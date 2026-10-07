"""ProRadCS Enterprise DICOM Gateway & Edge Node - Cryptographic Audit Logging Module.

Implements HIPAA § 164.312(b) compliant tamper-evident audit logging with blockchain-style
hash chaining, strict Zero-PHI enforcement (MANDATE-PHI-001), and integrity verification.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from backend.core.database import DatabaseManager, db_manager


# Standard system actors
ACTOR_SERVICE_WORKER = "PacsServiceWorker"
ACTOR_ADMIN_USER = "AdminUser"
ACTOR_SYSTEM = "SystemDaemon"

# Standard audit event types
EVENT_INGEST = "C_STORE_INGEST"
EVENT_ANONYMIZATION = "ANONYMIZATION"
EVENT_TRANSCODE = "TRANSCODE"
EVENT_FORWARD_SUCCESS = "FORWARD_SUCCESS"
EVENT_FORWARD_FAILURE = "FORWARD_FAILURE"
EVENT_SECURITY_VIOLATION = "SECURITY_VIOLATION"
EVENT_STORAGE_WATERMARK = "STORAGE_WATERMARK_ALERT"
EVENT_SERVICE_LIFECYCLE = "SERVICE_LIFECYCLE"

# Regular expressions to catch accidental PHI leaks in free text
PHI_NAME_PATTERN = re.compile(r"\b(patientname|patient_name|patientid|patient_id)\b", re.IGNORECASE)


class PHISecurityException(Exception):
    """Raised if an attempt is made to log Protected Health Information directly."""
    pass


def hash_patient_id(raw_patient_id: str, salt: str) -> str:
    """Computes a one-way deterministic SHA-256 hash of a Patient ID using the site salt.

    Never stores or logs the raw Patient ID.
    """
    salted_input = f"{salt}:{raw_patient_id}".encode("utf-8")
    return hashlib.sha256(salted_input).hexdigest()


class AuditLogger:
    """Cryptographic audit logger maintaining an immutable hash-chained audit trail."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db if db is not None else db_manager
        self._sys_logger = logging.getLogger("proradcs.audit")
        self._sys_logger.setLevel(logging.INFO)

    def _sanitize_details(self, details: Dict[str, Any]) -> str:
        """Serializes details to JSON while guaranteeing no direct PHI keys exist."""
        forbidden_keys = {"patient_name", "patientname", "patient_dob", "birth_date", "ssn"}
        for k in details.keys():
            if k.lower() in forbidden_keys:
                raise PHISecurityException(
                    f"MANDATE-PHI-001 Violation: Attempted to record forbidden PHI field '{k}' in audit log."
                )
        return json.dumps(details, sort_keys=True, default=str)

    def record_event(
        self,
        event_type: str,
        actor: str,
        details: Dict[str, Any],
        patient_hash: Optional[str] = None,
    ) -> int:
        """Inserts a cryptographically chained audit record into SQLite."""
        details_json = self._sanitize_details(details)
        utc_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        with self.db.get_connection(read_only=False) as conn:
            cursor = conn.cursor()
            
            # Fetch previous current_hash within transaction
            cursor.execute("SELECT current_hash FROM audit_logs ORDER BY log_id DESC LIMIT 1;")
            row = cursor.fetchone()
            previous_hash = str(row["current_hash"]) if (row is not None and row["current_hash"]) else ("0" * 64)

            # Compute SHA-256: previous_hash + timestamp + event_type + actor + patient_hash + details
            ph_str = patient_hash or ""
            payload = f"{previous_hash}|{utc_timestamp}|{event_type}|{actor}|{ph_str}|{details_json}".encode("utf-8")
            current_hash = hashlib.sha256(payload).hexdigest()

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    timestamp, event_type, actor, patient_hash, details, previous_hash, current_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    utc_timestamp,
                    event_type,
                    actor,
                    patient_hash,
                    details_json,
                    previous_hash,
                    current_hash,
                ),
            )
            inserted_id = int(cursor.lastrowid or 0)
            cursor.close()

        # Emit structured log to standard logging (Zero PHI)
        self._sys_logger.info(
            f"AUDIT_EVENT | id={inserted_id} | type={event_type} | actor={actor} | "
            f"patient_hash={patient_hash[:8] if patient_hash else 'NONE'} | hash={current_hash[:12]}"
        )
        return inserted_id

    def verify_chain_integrity(self) -> Tuple[bool, Optional[str]]:
        """Validates the cryptographic chain of all records in audit_logs.

        Returns (True, None) if unbroken, or (False, failure_reason) if tampering is detected.
        """
        with self.db.get_connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT log_id, timestamp, event_type, actor, patient_hash, details, previous_hash, current_hash
                FROM audit_logs
                ORDER BY log_id ASC;
                """
            )
            rows = cursor.fetchall()
            cursor.close()

        if not rows:
            return True, None

        expected_prev_hash = "0" * 64
        for row in rows:
            log_id = row["log_id"]
            row_prev = row["previous_hash"]
            row_curr = row["current_hash"]
            ph_str = row["patient_hash"] or ""
            details_json = row["details"]

            if row_prev != expected_prev_hash:
                return False, f"Broken chain link at log_id={log_id}: previous_hash mismatch."

            payload = f"{row_prev}|{row['timestamp']}|{row['event_type']}|{row['actor']}|{ph_str}|{details_json}".encode("utf-8")
            recomputed = hashlib.sha256(payload).hexdigest()

            if recomputed != row_curr:
                return False, f"Tampered record detected at log_id={log_id}: current_hash mismatch."

            expected_prev_hash = row_curr

        return True, None


# Global audit logger instance
audit_logger = AuditLogger()
