"""Unit tests for lossless DICOM image transcoding engine and audit logging."""

from pathlib import Path
import numpy as np
import pytest
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless, SecondaryCaptureImageStorage
from backend.core.database import DatabaseManager
from backend.core.audit import AuditLogger
from backend.workers.transcoder import DicomTranscoder


@pytest.fixture
def transcoder_db(tmp_path: Path) -> DatabaseManager:
    """Fixture creating an isolated test database with schema initialized."""
    db_file = tmp_path / "transcoder_test.db"
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema(seed_defaults=False)
    return mgr


@pytest.fixture
def transcoder(transcoder_db: DatabaseManager) -> DicomTranscoder:
    """Fixture creating a DicomTranscoder instance bound to isolated audit logger."""
    audit = AuditLogger(db=transcoder_db)
    return DicomTranscoder(max_workers=2, audit=audit)


def create_synthetic_image_file(path: Path, width: int = 64, height: int = 64) -> np.ndarray:
    """Creates an uncompressed DICOM image with known pixel array."""
    # Deterministic ramp pattern
    pixels = np.arange(width * height, dtype=np.uint16).reshape((height, width))

    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7.111111"

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7.111111"
    ds.StudyInstanceUID = "1.2.840.10008.5.1.4.1.1.7.222222"
    ds.SeriesInstanceUID = "1.2.840.10008.5.1.4.1.1.7.333333"
    ds.Modality = "OT"

    ds.Rows = height
    ds.Columns = width
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"

    ds.PixelData = pixels.tobytes()
    ds.save_as(str(path), write_like_original=False)
    return pixels


def test_lossless_jpeg2000_transcode(transcoder: DicomTranscoder, tmp_path: Path) -> None:
    """Verifies uncompressed DICOM image is losslessly transcoded to JPEG 2000 Part 1."""
    raw_path = tmp_path / "raw_image.dcm"
    out_path = tmp_path / "transcoded_image.dcm"

    original_pixels = create_synthetic_image_file(raw_path, width=32, height=32)

    result_path, size_bytes, sha256_hash = transcoder.transcode_file(raw_path, out_path)

    assert result_path == out_path
    assert out_path.exists()
    assert size_bytes > 0
    assert len(sha256_hash) == 64

    # Read back and inspect transfer syntax
    transcoded_ds = pydicom.dcmread(str(out_path))
    assert transcoded_ds.file_meta.TransferSyntaxUID == JPEG2000Lossless

    # Verify bit-for-bit diagnostic pixel equality
    decoded_pixels = transcoded_ds.pixel_array
    np.testing.assert_array_equal(original_pixels, decoded_pixels)


def test_transcode_non_image_dicom(transcoder: DicomTranscoder, tmp_path: Path) -> None:
    """Verifies datasets without PixelData pass through gracefully without error."""
    raw_path = tmp_path / "metadata_only.dcm"
    out_path = tmp_path / "transcoded_metadata.dcm"

    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7.444444"

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7.444444"
    ds.StudyInstanceUID = "1.2.840.10008.5.1.4.1.1.7.555555"
    ds.SeriesInstanceUID = "1.2.840.10008.5.1.4.1.1.7.666666"
    ds.Modality = "DOC"

    ds.save_as(str(raw_path), write_like_original=False)

    result_path, size_bytes, _ = transcoder.transcode_file(raw_path, out_path)
    assert result_path == out_path
    assert out_path.exists()
    assert size_bytes > 0


def test_transcode_audit_event_logged(
    transcoder: DicomTranscoder,
    transcoder_db: DatabaseManager,
    tmp_path: Path,
) -> None:
    """Verifies that each successful transcode records a tamper-evident audit record."""
    raw_path = tmp_path / "audit_test_image.dcm"
    out_path = tmp_path / "audit_test_out.dcm"
    create_synthetic_image_file(raw_path, width=64, height=64)

    transcoder.transcode_file(raw_path, out_path)

    with transcoder_db.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs WHERE event_type = 'TRANSCODE' ORDER BY log_id DESC LIMIT 1;")
        entry = cursor.fetchone()
        cursor.close()

    assert entry is not None
    assert entry["actor"] == "PacsServiceWorker"
    assert "audit_test_image.dcm" in entry["details"]
    assert "JPEG 2000" in entry["details"]
