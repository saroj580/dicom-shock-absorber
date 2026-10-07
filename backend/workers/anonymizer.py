"""ProRadCS Enterprise DICOM Gateway & Edge Node - De-Identification Engine.

Implements DICOM PS 3.15 Annex E Basic Application Level Confidentiality Profile (FR-PROC-001)
with deterministic, salted longitudinal pseudonymization, Zero-PHI logging, and diagnostic
geometry preservation.
"""

import hashlib
import logging
from typing import Optional
from pydicom.dataset import Dataset
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_ANONYMIZATION,
    AuditLogger,
    audit_logger,
    hash_patient_id,
)
from backend.core.config import settings


logger = logging.getLogger("proradcs.workers.anonymizer")

# DICOM Tags requiring mandatory removal per PS 3.15 Annex E
TAGS_TO_REMOVE = [
    (0x0010, 0x1000),  # Other Patient IDs
    (0x0010, 0x1001),  # Other Patient Names
    (0x0010, 0x1040),  # Patient's Address
    (0x0010, 0x1060),  # Patient's Mother's Birth Name
    (0x0010, 0x2154),  # Patient's Telephone Numbers
    (0x0010, 0x21F0),  # Patient's Religious Preference
    (0x0010, 0x4000),  # Patient Comments
    (0x0038, 0x0010),  # Admission ID
    (0x0038, 0x0011),  # Issuer of Admission ID
    (0x0040, 0x1001),  # Requested Procedure ID
    (0x0040, 0x1004),  # Patient Transport Arrangements
]


class DicomAnonymizer:
    """Sanitizes DICOM datasets adhering to PS 3.15 Annex E Basic Confidentiality Profile."""

    def __init__(self, salt: Optional[str] = None, audit: Optional[AuditLogger] = None) -> None:
        self.salt = salt if salt is not None else settings.salt
        self.audit = audit if audit is not None else audit_logger

    def generate_pseudo_id(self, original_id: str, prefix: str = "ANON-PT-") -> str:
        """Generates reproducible, irreversible pseudonym for longitudinal study linkage."""
        if not original_id:
            return f"{prefix}UNKNOWN"
        raw_digest = hashlib.sha256(f"{self.salt}:PATIENT_ID:{original_id}".encode("utf-8")).hexdigest()
        return f"{prefix}{raw_digest[:12].upper()}"

    def generate_pseudo_accession(self, original_acc: str, prefix: str = "ACC-") -> str:
        """Generates reproducible, irreversible accession number pseudonym."""
        if not original_acc:
            return f"{prefix}000000"
        raw_digest = hashlib.sha256(f"{self.salt}:ACCESSION:{original_acc}".encode("utf-8")).hexdigest()
        return f"{prefix}{raw_digest[:8].upper()}"

    def anonymize_dataset(self, dataset: Dataset) -> Dataset:
        """Applies DICOM PS 3.15 Annex E sanitization in-place and sets audit headers."""
        raw_patient_id = str(getattr(dataset, "PatientID", "")).strip()
        raw_accession = str(getattr(dataset, "AccessionNumber", "")).strip()
        study_uid = str(getattr(dataset, "StudyInstanceUID", "UNKNOWN_STUDY"))
        sop_uid = str(getattr(dataset, "SOPInstanceUID", "UNKNOWN_SOP"))

        # Compute deterministic pseudonyms
        pseudo_patient_id = self.generate_pseudo_id(raw_patient_id)
        pseudo_accession = self.generate_pseudo_accession(raw_accession)

        # 1. Replace Direct Patient Identifiers
        dataset.PatientName = "ANONYMIZED"
        dataset.PatientID = pseudo_patient_id
        dataset.PatientBirthDate = "19000101"
        dataset.AccessionNumber = pseudo_accession

        # 2. Redact Institutional & Physician Identifiers
        if hasattr(dataset, "InstitutionName"):
            dataset.InstitutionName = "REDACTED_INSTITUTION"
        if hasattr(dataset, "InstitutionAddress"):
            dataset.InstitutionAddress = "REDACTED"
        if hasattr(dataset, "ReferringPhysicianName"):
            dataset.ReferringPhysicianName = "REDACTED"
        if hasattr(dataset, "PhysiciansOfRecord"):
            dataset.PhysiciansOfRecord = "REDACTED"
        if hasattr(dataset, "PerformingPhysicianName"):
            dataset.PerformingPhysicianName = "REDACTED"
        if hasattr(dataset, "OperatorsName"):
            dataset.OperatorsName = "REDACTED"
        if hasattr(dataset, "StationName"):
            dataset.StationName = "EDGE_GATEWAY"
        if hasattr(dataset, "InstitutionalDepartmentName"):
            dataset.InstitutionalDepartmentName = "REDACTED"

        # 3. Remove High-Risk Secondary Identifiers
        for tag in TAGS_TO_REMOVE:
            if tag in dataset:
                del dataset[tag]

        # 4. Mandatory PS 3.15 De-identification Indicators
        dataset.PatientIdentityRemoved = "YES"
        dataset.DeidentificationMethod = "DICOM PS 3.15 Annex E Basic Profile / ProRadCS Edge"

        # 5. Log Cryptographic Audit Trail (Zero-PHI strictly enforced)
        patient_hash = hash_patient_id(raw_patient_id, self.salt) if raw_patient_id else None
        self.audit.record_event(
            event_type=EVENT_ANONYMIZATION,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "sop_instance_uid": sop_uid,
                "study_instance_uid": study_uid,
                "pseudo_patient_id": pseudo_patient_id,
                "profile": "DICOM PS 3.15 Annex E Basic Profile",
            },
            patient_hash=patient_hash,
        )

        return dataset


# Global anonymizer singleton
anonymizer = DicomAnonymizer()
