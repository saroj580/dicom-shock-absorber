"""Unit tests for DICOM PS 3.15 Annex E Anonymizer."""

from pathlib import Path
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
from backend.core.database import DatabaseManager
from backend.core.audit import AuditLogger
from backend.workers.anonymizer import DicomAnonymizer


@pytest.fixture
def anon_db(tmp_path: Path) -> DatabaseManager:
    """Fixture creating an isolated test database with schema initialized."""
    db_file = tmp_path / "anon_test.db"
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema(seed_defaults=False)
    return mgr


@pytest.fixture
def anonymizer(anon_db: DatabaseManager) -> DicomAnonymizer:
    """Fixture creating a DicomAnonymizer instance with audit logger."""
    audit = AuditLogger(db=anon_db)
    return DicomAnonymizer(salt="TEST_SALT_SECRET_77777777", audit=audit)


def create_sample_dataset() -> Dataset:
    """Creates a sample DICOM dataset populated with sensitive clinical PHI."""
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7.999"

    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7.999"
    ds.StudyInstanceUID = "1.2.840.10008.5.1.4.1.1.7.100.1"
    ds.SeriesInstanceUID = "1.2.840.10008.5.1.4.1.1.7.200.1"

    # Sensitive Direct PHI
    ds.PatientName = "Smith^John^A"
    ds.PatientID = "HOSPITAL_PT_12345"
    ds.PatientBirthDate = "19750815"
    ds.AccessionNumber = "ACC_998877"

    # Institutional Tags
    ds.InstitutionName = "Metropolitan General Hospital"
    ds.ReferringPhysicianName = "Dr. Marcus Welby"
    ds.StationName = "CT_ROOM_4"

    # Secondary tags to delete
    ds.PatientAddress = "123 Main Street, Suite 400"

    return ds


def test_ps315_phi_redaction(anonymizer: DicomAnonymizer) -> None:
    """Verifies direct identifiers are pseudonymized and secondary tags are purged."""
    ds = create_sample_dataset()
    anonymized = anonymizer.anonymize_dataset(ds)

    # Direct Identifiers Sanitized
    assert str(anonymized.PatientName) == "ANONYMIZED"
    assert str(anonymized.PatientID).startswith("ANON-PT-")
    assert str(anonymized.PatientID) != "HOSPITAL_PT_12345"
    assert str(anonymized.PatientBirthDate) == "19000101"
    assert str(anonymized.AccessionNumber).startswith("ACC-")

    # Institutional Redactions
    assert anonymized.InstitutionName == "REDACTED_INSTITUTION"
    assert anonymized.ReferringPhysicianName == "REDACTED"
    assert anonymized.StationName == "EDGE_GATEWAY"

    # Secondary tags purged
    assert (0x0010, 0x1040) not in anonymized

    # Mandatory Indicators
    assert anonymized.PatientIdentityRemoved == "YES"
    assert "DICOM PS 3.15 Annex E" in anonymized.DeidentificationMethod


def test_deterministic_longitudinal_linkage(anonymizer: DicomAnonymizer) -> None:
    """Verifies that the same Patient ID produces the exact same pseudonym."""
    id1 = anonymizer.generate_pseudo_id("PATIENT_555")
    id2 = anonymizer.generate_pseudo_id("PATIENT_555")
    id3 = anonymizer.generate_pseudo_id("PATIENT_777")

    assert id1 == id2
    assert id1 != id3
    assert id1.startswith("ANON-PT-")


def test_anonymization_audit_logging(anonymizer: DicomAnonymizer, anon_db: DatabaseManager) -> None:
    """Verifies that anonymization records an audit event with Zero-PHI compliance."""
    ds = create_sample_dataset()
    anonymizer.anonymize_dataset(ds)

    with anon_db.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY log_id DESC LIMIT 1;")
        latest = cursor.fetchone()
        cursor.close()

    assert latest is not None
    assert latest["event_type"] == "ANONYMIZATION"
    assert latest["actor"] == "PacsServiceWorker"
    assert "Smith" not in latest["details"]
    assert "HOSPITAL_PT_12345" not in latest["details"]
    assert latest["patient_hash"] is not None


def test_empty_identifiers_handling(anonymizer: DicomAnonymizer) -> None:
    """Verifies anonymizer gracefully handles empty patient ID and accession."""
    pseudo_id = anonymizer.generate_pseudo_id("")
    assert pseudo_id == "ANON-PT-UNKNOWN"

    pseudo_acc = anonymizer.generate_pseudo_accession("")
    assert pseudo_acc == "ACC-000000"

