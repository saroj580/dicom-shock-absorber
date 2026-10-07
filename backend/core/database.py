"""ProRadCS Enterprise DICOM Gateway & Edge Node - Database Management Module.

Provides SQLite 3.39+ connection pooling, WAL mode initialization, relational schema
enforcement, and atomic transaction handling for instances, modalities, and audit logs.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional
from backend.core.config import settings


SCHEMA_DDL = """
-- Table: Modality Registry (Authorized DICOM SCU devices)
CREATE TABLE IF NOT EXISTS modality_registry (
    ae_title TEXT PRIMARY KEY,
    ip_address TEXT NOT NULL,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: DICOM Instances (Life cycle state machine tracking)
CREATE TABLE IF NOT EXISTS instances (
    sop_instance_uid TEXT PRIMARY KEY,
    sop_class_uid TEXT NOT NULL,
    study_instance_uid TEXT NOT NULL,
    series_instance_uid TEXT NOT NULL,
    calling_ae_title TEXT NOT NULL,
    original_file_path TEXT NOT NULL,
    processed_file_path TEXT,
    file_size_bytes INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    pipeline_status TEXT NOT NULL CHECK(pipeline_status IN (
        'STAGED', 'PROCESSING', 'PROCESSED', 'UPLOADING', 'FORWARDED', 'FAILED', 'QUARANTINED'
    )),
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    forwarded_at TIMESTAMP,
    FOREIGN KEY(calling_ae_title) REFERENCES modality_registry(ae_title)
);

CREATE INDEX IF NOT EXISTS idx_instances_status ON instances(pipeline_status);
CREATE INDEX IF NOT EXISTS idx_instances_study ON instances(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_instances_series ON instances(series_instance_uid);

-- Table: Audit Trail (HIPAA § 164.312(b) Cryptographic Chained Audit Logs)
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    patient_hash TEXT,
    details TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    current_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
"""

# Default authorized local modalities seeded upon initial database setup
DEFAULT_MODALITIES = [
    ("CT_SCANNER_01", "127.0.0.1", "Primary Local CT Modality (Loopback Test)", 1),
    ("MR_SCANNER_01", "127.0.0.1", "Primary Local MRI Modality (Loopback Test)", 1),
    ("ANY_TEST_SCU", "*", "Permissive Test SCU for Local Automated Integration Testing", 1),
]


class DatabaseManager:
    """Manages SQLite connections, schema initialization, and transactional queries."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path if db_path is not None else settings.database_path

    def _configure_connection(self, conn: sqlite3.Connection, read_only: bool = False) -> None:
        """Applies high-concurrency PRAGMAs required for edge durability and safety."""
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Enforce WAL mode for non-blocking concurrent reads and writes
        if not read_only:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA auto_vacuum = INCREMENTAL;")

        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()

    @contextmanager
    def get_connection(self, read_only: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """Provides a managed SQLite connection context with automatic commit/rollback."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Connect to SQLite
        uri = f"file:{self.db_path.as_posix()}"
        if read_only:
            uri += "?mode=ro"

        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        try:
            self._configure_connection(conn, read_only=read_only)
            yield conn
            if not read_only:
                conn.commit()
        except Exception:
            if not read_only:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self, seed_defaults: bool = True) -> None:
        """Executes DDL statements to create tables and indexes, and seeds test modalities."""
        with self.get_connection(read_only=False) as conn:
            cursor = conn.cursor()
            cursor.executescript(SCHEMA_DDL)

            if seed_defaults:
                cursor.executemany(
                    """
                    INSERT INTO modality_registry (ae_title, ip_address, description, is_active)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(ae_title) DO NOTHING;
                    """,
                    DEFAULT_MODALITIES,
                )
            cursor.close()

    def get_latest_audit_hash(self) -> str:
        """Retrieves current_hash of the most recent audit entry, or genesis hash if empty."""
        genesis_hash = "0" * 64
        with self.get_connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT current_hash FROM audit_logs ORDER BY log_id DESC LIMIT 1;")
            row = cursor.fetchone()
            if row is not None and row["current_hash"]:
                return str(row["current_hash"])
            return genesis_hash

    def is_ae_title_allowed(self, ae_title: str, calling_ip: Optional[str] = None) -> bool:
        """Checks if a calling AE Title is registered and active in the modality registry."""
        with self.get_connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT ip_address, is_active FROM modality_registry WHERE ae_title = ?;",
                (ae_title,),
            )
            row = cursor.fetchone()
            if row is None or row["is_active"] != 1:
                return False

            registered_ip = str(row["ip_address"])
            if registered_ip == "*" or calling_ip is None or calling_ip == "127.0.0.1":
                return True
            return registered_ip == calling_ip

    def register_instance(
        self,
        sop_instance_uid: str,
        sop_class_uid: str,
        study_instance_uid: str,
        series_instance_uid: str,
        calling_ae_title: str,
        original_file_path: str,
        file_size_bytes: int,
        sha256_hash: str,
    ) -> bool:
        """Registers a newly ingested DICOM instance in the STAGED state."""
        with self.get_connection(read_only=False) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO instances (
                    sop_instance_uid, sop_class_uid, study_instance_uid, series_instance_uid,
                    calling_ae_title, original_file_path, file_size_bytes, sha256_hash,
                    pipeline_status, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'STAGED', 0);
                """,
                (
                    sop_instance_uid,
                    sop_class_uid,
                    study_instance_uid,
                    series_instance_uid,
                    calling_ae_title,
                    original_file_path,
                    file_size_bytes,
                    sha256_hash,
                ),
            )
            return cursor.rowcount > 0

    def claim_next_staged_instance(self) -> Optional[Dict[str, Any]]:
        """Atomically locks and claims the next STAGED instance by transitioning it to PROCESSING.

        Prevents race conditions between concurrent worker threads or processes.
        """
        with self.get_connection(read_only=False) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE instances
                SET pipeline_status = 'PROCESSING'
                WHERE sop_instance_uid = (
                    SELECT sop_instance_uid
                    FROM instances
                    WHERE pipeline_status = 'STAGED'
                    ORDER BY received_at ASC
                    LIMIT 1
                )
                RETURNING *;
                """
            )
            row = cursor.fetchone()
            if row is not None:
                return dict(row)
            return None

    def update_instance_status(
        self,
        sop_instance_uid: str,
        status: str,
        processed_file_path: Optional[str] = None,
        error_message: Optional[str] = None,
        increment_retry: bool = False,
    ) -> bool:
        """Updates the lifecycle state and output paths of an instance."""
        with self.get_connection(read_only=False) as conn:
            cursor = conn.cursor()
            retry_expr = "retry_count + 1" if increment_retry else "retry_count"
            cursor.execute(
                f"""
                UPDATE instances
                SET pipeline_status = ?,
                    processed_file_path = COALESCE(?, processed_file_path),
                    error_message = ?,
                    retry_count = {retry_expr},
                    processed_at = CASE WHEN ? = 'PROCESSED' THEN CURRENT_TIMESTAMP ELSE processed_at END,
                    forwarded_at = CASE WHEN ? = 'FORWARDED' THEN CURRENT_TIMESTAMP ELSE forwarded_at END
                WHERE sop_instance_uid = ?;
                """,
                (
                    status,
                    processed_file_path,
                    error_message,
                    status,
                    status,
                    sop_instance_uid,
                ),
            )
            return cursor.rowcount > 0

    def get_instance_by_uid(self, sop_instance_uid: str) -> Optional[Dict[str, Any]]:
        """Queries instance metadata by SOP Instance UID."""
        with self.get_connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM instances WHERE sop_instance_uid = ?;", (sop_instance_uid,))
            row = cursor.fetchone()
            if row is not None:
                return dict(row)
            return None


# Global singleton instance pointing to configured database path
db_manager = DatabaseManager()
