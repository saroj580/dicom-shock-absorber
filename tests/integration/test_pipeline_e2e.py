"""End-to-End Integration Tests for ProRadCS Enterprise DICOM Gateway & Edge Node.

Validates complete medical imaging lifecycle:
1. Ingestion: C-STORE SCP storage engine with atomic disk flush and STAGED registration.
2. Processing: Multi-process worker claim, PS 3.15 de-identification, and JPEG 2000 lossless compression.
3. Relay: DICOMweb STOW-RS HTTPS forward and state transition to FORWARDED.
4. Compliance: Cryptographic SHA-256 blockchain audit trail verification and Zero-PHI integrity.
"""

from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless, CTImageStorage
import httpx

from backend.core.config import EdgeSettings
from backend.core.database import DatabaseManager
from backend.core.audit import AuditLogger
from backend.dicom.models import DimseStatus
from backend.dicom.storage import DicomStorageEngine
from backend.workers.anonymizer import DicomAnonymizer
from backend.workers.transcoder import DicomTranscoder
from backend.workers.uploader import StowRsUploader
from backend.workers.service import ProcessorWorkerDaemon


@pytest.fixture
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Configures fully isolated filesystem and database environment for pipeline execution."""
    archive_dir = tmp_path / "DICOM_Archive"
    db_file = tmp_path / "gateway_e2e.db"

    # Initialize isolated settings overrides
    custom_settings = EdgeSettings(
        archive_dir=archive_dir,
        db_path_override=db_file,
        salt="E2E_SECRET_SALT_VALUE_88888888",
        cloud_endpoint="https://cloud.orthanc-vna.hospital.org/dicom-web/studies",
        node_token="Bearer E2E_AUTH_TOKEN",
    )
    custom_settings.ensure_directories()

    # Initialize isolated database
    db = DatabaseManager(db_path=db_file)
    db.initialize_schema(seed_defaults=True)

    # Audit logger bound to isolated DB
    audit = AuditLogger(db=db)

    # Patch settings in global modules
    monkeypatch.setattr("backend.core.config.settings", custom_settings)
    monkeypatch.setattr("backend.dicom.storage.settings", custom_settings)
    monkeypatch.setattr("backend.workers.service.settings", custom_settings)
    monkeypatch.setattr("backend.workers.transcoder.settings", custom_settings)

    # Components wired together
    storage_engine = DicomStorageEngine(db=db, audit=audit)
    anonymizer = DicomAnonymizer(salt=custom_settings.salt, audit=audit)
    transcoder = DicomTranscoder(max_workers=2, audit=audit)
    uploader = StowRsUploader(
        endpoint=custom_settings.cloud_endpoint,
        token=custom_settings.node_token,
        audit=audit,
    )

    worker = ProcessorWorkerDaemon(
        db=db,
        anon=anonymizer,
        trans=transcoder,
        up=uploader,
        audit=audit,
    )

    return {
        "db": db,
        "audit": audit,
        "settings": custom_settings,
        "storage": storage_engine,
        "worker": worker,
        "uploader": uploader,
        "tmp_path": tmp_path,
    }


def create_clinical_ct_dataset() -> Dataset:
    """Generates an uncompressed diagnostic CT DICOM dataset with sensitive clinical PHI."""
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = "1.2.840.10008.5.1.4.1.1.2.999999.1"

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.2.999999.1"
    ds.StudyInstanceUID = "1.2.840.10008.5.1.4.1.1.2.777.1"
    ds.SeriesInstanceUID = "1.2.840.10008.5.1.4.1.1.2.888.1"
    ds.Modality = "CT"

    # Sensitive Patient & Institutional PHI
    ds.PatientName = "Doe^Jane^E"
    ds.PatientID = "HOSPITAL_PATIENT_8899"
    ds.PatientBirthDate = "19681123"
    ds.AccessionNumber = "ACC-CT-54321"
    ds.InstitutionName = "St. Jude Regional Medical Center"
    ds.ReferringPhysicianName = "Dr. Gregory House"
    ds.StationName = "CT_SUITE_B"

    # Image Geometry & 64x64 Pixel Matrix
    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"

    pixel_data = np.arange(64 * 64, dtype=np.uint16).reshape((64, 64))
    ds.PixelData = pixel_data.tobytes()

    return ds


def test_end_to_end_ingest_process_upload_pipeline(test_env: dict) -> None:
    """Executes full pipeline: Ingest -> STAGED -> PROCESSING -> Anonymize -> Transcode -> STOW-RS -> FORWARDED."""
    db: DatabaseManager = test_env["db"]
    audit: AuditLogger = test_env["audit"]
    storage: DicomStorageEngine = test_env["storage"]
    worker: ProcessorWorkerDaemon = test_env["worker"]
    settings: EdgeSettings = test_env["settings"]

    ct_dataset = create_clinical_ct_dataset()
    sop_uid = str(ct_dataset.SOPInstanceUID)
    study_uid = str(ct_dataset.StudyInstanceUID)

    # -------------------------------------------------------------------------
    # Step 1: DICOM Receiver Ingestion (C-STORE SCP Simulation)
    # -------------------------------------------------------------------------
    store_result = storage.persist_dataset(
        dataset=ct_dataset,
        calling_ae="CT_SCANNER_01",
    )
    assert store_result.status_code == DimseStatus.SUCCESS, f"Store failed: {store_result.error_message}"
    assert store_result.file_path is not None
    assert Path(store_result.file_path).exists()

    # Verify Database State: STAGED
    instance_rec = db.get_instance_by_uid(sop_uid)
    assert instance_rec is not None
    assert instance_rec["pipeline_status"] == "STAGED"
    assert instance_rec["calling_ae_title"] == "CT_SCANNER_01"

    # -------------------------------------------------------------------------
    # Step 2: Processor Worker Claim (Atomic UPDATE ... RETURNING)
    # -------------------------------------------------------------------------
    claimed = db.claim_next_staged_instance()
    assert claimed is not None
    assert claimed["sop_instance_uid"] == sop_uid
    assert claimed["pipeline_status"] == "PROCESSING"

    # -------------------------------------------------------------------------
    # Step 3: Worker Processing & Mocked STOW-RS Upload
    # -------------------------------------------------------------------------
    mock_resp = httpx.Response(
        status_code=200,
        text='{"status": "success", "study_uid": "' + study_uid + '"}',
        request=httpx.Request("POST", settings.cloud_endpoint),
    )

    with patch.object(httpx.Client, "post", return_value=mock_resp) as mock_post:
        worker.process_claimed_instance(claimed)
        mock_post.assert_called_once()

    # -------------------------------------------------------------------------
    # Step 4: Verification of Final Forwarded State & Transcoded Artifact
    # -------------------------------------------------------------------------
    final_rec = db.get_instance_by_uid(sop_uid)
    assert final_rec is not None
    assert final_rec["pipeline_status"] == "FORWARDED"
    assert final_rec["processed_file_path"] is not None

    processed_path = Path(final_rec["processed_file_path"])
    assert processed_path.exists()

    # Inspect processed DICOM file
    transcoded_ds = pydicom.dcmread(str(processed_path))
    assert transcoded_ds.file_meta.TransferSyntaxUID == JPEG2000Lossless

    # Verify PS 3.15 Annex E Anonymization in processed file
    assert str(transcoded_ds.PatientName) == "ANONYMIZED"
    assert str(transcoded_ds.PatientID).startswith("ANON-PT-")
    assert str(transcoded_ds.PatientID) != "HOSPITAL_PATIENT_8899"
    assert transcoded_ds.PatientIdentityRemoved == "YES"
    assert transcoded_ds.InstitutionName == "REDACTED_INSTITUTION"

    # -------------------------------------------------------------------------
    # Step 5: Cryptographic Audit Trail & Zero-PHI Verification
    # -------------------------------------------------------------------------
    is_valid, failure_reason = audit.verify_chain_integrity()
    assert is_valid is True, f"Audit chain broken: {failure_reason}"

    with db.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY log_id ASC;")
        logs = cursor.fetchall()
        cursor.close()

    assert len(logs) >= 4  # INGEST, ANONYMIZATION, TRANSCODE, FORWARD_SUCCESS
    event_types = [r["event_type"] for r in logs]
    assert "C_STORE_INGEST" in event_types
    assert "ANONYMIZATION" in event_types
    assert "TRANSCODE" in event_types
    assert "FORWARD_SUCCESS" in event_types

    # Strict Zero-PHI Check: Raw patient name / ID must never exist in audit rows
    for row in logs:
        assert "Jane" not in row["details"]
        assert "Doe" not in row["details"]
        assert "HOSPITAL_PATIENT_8899" not in row["details"]


def test_pipeline_offline_stow_rs_retry(test_env: dict) -> None:
    """Verifies that WAN dropouts keep instances safely parked in PROCESSED with retry counter."""
    db: DatabaseManager = test_env["db"]
    storage: DicomStorageEngine = test_env["storage"]
    worker: ProcessorWorkerDaemon = test_env["worker"]
    settings: EdgeSettings = test_env["settings"]

    ct_dataset = create_clinical_ct_dataset()
    ct_dataset.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.2.111.1"
    ct_dataset.file_meta.MediaStorageSOPInstanceUID = "1.2.840.10008.5.1.4.1.1.2.111.1"
    sop_uid = str(ct_dataset.SOPInstanceUID)

    # Ingest
    store_res = storage.persist_dataset(dataset=ct_dataset, calling_ae="CT_SCANNER_01")
    assert store_res.status_code == DimseStatus.SUCCESS

    # Claim
    claimed = db.claim_next_staged_instance()
    assert claimed is not None

    # Simulate WAN failure (HTTP 503 Service Unavailable)
    mock_resp = httpx.Response(
        status_code=503,
        text="Gateway Timeout: Cloud VNA Offline",
        request=httpx.Request("POST", settings.cloud_endpoint),
    )

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        worker.process_claimed_instance(claimed)

    # Verify instance state: parked in PROCESSED for retry, retry_count incremented
    rec = db.get_instance_by_uid(sop_uid)
    assert rec is not None
    assert rec["pipeline_status"] == "PROCESSED"
    assert rec["retry_count"] == 1
    assert "503" in rec["error_message"]
