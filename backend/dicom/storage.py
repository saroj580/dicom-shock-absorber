"""ProRadCS Enterprise DICOM Gateway & Edge Node - DICOM Storage Engine.

Implements MANDATE-DATA-002 (atomic .tmp write, os.fsync, and atomic rename to .dcm),
FR-DICOM-005 (transaction finality before C-STORE acknowledgement), FR-DICOM-006
(duplicate instance checksum collision and quarantine isolation), and Zero-PHI audit recording.
"""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Optional
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.filereader import dcmread
from pydicom.uid import ExplicitVRLittleEndian
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_INGEST,
    EVENT_SECURITY_VIOLATION,
    AuditLogger,
    audit_logger,
    hash_patient_id,
)
from backend.core.config import settings
from backend.core.database import DatabaseManager, db_manager
from backend.dicom.models import DimseStatus, DicomInstanceMetadata, StoreResult


class DicomStorageEngine:
    """Handles thread-safe persistence, checksumming, and quarantine routing for DICOM datasets."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        audit: Optional[AuditLogger] = None,
    ) -> None:
        self.db = db if db is not None else db_manager
        self.audit = audit if audit is not None else (AuditLogger(db=self.db) if db is not None else audit_logger)

    def extract_metadata(self, dataset: Dataset, calling_ae: str) -> DicomInstanceMetadata:
        """Extracts mandatory instance identifiers deterministically from incoming dataset."""
        sop_instance_uid = str(getattr(dataset, "SOPInstanceUID", "")).strip()
        sop_class_uid = str(getattr(dataset, "SOPClassUID", "")).strip()
        study_instance_uid = str(getattr(dataset, "StudyInstanceUID", "")).strip()
        series_instance_uid = str(getattr(dataset, "SeriesInstanceUID", "")).strip()

        if not sop_instance_uid or not sop_class_uid or not study_instance_uid:
            raise ValueError("Dataset is missing mandatory DICOM UIDs (SOPInstanceUID, SOPClassUID, or StudyInstanceUID).")

        modality = str(getattr(dataset, "Modality", "OT")).strip()
        raw_patient_id = str(getattr(dataset, "PatientID", "")).strip() or None

        # Transfer syntax from file_meta if present, otherwise default explicit VR little endian
        transfer_syntax = ExplicitVRLittleEndian
        if hasattr(dataset, "file_meta") and dataset.file_meta is not None:
            transfer_syntax = getattr(dataset.file_meta, "TransferSyntaxUID", ExplicitVRLittleEndian)

        return DicomInstanceMetadata(
            sop_instance_uid=sop_instance_uid,
            sop_class_uid=sop_class_uid,
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
            calling_ae_title=calling_ae,
            modality=modality,
            transfer_syntax_uid=str(transfer_syntax),
            raw_patient_id=raw_patient_id,
        )

    def persist_dataset(self, dataset: Dataset, calling_ae: str) -> StoreResult:
        """Persists a DICOM dataset atomically to disk adhering to MANDATE-DATA-002 and FR-DICOM-005/006."""
        settings.ensure_directories()

        # Step 1: Extract and validate metadata
        try:
            metadata = self.extract_metadata(dataset, calling_ae)
        except Exception as exc:
            # Route corrupted / unparseable payload to quarantine
            quarantine_path = self._quarantine_raw_dataset(dataset, calling_ae, reason=str(exc))
            return StoreResult(
                status_code=DimseStatus.DATASET_MISMATCH,
                file_path=quarantine_path,
                is_duplicate=False,
                error_message=f"Metadata extraction failed: {exc}",
            )

        study_dir = settings.staging_dir / metadata.study_instance_uid
        study_dir.mkdir(parents=True, exist_ok=True)

        final_dcm_path = study_dir / f"{metadata.sop_instance_uid}.dcm"
        temp_path = study_dir / f"{metadata.sop_instance_uid}.tmp"

        # Step 2: Atomic Write to .tmp file and compute SHA-256
        sha256 = hashlib.sha256()
        try:
            # Ensure dataset has valid file_meta for saving
            if not hasattr(dataset, "file_meta") or dataset.file_meta is None:
                meta = FileMetaDataset()
                meta.MediaStorageSOPClassUID = metadata.sop_class_uid
                meta.MediaStorageSOPInstanceUID = metadata.sop_instance_uid
                meta.TransferSyntaxUID = metadata.transfer_syntax_uid or ExplicitVRLittleEndian
                dataset.file_meta = meta
                dataset.is_little_endian = True
                dataset.is_implicit_VR = False

            # Write dataset to temporary file
            dataset.save_as(str(temp_path), write_like_original=False)

            # Read file, calculate SHA-256, and flush file buffers to physical disk (MANDATE-DATA-002)
            with open(temp_path, "rb+") as f:
                while chunk := f.read(65536):
                    sha256.update(chunk)
                f.flush()
                os.fsync(f.fileno())

            file_hash = sha256.hexdigest()
            file_size = temp_path.stat().st_size

        except Exception as write_err:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return StoreResult(
                status_code=DimseStatus.PROCESSING_FAILURE,
                file_path=None,
                file_size_bytes=0,
                error_message=f"I/O error during atomic write: {write_err}",
            )

        # Step 3: Duplicate SOP Handling (FR-DICOM-006)
        existing = self.db.get_instance_by_uid(metadata.sop_instance_uid)
        if existing is not None:
            if existing["sha256_hash"] == file_hash:
                # Identical instance already registered - discard temp file and reply Success
                temp_path.unlink(missing_ok=True)
                return StoreResult(
                    status_code=DimseStatus.SUCCESS,
                    file_path=Path(existing["original_file_path"]),
                    file_size_bytes=int(existing["file_size_bytes"]),
                    sha256_hash=file_hash,
                    is_duplicate=True,
                    error_message=None,
                )
            else:
                # Checksum differs! Quarantine new revision with -REV<timestamp> suffix
                rev_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                quarantine_dir = settings.quarantine_dir / metadata.study_instance_uid
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                quarantine_path = quarantine_dir / f"{metadata.sop_instance_uid}-REV{rev_timestamp}.dcm"
                
                temp_path.replace(quarantine_path)

                self.audit.record_event(
                    event_type=EVENT_SECURITY_VIOLATION,
                    actor=ACTOR_SERVICE_WORKER,
                    details={
                        "warning": "Duplicate SOPInstanceUID with differing SHA-256 hash detected",
                        "sop_instance_uid": metadata.sop_instance_uid,
                        "study_instance_uid": metadata.study_instance_uid,
                        "original_hash": existing["sha256_hash"],
                        "new_hash": file_hash,
                        "quarantined_path": str(quarantine_path),
                    },
                    patient_hash=hash_patient_id(metadata.raw_patient_id, settings.salt) if metadata.raw_patient_id else None,
                )

                return StoreResult(
                    status_code=DimseStatus.SUCCESS,
                    file_path=quarantine_path,
                    file_size_bytes=file_size,
                    sha256_hash=file_hash,
                    is_duplicate=True,
                    error_message="Differing checksum duplicate quarantined",
                )

        # Step 4: Atomic Rename from .tmp to .dcm (MANDATE-DATA-002)
        try:
            temp_path.replace(final_dcm_path)
        except Exception as rename_err:
            temp_path.unlink(missing_ok=True)
            return StoreResult(
                status_code=DimseStatus.PROCESSING_FAILURE,
                file_path=None,
                file_size_bytes=0,
                error_message=f"Atomic rename failed: {rename_err}",
            )

        # Step 5: Register in SQLite database as STAGED
        try:
            self.db.register_instance(
                sop_instance_uid=metadata.sop_instance_uid,
                sop_class_uid=metadata.sop_class_uid,
                study_instance_uid=metadata.study_instance_uid,
                series_instance_uid=metadata.series_instance_uid,
                calling_ae_title=metadata.calling_ae_title,
                original_file_path=str(final_dcm_path),
                file_size_bytes=file_size,
                sha256_hash=file_hash,
            )
        except Exception as db_err:
            # If database registration fails, isolate file to quarantine
            quarantine_path = settings.quarantine_dir / f"DB_FAIL_{metadata.sop_instance_uid}.dcm"
            final_dcm_path.replace(quarantine_path)
            return StoreResult(
                status_code=DimseStatus.PROCESSING_FAILURE,
                file_path=quarantine_path,
                file_size_bytes=file_size,
                error_message=f"Database staging registration failed: {db_err}",
            )

        # Step 6: Log cryptographic audit event (Zero-PHI)
        patient_hash = hash_patient_id(metadata.raw_patient_id, settings.salt) if metadata.raw_patient_id else None
        self.audit.record_event(
            event_type=EVENT_INGEST,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "sop_instance_uid": metadata.sop_instance_uid,
                "study_instance_uid": metadata.study_instance_uid,
                "series_instance_uid": metadata.series_instance_uid,
                "calling_ae": metadata.calling_ae_title,
                "file_size_bytes": file_size,
                "sha256": file_hash,
                "pipeline_status": "STAGED",
            },
            patient_hash=patient_hash,
        )

        return StoreResult(
            status_code=DimseStatus.SUCCESS,
            file_path=final_dcm_path,
            file_size_bytes=file_size,
            sha256_hash=file_hash,
            is_duplicate=False,
            error_message=None,
        )

    def _quarantine_raw_dataset(self, dataset: Dataset, calling_ae: str, reason: str) -> Path:
        """Saves an invalid or unparseable dataset directly into quarantine."""
        settings.ensure_directories()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        target_path = settings.quarantine_dir / f"CORRUPT_{calling_ae}_{timestamp}.dcm"
        try:
            dataset.save_as(str(target_path), write_like_original=False)
        except Exception:
            # Write fallback raw marker file if save_as fails
            target_path.write_text(f"Unparseable dataset received from {calling_ae}. Error: {reason}")
        return target_path


# Global storage engine singleton
storage_engine = DicomStorageEngine()
