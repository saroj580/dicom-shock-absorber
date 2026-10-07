"""Unit tests for SQLite WAL DatabaseManager and concurrency operations."""

from pathlib import Path
import sqlite3
import pytest
from backend.core.database import DatabaseManager


@pytest.fixture
def test_db(tmp_path: Path) -> DatabaseManager:
    """Fixture initializing an isolated SQLite database in a temporary directory."""
    db_file = tmp_path / "test_gateway.db"
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema(seed_defaults=True)
    return mgr


def test_schema_and_wal_mode_enforcement(test_db: DatabaseManager) -> None:
    """Verifies SQLite initializes in WAL mode with enforced PRAGMAs."""
    with test_db.get_connection(read_only=False) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode.lower() == "wal"

        cursor.execute("PRAGMA foreign_keys;")
        foreign_keys = cursor.fetchone()[0]
        assert foreign_keys == 1


def test_modality_registry_whitelist(test_db: DatabaseManager) -> None:
    """Verifies AE Title authorization against modality_registry."""
    # Seeded modalities should be allowed
    assert test_db.is_ae_title_allowed("CT_SCANNER_01", "127.0.0.1") is True
    assert test_db.is_ae_title_allowed("MR_SCANNER_01", "127.0.0.1") is True
    assert test_db.is_ae_title_allowed("ANY_TEST_SCU", "192.168.1.100") is True

    # Unknown AE title should be rejected
    assert test_db.is_ae_title_allowed("UNKNOWN_SCU", "127.0.0.1") is False

    # Deactivating modality
    with test_db.get_connection(read_only=False) as conn:
        conn.execute("UPDATE modality_registry SET is_active = 0 WHERE ae_title = 'CT_SCANNER_01';")

    assert test_db.is_ae_title_allowed("CT_SCANNER_01", "127.0.0.1") is False


def test_instance_registration_and_atomic_claim(test_db: DatabaseManager) -> None:
    """Verifies register_instance writes STAGED and claim_next_staged_instance claims it."""
    sop_uid = "1.2.840.10008.1.999.1"
    study_uid = "1.2.840.10008.2.999.1"
    series_uid = "1.2.840.10008.3.999.1"

    success = test_db.register_instance(
        sop_instance_uid=sop_uid,
        sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
        study_instance_uid=study_uid,
        series_instance_uid=series_uid,
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:/DICOM_Archive/staging/test.dcm",
        file_size_bytes=524288,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    assert success is True

    # Atomic Claim via RETURNING *
    claimed = test_db.claim_next_staged_instance()
    assert claimed is not None
    assert claimed["sop_instance_uid"] == sop_uid
    assert claimed["pipeline_status"] == "PROCESSING"

    # Second claim should return None as the row is now PROCESSING
    second_claim = test_db.claim_next_staged_instance()
    assert second_claim is None


def test_duplicate_instance_insertion_raises_integrity_error(test_db: DatabaseManager) -> None:
    """Verifies primary key constraint prevents duplicate SOP Instance UIDs."""
    sop_uid = "1.2.840.10008.1.999.DUP"

    test_db.register_instance(
        sop_instance_uid=sop_uid,
        sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
        study_instance_uid="1.2.840.10008.2.999.DUP",
        series_instance_uid="1.2.840.10008.3.999.DUP",
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:/test.dcm",
        file_size_bytes=1000,
        sha256_hash="hash1",
    )

    with pytest.raises(sqlite3.IntegrityError):
        test_db.register_instance(
            sop_instance_uid=sop_uid,
            sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
            study_instance_uid="1.2.840.10008.2.999.DUP",
            series_instance_uid="1.2.840.10008.3.999.DUP",
            calling_ae_title="CT_SCANNER_01",
            original_file_path="D:/test.dcm",
            file_size_bytes=1000,
            sha256_hash="hash1",
        )


def test_instance_status_transitions_and_query(test_db: DatabaseManager) -> None:
    """Verifies status transitions to PROCESSED and FORWARDED and metadata query."""
    sop_uid = "1.2.840.10008.1.999.STATUS"

    test_db.register_instance(
        sop_instance_uid=sop_uid,
        sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
        study_instance_uid="1.2.840.10008.2.999.STATUS",
        series_instance_uid="1.2.840.10008.3.999.STATUS",
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:/test.dcm",
        file_size_bytes=1000,
        sha256_hash="hash_status",
    )

    inst = test_db.get_instance_by_uid(sop_uid)
    assert inst is not None
    assert inst["pipeline_status"] == "STAGED"

    test_db.update_instance_status(sop_instance_uid=sop_uid, status="PROCESSED")
    inst = test_db.get_instance_by_uid(sop_uid)
    assert inst is not None
    assert inst["pipeline_status"] == "PROCESSED"
    assert inst["processed_at"] is not None

    test_db.update_instance_status(sop_instance_uid=sop_uid, status="FORWARDED")
    inst = test_db.get_instance_by_uid(sop_uid)
    assert inst is not None
    assert inst["pipeline_status"] == "FORWARDED"
    assert inst["forwarded_at"] is not None
