"""Unit tests for FastAPI REST API routes, models, and dashboard actions."""

from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from backend.core.config import settings
from backend.core.database import db_manager
from backend.core.audit import audit_logger, ACTOR_SERVICE_WORKER, EVENT_INGEST
from backend.api.service import create_app


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Fixture providing an isolated FastAPI TestClient with temporary database."""
    original_db_path = db_manager.db_path
    original_audit_db = audit_logger.db

    test_db = tmp_path / "test_api_sqlite.db"
    db_manager.db_path = test_db
    db_manager.initialize_schema(seed_defaults=True)
    audit_logger.db = db_manager

    app = create_app(audit=audit_logger)
    with TestClient(app) as test_client:
        yield test_client

    db_manager.db_path = original_db_path
    audit_logger.db = original_audit_db


def test_get_health(client: TestClient) -> None:
    """Verifies GET /api/health returns 200 OK with proper system telemetry."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert data["version"] == "1.0.0-PROD"
    assert data["database_connected"] is True
    assert data["ae_title"] == settings.ae_title
    assert data["dicom_port"] == settings.dicom_port


def test_get_telemetry(client: TestClient) -> None:
    """Verifies GET /api/telemetry returns hardware, storage, and queue metrics."""
    response = client.get("/api/telemetry")
    assert response.status_code == 200
    data = response.json()

    assert "storage" in data
    assert "queues" in data
    assert "cpu_percent" in data
    assert "memory_percent" in data
    assert "database_size_bytes" in data
    assert "is_watermark_safe" in data["storage"]


def test_modalities_crud_and_toggle(client: TestClient) -> None:
    """Verifies modality whitelisting: listing, creation, duplicate rejection, and toggle."""
    # 1. Verify default seeded modalities exist
    resp = client.get("/api/modalities")
    assert resp.status_code == 200
    modalities = resp.json()
    ae_titles = [m["ae_title"] for m in modalities]
    assert "CT_SCANNER_01" in ae_titles
    assert "MR_SCANNER_01" in ae_titles

    # 2. Register a new clinical modality
    new_modality = {
        "ae_title": "XRAY_PORTABLE_01",
        "ip_address": "192.168.2.55",
        "description": "Mobile Emergency X-Ray",
        "is_active": True,
    }
    resp_create = client.post("/api/modalities", json=new_modality)
    assert resp_create.status_code == 201
    created = resp_create.json()
    assert created["ae_title"] == "XRAY_PORTABLE_01"
    assert created["is_active"] == 1

    # 3. Duplicate registration is rejected with 409 Conflict
    resp_dup = client.post("/api/modalities", json=new_modality)
    assert resp_dup.status_code == 409

    # 4. Toggle modality active state
    resp_toggle = client.post("/api/modalities/XRAY_PORTABLE_01/toggle")
    assert resp_toggle.status_code == 200
    assert resp_toggle.json()["success"] is True

    # Verify state was toggled to inactive (0)
    resp_list = client.get("/api/modalities")
    matched = [m for m in resp_list.json() if m["ae_title"] == "XRAY_PORTABLE_01"][0]
    assert matched["is_active"] == 0

    # 5. Toggle non-existent modality returns 404
    resp_404 = client.post("/api/modalities/NONEXISTENT_AE/toggle")
    assert resp_404.status_code == 404


def test_queue_inspection_and_filtering(client: TestClient) -> None:
    """Verifies GET /api/queue pagination and status filtering."""
    # Seed sample instances
    db_manager.register_instance(
        sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.TEST.1",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.7",
        study_instance_uid="1.2.840.10008.5.1.4.1.1.7.STUDY.1",
        series_instance_uid="1.2.840.10008.5.1.4.1.1.7.SERIES.1",
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:\\DICOM_Archive\\staged\\test1.dcm",
        file_size_bytes=524288,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    db_manager.register_instance(
        sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.TEST.2",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.7",
        study_instance_uid="1.2.840.10008.5.1.4.1.1.7.STUDY.1",
        series_instance_uid="1.2.840.10008.5.1.4.1.1.7.SERIES.1",
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:\\DICOM_Archive\\staged\\test2.dcm",
        file_size_bytes=262144,
        sha256_hash="f4c0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b866",
    )
    # Transition second instance to PROCESSED
    db_manager.update_instance_status(
        sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.TEST.2",
        status="PROCESSED",
        processed_file_path="D:\\DICOM_Archive\\processed\\test2.dcm",
    )

    # 1. Query all queue instances
    resp_all = client.get("/api/queue")
    assert resp_all.status_code == 200
    data_all = resp_all.json()
    assert data_all["total_count"] == 2
    assert len(data_all["instances"]) == 2

    # 2. Filter by status=STAGED
    resp_staged = client.get("/api/queue?status=STAGED")
    assert resp_staged.status_code == 200
    data_staged = resp_staged.json()
    assert data_staged["total_count"] == 1
    assert data_staged["instances"][0]["sop_instance_uid"] == "1.2.840.10008.5.1.4.1.1.7.TEST.1"

    # 3. Filter by status=PROCESSED
    resp_processed = client.get("/api/queue?status=PROCESSED")
    assert resp_processed.status_code == 200
    data_proc = resp_processed.json()
    assert data_proc["total_count"] == 1
    assert data_proc["instances"][0]["sop_instance_uid"] == "1.2.840.10008.5.1.4.1.1.7.TEST.2"


def test_audit_trail_and_verification(client: TestClient) -> None:
    """Verifies audit trail listing and cryptographic SHA-256 chain verification."""
    # Record an ingest event
    audit_logger.record_event(
        event_type=EVENT_INGEST,
        actor=ACTOR_SERVICE_WORKER,
        details={"study_instance_uid": "1.2.3.4", "count": 1},
        patient_hash="a1b2c3d4e5f60718293a4b5c6d7e8f90",
    )

    # 1. Retrieve audit trail
    resp_trail = client.get("/api/audit")
    assert resp_trail.status_code == 200
    trail = resp_trail.json()
    assert len(trail) >= 1
    latest = trail[0]
    assert latest["actor"] == ACTOR_SERVICE_WORKER

    # 2. Verify audit chain integrity
    resp_verify = client.get("/api/audit/verify")
    assert resp_verify.status_code == 200
    verify_data = resp_verify.json()
    assert verify_data["is_chain_intact"] is True
    assert verify_data["total_records_verified"] >= 1
    assert verify_data["error_message"] is None


def test_wal_checkpoint_action(client: TestClient) -> None:
    """Verifies POST /api/actions/checkpoint executes PRAGMA wal_checkpoint(TRUNCATE)."""
    resp = client.post("/api/actions/checkpoint")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "checkpoint" in data["message"].lower()
    assert "checkpointed" in data["details"]
