"""ProRadCS Enterprise DICOM Gateway & Edge Node - System Telemetry Module.

Monitors edge appliance hardware metrics, partition free space percentage, storage watermarks
(NFR-002), queue sizes, and memory footprints for local diagnostics and health checks.
"""

from pathlib import Path
import shutil
from typing import Any, Dict, Optional
import psutil
from pydantic import BaseModel, Field
from backend.core.config import settings
from backend.core.database import DatabaseManager, db_manager


class StorageTelemetry(BaseModel):
    """Partition storage capacity and watermark telemetry."""
    total_bytes: int = Field(..., description="Total volume storage capacity in bytes.")
    free_bytes: int = Field(..., description="Available free storage in bytes.")
    used_bytes: int = Field(..., description="Used storage in bytes.")
    free_percent: float = Field(..., description="Available free storage percentage.")
    is_watermark_safe: bool = Field(..., description="True if free storage exceeds the minimum threshold.")
    min_required_percent: float = Field(..., description="Configured watermark safety floor.")


class QueueTelemetry(BaseModel):
    """Current DICOM instance counts across lifecycle states."""
    staged_count: int = Field(0, description="Instances pending de-identification and transcoding.")
    processing_count: int = Field(0, description="Instances actively undergoing processing.")
    processed_count: int = Field(0, description="Instances transcoded and awaiting WAN transmission.")
    forwarded_count: int = Field(0, description="Instances successfully transmitted to Cloud VNA.")
    failed_count: int = Field(0, description="Instances halted due to network or processing errors.")
    quarantined_count: int = Field(0, description="Corrupted or duplicate-collision instances isolated.")


class SystemTelemetry(BaseModel):
    """Host machine hardware resource consumption metrics."""
    cpu_percent: float = Field(..., description="Total system CPU utilization percentage.")
    memory_total_mb: float = Field(..., description="Total system RAM in Megabytes.")
    memory_used_mb: float = Field(..., description="Consumed system RAM in Megabytes.")
    memory_percent: float = Field(..., description="Consumed system RAM percentage.")
    process_memory_mb: float = Field(..., description="RAM consumed by current Python process.")
    storage: StorageTelemetry
    queues: QueueTelemetry
    database_size_bytes: int = Field(..., description="Current disk size of the primary SQLite database.")


class TelemetryCollector:
    """Collects real-time hardware telemetry and enforces storage watermarks."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db if db is not None else db_manager

    def get_storage_telemetry(self, target_path: Optional[Path] = None) -> StorageTelemetry:
        """Inspects disk partition containing the archive root directory."""
        path_to_check = target_path if target_path is not None else settings.archive_dir
        
        # Resolve to nearest existing parent directory if archive path does not exist yet
        resolved_path = path_to_check
        while not resolved_path.exists() and resolved_path.parent != resolved_path:
            resolved_path = resolved_path.parent

        usage = shutil.disk_usage(resolved_path)
        free_percent = (usage.free / usage.total) * 100.0 if usage.total > 0 else 0.0
        is_safe = free_percent >= settings.storage_min_free_percent

        return StorageTelemetry(
            total_bytes=usage.total,
            free_bytes=usage.free,
            used_bytes=usage.used,
            free_percent=round(free_percent, 2),
            is_watermark_safe=is_safe,
            min_required_percent=settings.storage_min_free_percent,
        )

    def is_storage_safe(self) -> bool:
        """Fast check used by DICOM C-STORE SCP before accepting inbound payload (NFR-002)."""
        return self.get_storage_telemetry().is_watermark_safe

    def get_queue_telemetry(self) -> QueueTelemetry:
        """Queries the database for current instance distribution across pipeline states."""
        counts: Dict[str, int] = {
            "STAGED": 0,
            "PROCESSING": 0,
            "PROCESSED": 0,
            "FORWARDED": 0,
            "FAILED": 0,
            "QUARANTINED": 0,
        }

        try:
            with self.db.get_connection(read_only=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT pipeline_status, COUNT(*) as cnt
                    FROM instances
                    GROUP BY pipeline_status;
                    """
                )
                for row in cursor.fetchall():
                    status = str(row["pipeline_status"])
                    if status in counts:
                        counts[status] = int(row["cnt"])
                cursor.close()
        except Exception:
            # Table may not exist yet during pre-initialization checks
            pass

        return QueueTelemetry(
            staged_count=counts["STAGED"],
            processing_count=counts["PROCESSING"],
            processed_count=counts["PROCESSED"],
            forwarded_count=counts["FORWARDED"],
            failed_count=counts["FAILED"],
            quarantined_count=counts["QUARANTINED"],
        )

    def get_full_telemetry(self) -> SystemTelemetry:
        """Compiles an exhaustive telemetry report for the local web dashboard."""
        virtual_mem = psutil.virtual_memory()
        current_process = psutil.Process()
        proc_mem_mb = current_process.memory_info().rss / (1024 * 1024)

        db_path = settings.database_path
        db_size = db_path.stat().st_size if db_path.exists() else 0

        return SystemTelemetry(
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_total_mb=round(virtual_mem.total / (1024 * 1024), 2),
            memory_used_mb=round(virtual_mem.used / (1024 * 1024), 2),
            memory_percent=virtual_mem.percent,
            process_memory_mb=round(proc_mem_mb, 2),
            storage=self.get_storage_telemetry(),
            queues=self.get_queue_telemetry(),
            database_size_bytes=db_size,
        )


# Global telemetry collector singleton
telemetry_collector = TelemetryCollector()
