"""ProRadCS Enterprise DICOM Gateway & Edge Node - REST API Routes.

Exposes read-heavy endpoints for system telemetry, instance queue inspection,
modality registry management, cryptographic audit verification, and WAL checkpointing.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from backend.core.audit import ACTOR_ADMIN_USER, audit_logger
from backend.core.config import settings
from backend.core.database import db_manager
from backend.core.telemetry import SystemTelemetry, telemetry_collector
from backend.api.models import (
    ActionResponse,
    AuditRecordItem,
    AuditVerificationResult,
    HealthStatusResponse,
    InstanceItem,
    ModalityCreate,
    ModalityItem,
    QueueListResponse,
)


api_router = APIRouter(prefix="/api")


@api_router.get("/health", response_model=HealthStatusResponse, tags=["Health"])
def get_health_status() -> HealthStatusResponse:
    """Returns overall node health, partition safety floor, and DICOM connectivity."""
    storage_info = telemetry_collector.get_storage_telemetry()
    is_safe = storage_info.is_watermark_safe
    status_str = "HEALTHY" if is_safe else "DEGRADED"

    db_ok = True
    try:
        with db_manager.get_connection(read_only=True) as conn:
            conn.cursor().execute("SELECT 1;")
    except Exception:
        db_ok = False
        status_str = "CRITICAL"

    return HealthStatusResponse(
        status=status_str,
        version="1.0.0-PROD",
        is_storage_safe=is_safe,
        storage_free_percent=storage_info.free_percent,
        database_connected=db_ok,
        ae_title=settings.ae_title,
        dicom_port=settings.dicom_port,
    )


@api_router.get("/telemetry", response_model=SystemTelemetry, tags=["Telemetry"])
def get_telemetry() -> SystemTelemetry:
    """Returns detailed real-time telemetry: storage partition, queues, CPU, and RAM."""
    return telemetry_collector.get_full_telemetry()


@api_router.get("/queue", response_model=QueueListResponse, tags=["Queue"])
def get_queue(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: STAGED, PROCESSING, PROCESSED, FORWARDED, FAILED, QUARANTINED"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> QueueListResponse:
    """Queries instance life cycle state with optional status filtering and pagination."""
    instances: List[InstanceItem] = []
    total_count = 0

    with db_manager.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        if status_filter:
            cursor.execute("SELECT COUNT(*) as cnt FROM instances WHERE pipeline_status = ?;", (status_filter,))
            total_count = int(cursor.fetchone()["cnt"])

            cursor.execute(
                """
                SELECT * FROM instances
                WHERE pipeline_status = ?
                ORDER BY received_at DESC
                LIMIT ? OFFSET ?;
                """,
                (status_filter, limit, offset),
            )
        else:
            cursor.execute("SELECT COUNT(*) as cnt FROM instances;")
            total_count = int(cursor.fetchone()["cnt"])

            cursor.execute(
                """
                SELECT * FROM instances
                ORDER BY received_at DESC
                LIMIT ? OFFSET ?;
                """,
                (limit, offset),
            )

        for row in cursor.fetchall():
            instances.append(InstanceItem(
                sop_instance_uid=str(row["sop_instance_uid"]),
                sop_class_uid=str(row["sop_class_uid"]),
                study_instance_uid=str(row["study_instance_uid"]),
                series_instance_uid=str(row["series_instance_uid"]),
                calling_ae_title=str(row["calling_ae_title"]),
                original_file_path=str(row["original_file_path"]),
                processed_file_path=str(row["processed_file_path"]) if row["processed_file_path"] else None,
                file_size_bytes=int(row["file_size_bytes"]),
                sha256_hash=str(row["sha256_hash"]),
                pipeline_status=str(row["pipeline_status"]),
                retry_count=int(row["retry_count"]),
                error_message=str(row["error_message"]) if row["error_message"] else None,
                received_at=str(row["received_at"]),
                processed_at=str(row["processed_at"]) if row["processed_at"] else None,
                forwarded_at=str(row["forwarded_at"]) if row["forwarded_at"] else None,
            ))

    return QueueListResponse(total_count=total_count, instances=instances)


@api_router.get("/modalities", response_model=List[ModalityItem], tags=["Modalities"])
def list_modalities() -> List[ModalityItem]:
    """Retrieves all registered clinical imaging modalities."""
    modalities: List[ModalityItem] = []
    with db_manager.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM modality_registry ORDER BY ae_title ASC;")
        for row in cursor.fetchall():
            modalities.append(ModalityItem(
                ae_title=str(row["ae_title"]),
                ip_address=str(row["ip_address"]),
                description=str(row["description"]) if row["description"] else None,
                is_active=int(row["is_active"]),
                created_at=str(row["created_at"]),
            ))
    return modalities


@api_router.post("/modalities", response_model=ModalityItem, status_code=status.HTTP_201_CREATED, tags=["Modalities"])
def register_modality(payload: ModalityCreate) -> ModalityItem:
    """Registers a new authorized modality in the whitelist."""
    clean_ae = payload.ae_title.strip().upper()
    with db_manager.get_connection(read_only=False) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO modality_registry (ae_title, ip_address, description, is_active)
                VALUES (?, ?, ?, ?);
                """,
                (clean_ae, payload.ip_address.strip(), payload.description, 1 if payload.is_active else 0),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Modality with AE Title '{clean_ae}' already exists.",
            )

        cursor.execute("SELECT * FROM modality_registry WHERE ae_title = ?;", (clean_ae,))
        row = cursor.fetchone()

    return ModalityItem(
        ae_title=str(row["ae_title"]),
        ip_address=str(row["ip_address"]),
        description=str(row["description"]) if row["description"] else None,
        is_active=int(row["is_active"]),
        created_at=str(row["created_at"]),
    )


@api_router.post("/modalities/{ae_title}/toggle", response_model=ActionResponse, tags=["Modalities"])
def toggle_modality(ae_title: str) -> ActionResponse:
    """Toggles active/inactive status of a modality."""
    clean_ae = ae_title.strip().upper()
    with db_manager.get_connection(read_only=False) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM modality_registry WHERE ae_title = ?;", (clean_ae,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Modality '{clean_ae}' not found.")

        new_state = 0 if int(row["is_active"]) == 1 else 1
        cursor.execute("UPDATE modality_registry SET is_active = ? WHERE ae_title = ?;", (new_state, clean_ae))

    state_label = "ENABLED" if new_state == 1 else "DISABLED"
    return ActionResponse(success=True, message=f"Modality '{clean_ae}' has been {state_label}.")


@api_router.get("/audit", response_model=List[AuditRecordItem], tags=["Audit"])
def get_audit_trail(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[AuditRecordItem]:
    """Retrieves paginated cryptographic audit trail records (Zero-PHI strictly enforced)."""
    records: List[AuditRecordItem] = []
    with db_manager.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM audit_logs
            ORDER BY log_id DESC
            LIMIT ? OFFSET ?;
            """,
            (limit, offset),
        )
        for row in cursor.fetchall():
            try:
                parsed_details = json.loads(str(row["details"]))
            except Exception:
                parsed_details = {"raw": str(row["details"])}

            records.append(AuditRecordItem(
                log_id=int(row["log_id"]),
                timestamp=str(row["timestamp"]),
                event_type=str(row["event_type"]),
                actor=str(row["actor"]),
                patient_hash=str(row["patient_hash"]) if row["patient_hash"] else None,
                details=parsed_details,
                previous_hash=str(row["previous_hash"]),
                current_hash=str(row["current_hash"]),
            ))
    return records


@api_router.get("/audit/verify", response_model=AuditVerificationResult, tags=["Audit"])
def verify_audit_chain() -> AuditVerificationResult:
    """Cryptographically traverses and verifies the SHA-256 hash chain of the audit trail."""
    is_valid, failure_reason = audit_logger.verify_chain_integrity()
    with db_manager.get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM audit_logs;")
        count = int(cursor.fetchone()["cnt"])

    return AuditVerificationResult(
        is_chain_intact=is_valid,
        total_records_verified=count,
        error_message=failure_reason,
    )


@api_router.post("/actions/checkpoint", response_model=ActionResponse, tags=["Actions"])
def execute_wal_checkpoint() -> ActionResponse:
    """Manually forces SQLite WAL checkpoint TRUNCATE to flush WAL journal into main DB file."""
    try:
        with db_manager.get_connection(read_only=False) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            row = cursor.fetchone()
            busy, log, checkpointed = row[0], row[1], row[2]

        audit_logger.record_event(
            event_type="ADMIN_WAL_CHECKPOINT",
            actor=ACTOR_ADMIN_USER,
            details={"busy": busy, "log": log, "checkpointed": checkpointed},
        )
        return ActionResponse(
            success=True,
            message="SQLite WAL checkpoint completed successfully.",
            details={"busy": busy, "log": log, "checkpointed": checkpointed},
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Checkpoint error: {exc}")
