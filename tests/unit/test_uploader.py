"""Unit tests for DICOMweb STOW-RS cloud uploader and retry calculation."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import httpx
from backend.core.database import DatabaseManager
from backend.core.audit import AuditLogger
from backend.workers.uploader import StowRsUploader


@pytest.fixture
def uploader_db(tmp_path: Path) -> DatabaseManager:
    """Fixture creating an isolated test database with schema initialized."""
    db_file = tmp_path / "uploader_test.db"
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema(seed_defaults=False)
    return mgr


@pytest.fixture
def uploader(uploader_db: DatabaseManager) -> StowRsUploader:
    """Fixture creating a StowRsUploader instance bound to isolated audit logger."""
    audit = AuditLogger(db=uploader_db)
    return StowRsUploader(
        endpoint="https://cloud.orthanc-vna.hospital.org/dicom-web/studies",
        token="Bearer TEST_TOKEN_SECRET_9999",
        timeout=5.0,
        max_retries=3,
        audit=audit,
    )


def test_multipart_payload_structure(uploader: StowRsUploader) -> None:
    """Verifies that DICOM binary data is properly packaged into PS 3.18 multipart body."""
    raw_dicom_bytes = b"\x00\x01\x02\x03\x04\x05SAMPLE_DICOM_BYTES"
    boundary = "TEST_BOUNDARY_ABC123"

    body, content_type = uploader._build_multipart_payload(raw_dicom_bytes, boundary=boundary)

    assert f'boundary="{boundary}"' in content_type
    assert 'type="application/dicom"' in content_type

    # Verify standard boundary envelope
    assert body.startswith(f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode("utf-8"))
    assert body.endswith(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    assert raw_dicom_bytes in body


def test_backoff_delay_calculation(uploader: StowRsUploader) -> None:
    """Verifies exponential backoff with jitter grows appropriately and respects cap."""
    d0 = uploader.calculate_backoff_delay(0, base=2.0)
    d1 = uploader.calculate_backoff_delay(1, base=2.0)
    d2 = uploader.calculate_backoff_delay(2, base=2.0)

    # 2 * 2^0 = 2 (+ jitter 0.1..1.0) -> [2.1, 3.0]
    assert 2.1 <= d0 <= 3.0
    # 2 * 2^1 = 4 (+ jitter 0.1..1.0) -> [4.1, 5.0]
    assert 4.1 <= d1 <= 5.0
    # 2 * 2^2 = 8 (+ jitter 0.1..1.0) -> [8.1, 9.0]
    assert 8.1 <= d2 <= 9.0

    # Test max_delay ceiling
    d_capped = uploader.calculate_backoff_delay(20, base=2.0, max_delay=60.0)
    assert 60.1 <= d_capped <= 61.0


def test_upload_instance_success(uploader: StowRsUploader, uploader_db: DatabaseManager, tmp_path: Path) -> None:
    """Verifies successful HTTP 200 STOW-RS response records FORWARD_SUCCESS audit event."""
    sample_file = tmp_path / "valid_image.dcm"
    sample_file.write_bytes(b"DCM_VALID_MOCK_PAYLOAD")

    mock_resp = httpx.Response(status_code=200, request=httpx.Request("POST", uploader.endpoint))

    with patch.object(httpx.Client, "post", return_value=mock_resp) as mock_post:
        success, error = uploader.upload_instance(
            file_path=sample_file,
            study_instance_uid="1.2.840.10008.5.1.4.1.1.7.STUDY.1",
            sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.SOP.1",
        )

        assert success is True
        assert error is None
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer TEST_TOKEN_SECRET_9999"

    # Verify audit record
    with uploader_db.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs WHERE event_type = 'FORWARD_SUCCESS';")
        entry = cursor.fetchone()
        cursor.close()

    assert entry is not None
    assert entry["actor"] == "PacsServiceWorker"
    assert "1.2.840.10008.5.1.4.1.1.7.SOP.1" in entry["details"]


def test_upload_instance_http_rejection(uploader: StowRsUploader, uploader_db: DatabaseManager, tmp_path: Path) -> None:
    """Verifies HTTP 500 error records FORWARD_FAILURE audit event."""
    sample_file = tmp_path / "valid_image.dcm"
    sample_file.write_bytes(b"DCM_VALID_MOCK_PAYLOAD")

    mock_resp = httpx.Response(
        status_code=500,
        text="Internal Server Error: VNA storage pool offline",
        request=httpx.Request("POST", uploader.endpoint),
    )

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        success, error = uploader.upload_instance(
            file_path=sample_file,
            study_instance_uid="1.2.840.10008.5.1.4.1.1.7.STUDY.2",
            sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.SOP.2",
            current_retry_count=1,
        )

        assert success is False
        assert error is not None
        assert "500" in error

    # Verify audit record
    with uploader_db.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs WHERE event_type = 'FORWARD_FAILURE';")
        entry = cursor.fetchone()
        cursor.close()

    assert entry is not None
    assert "500" in entry["details"]


def test_upload_instance_network_timeout(uploader: StowRsUploader, tmp_path: Path) -> None:
    """Verifies network transport timeouts are caught and reported as failures."""
    sample_file = tmp_path / "valid_image.dcm"
    sample_file.write_bytes(b"DCM_VALID_MOCK_PAYLOAD")

    with patch.object(httpx.Client, "post", side_effect=httpx.ConnectTimeout("Connection timed out")):
        success, error = uploader.upload_instance(
            file_path=sample_file,
            study_instance_uid="1.2.840.10008.5.1.4.1.1.7.STUDY.3",
            sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.SOP.3",
        )

        assert success is False
        assert error is not None
        assert "timed out" in error.lower()


def test_upload_nonexistent_file(uploader: StowRsUploader, tmp_path: Path) -> None:
    """Verifies attempting to upload a missing file returns False without raising exception."""
    missing_file = tmp_path / "does_not_exist.dcm"
    success, error = uploader.upload_instance(
        file_path=missing_file,
        study_instance_uid="1.2.840.10008.5.1.4.1.1.7.STUDY.4",
        sop_instance_uid="1.2.840.10008.5.1.4.1.1.7.SOP.4",
    )

    assert success is False
    assert error is not None
    assert "not found" in error.lower()
