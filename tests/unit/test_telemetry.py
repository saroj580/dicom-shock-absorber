"""Unit tests for system telemetry metrics, queue counters, and storage watermarks."""

from pathlib import Path
import pytest
from backend.core.database import DatabaseManager
from backend.core.telemetry import TelemetryCollector, StorageTelemetry, QueueTelemetry, SystemTelemetry


@pytest.fixture
def telemetry_db(tmp_path: Path) -> DatabaseManager:
    """Fixture creating an isolated test database with schema initialized."""
    db_file = tmp_path / "telemetry_test.db"
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema(seed_defaults=True)
    return mgr


@pytest.fixture
def collector(telemetry_db: DatabaseManager) -> TelemetryCollector:
    """Fixture creating a TelemetryCollector instance."""
    return TelemetryCollector(db=telemetry_db)


def test_storage_telemetry_calculation(collector: TelemetryCollector, tmp_path: Path) -> None:
    """Verifies disk usage calculation and watermark safety check."""
    storage = collector.get_storage_telemetry(target_path=tmp_path)
    assert isinstance(storage, StorageTelemetry)
    assert storage.total_bytes > 0
    assert storage.free_bytes > 0
    assert storage.used_bytes >= 0
    assert 0.0 <= storage.free_percent <= 100.0
    assert isinstance(storage.is_watermark_safe, bool)


def test_queue_telemetry_counting(collector: TelemetryCollector, telemetry_db: DatabaseManager) -> None:
    """Verifies queue instance state counts are correctly aggregated."""
    # Initially empty
    q0 = collector.get_queue_telemetry()
    assert isinstance(q0, QueueTelemetry)
    assert q0.staged_count == 0
    assert q0.processed_count == 0
    assert q0.forwarded_count == 0

    # Insert test instances
    telemetry_db.register_instance(
        sop_instance_uid="1.2.3.1",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
        study_instance_uid="1.2.3",
        series_instance_uid="1.2.3.1",
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:/test1.dcm",
        file_size_bytes=100,
        sha256_hash="h1",
    )
    telemetry_db.register_instance(
        sop_instance_uid="1.2.3.2",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
        study_instance_uid="1.2.3",
        series_instance_uid="1.2.3.1",
        calling_ae_title="CT_SCANNER_01",
        original_file_path="D:/test2.dcm",
        file_size_bytes=200,
        sha256_hash="h2",
    )

    q1 = collector.get_queue_telemetry()
    assert q1.staged_count == 2
    assert q1.processing_count == 0

    # Transition one to PROCESSED
    telemetry_db.update_instance_status(sop_instance_uid="1.2.3.1", status="PROCESSED")
    q2 = collector.get_queue_telemetry()
    assert q2.staged_count == 1
    assert q2.processed_count == 1


def test_system_telemetry_payload(collector: TelemetryCollector) -> None:
    """Verifies complete system telemetry aggregates CPU, RAM, disk, and queue data."""
    sys_telem = collector.get_full_telemetry()
    assert isinstance(sys_telem, SystemTelemetry)
    assert sys_telem.cpu_percent >= 0.0
    assert sys_telem.memory_total_mb > 0.0
    assert sys_telem.memory_used_mb > 0.0
    assert sys_telem.process_memory_mb > 0.0
    assert isinstance(sys_telem.storage, StorageTelemetry)
    assert isinstance(sys_telem.queues, QueueTelemetry)
