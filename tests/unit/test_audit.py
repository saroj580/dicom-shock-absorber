"""Unit tests for cryptographic blockchain-style AuditLogger and Zero-PHI compliance."""

from pathlib import Path
import pytest
from backend.core.database import DatabaseManager
from backend.core.audit import (
    AuditLogger,
    PHISecurityException,
    hash_patient_id,
    ACTOR_SERVICE_WORKER,
    EVENT_INGEST,
)


@pytest.fixture
def audit_db(tmp_path: Path) -> DatabaseManager:
    """Fixture creating an isolated test database with schema initialized."""
    db_file = tmp_path / "test_audit.db"
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema(seed_defaults=False)
    return mgr


@pytest.fixture
def audit_logger(audit_db: DatabaseManager) -> AuditLogger:
    """Fixture creating an AuditLogger bound to the isolated database."""
    return AuditLogger(db=audit_db)


def test_hash_patient_id_deterministic() -> None:
    """Verifies patient ID hashing produces deterministic 64-char hex strings with salt."""
    salt = "SECURE_TEST_SALT_12345678"
    pt_id = "PATIENT_98765"

    h1 = hash_patient_id(pt_id, salt)
    h2 = hash_patient_id(pt_id, salt)

    assert len(h1) == 64
    assert h1 == h2
    assert h1 != hash_patient_id(pt_id, "DIFFERENT_SALT_99999999")


def test_audit_event_chaining_and_verification(audit_logger: AuditLogger) -> None:
    """Verifies sequential audit entries form a valid cryptographic SHA-256 chain."""
    # 1. First event (Genesis block)
    id1 = audit_logger.record_event(
        event_type=EVENT_INGEST,
        actor=ACTOR_SERVICE_WORKER,
        details={"study_uid": "1.2.3.4", "instances": 1},
        patient_hash="0123456789abcdef",
    )
    assert id1 == 1

    # 2. Second event
    id2 = audit_logger.record_event(
        event_type="ANONYMIZATION",
        actor=ACTOR_SERVICE_WORKER,
        details={"study_uid": "1.2.3.4", "status": "ANONYMIZED"},
        patient_hash="0123456789abcdef",
    )
    assert id2 == 2

    # 3. Third event
    id3 = audit_logger.record_event(
        event_type="STOW_RS_FORWARD",
        actor=ACTOR_SERVICE_WORKER,
        details={"study_uid": "1.2.3.4", "status": "FORWARDED"},
    )
    assert id3 == 3

    # Chain verification
    is_valid, error = audit_logger.verify_chain_integrity()
    assert is_valid is True
    assert error is None


def test_audit_tamper_detection(audit_logger: AuditLogger, audit_db: DatabaseManager) -> None:
    """Verifies that tampering with database records breaks the cryptographic chain."""
    audit_logger.record_event(
        event_type=EVENT_INGEST,
        actor=ACTOR_SERVICE_WORKER,
        details={"action": "INGEST_1"},
    )
    audit_logger.record_event(
        event_type=EVENT_INGEST,
        actor=ACTOR_SERVICE_WORKER,
        details={"action": "INGEST_2"},
    )

    # Tamper with the first record in SQLite
    with audit_db.get_connection(read_only=False) as conn:
        conn.execute("UPDATE audit_logs SET actor = 'MaliciousAttacker' WHERE log_id = 1;")

    is_valid, error = audit_logger.verify_chain_integrity()
    assert is_valid is False
    assert error is not None
    assert "log_id=1" in error


def test_mandate_phi_forbidden_keys_rejected(audit_logger: AuditLogger) -> None:
    """Verifies MANDATE-PHI-001: logging patient_name or birth_date raises PHISecurityException."""
    with pytest.raises(PHISecurityException, match="MANDATE-PHI-001 Violation"):
        audit_logger.record_event(
            event_type="SECURITY_TEST",
            actor="Admin",
            details={"patient_name": "John Doe", "status": "PENDING"},
        )

    with pytest.raises(PHISecurityException, match="MANDATE-PHI-001 Violation"):
        audit_logger.record_event(
            event_type="SECURITY_TEST",
            actor="Admin",
            details={"birth_date": "1980-01-01", "status": "PENDING"},
        )
