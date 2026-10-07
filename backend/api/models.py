"""ProRadCS Enterprise DICOM Gateway & Edge Node - Web API Data Models.

Defines Pydantic schemas for health diagnostics, telemetry payloads, modality registry
CRUD operations, queue tracking, and cryptographic audit chain verification.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthStatusResponse(BaseModel):
    """Overall appliance operational status and health metrics."""
    status: str = Field("HEALTHY", description="Overall system health status (HEALTHY, DEGRADED, CRITICAL)")
    version: str = Field("1.0.0-PROD", description="Appliance firmware/software release version")
    is_storage_safe: bool = Field(..., description="True if partition free space is above safety threshold")
    storage_free_percent: float = Field(..., description="Available storage percentage")
    database_connected: bool = Field(True, description="True if SQLite WAL database is accessible")
    ae_title: str = Field(..., description="Local DICOM Application Entity Title")
    dicom_port: int = Field(..., description="Listening port for inbound C-STORE")


class ModalityCreate(BaseModel):
    """Schema for registering a new medical imaging modality."""
    ae_title: str = Field(..., min_length=1, max_length=16, description="Modality AE Title (1-16 chars)")
    ip_address: str = Field(..., description="Static IP address or '*' for permissive testing")
    description: Optional[str] = Field(None, max_length=255, description="Human-readable modality description")
    is_active: bool = Field(True, description="Whether the modality is enabled")


class ModalityItem(BaseModel):
    """Registered modality record."""
    ae_title: str
    ip_address: str
    description: Optional[str] = None
    is_active: int
    created_at: str


class InstanceItem(BaseModel):
    """Individual DICOM instance metadata and pipeline tracking record."""
    sop_instance_uid: str
    sop_class_uid: str
    study_instance_uid: str
    series_instance_uid: str
    calling_ae_title: str
    original_file_path: str
    processed_file_path: Optional[str] = None
    file_size_bytes: int
    sha256_hash: str
    pipeline_status: str
    retry_count: int
    error_message: Optional[str] = None
    received_at: str
    processed_at: Optional[str] = None
    forwarded_at: Optional[str] = None


class QueueListResponse(BaseModel):
    """Paginated list of instances currently tracked in the persistence engine."""
    total_count: int
    instances: List[InstanceItem]


class AuditRecordItem(BaseModel):
    """Cryptographic chained audit log row."""
    log_id: int
    timestamp: str
    event_type: str
    actor: str
    patient_hash: Optional[str] = None
    details: Dict[str, Any]
    previous_hash: str
    current_hash: str


class AuditVerificationResult(BaseModel):
    """Result of full cryptographic blockchain-style hash chain validation."""
    is_chain_intact: bool = Field(..., description="True if all SHA-256 links are mathematically valid")
    total_records_verified: int
    error_message: Optional[str] = None


class ActionResponse(BaseModel):
    """Standard outcome response for administrative commands."""
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None
