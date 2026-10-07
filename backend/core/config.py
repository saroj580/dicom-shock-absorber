"""ProRadCS Enterprise DICOM Gateway & Edge Node - Configuration Module.

Loads and validates system-wide runtime configuration from environment variables
(PRCS_*) with production-ready defaults and directory management.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EdgeSettings(BaseSettings):
    """Runtime configuration for ProRadCS Edge Gateway services.

    Reads configuration values from system environment variables prefixed with 'PRCS_'.
    Provides fallback defaults suitable for both production and development environments.
    """

    model_config = SettingsConfigDict(
        env_prefix="PRCS_",
        case_sensitive=False,
        extra="ignore",
    )

    # DICOM Network Configuration
    ae_title: str = Field(
        default="PRCS_EDGE_01",
        description="Local DICOM Application Entity Title (max 16 characters per DICOM PS 3.5).",
    )
    dicom_port: int = Field(
        default=104,
        ge=1,
        le=65535,
        description="Listening TCP port for inbound DICOM C-STORE and C-ECHO associations.",
    )
    max_associations: int = Field(
        default=16,
        ge=1,
        le=128,
        description="Maximum concurrent incoming DICOM network associations.",
    )

    # Local Telemetry Web Server Configuration
    web_host: str = Field(
        default="127.0.0.1",
        description="Binding address for the local FastAPI telemetry server.",
    )
    web_port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="HTTP port for the local telemetry dashboard.",
    )

    # File Storage & Archive Paths
    archive_dir: Path = Field(
        default=Path("D:/DICOM_Archive"),
        description="Root directory for DICOM storage (staging, processed, quarantine, database).",
    )
    storage_min_free_percent: float = Field(
        default=10.0,
        ge=1.0,
        le=90.0,
        description="Minimum free storage partition percentage before rejecting C-STORE with 0xA700.",
    )

    # Upstream Cloud WAN Relay Configuration (STOW-RS default)
    cloud_endpoint: str = Field(
        default="https://vna.hospital.org/stow",
        description="Upstream Cloud VNA STOW-RS REST endpoint (DICOMweb PS 3.18).",
    )
    node_token: str = Field(
        default="Bearer test-token-value",
        description="Authorization bearer token for upstream Cloud VNA relay.",
    )
    upload_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="HTTP request timeout for WAN uploads.",
    )
    upload_max_retries: int = Field(
        default=10,
        ge=1,
        description="Maximum retry attempts before temporarily parking failed uploads.",
    )

    # Pseudonymization Security
    salt: str = Field(
        default="PRCS_LOCAL_SECURE_SALT_987214_STABLE",
        min_length=16,
        description="Internal site-specific salt for deterministic longitudinal de-identification.",
    )

    # Database Path (defaults to database.db within archive_dir)
    db_path_override: Optional[Path] = Field(
        default=None,
        description="Explicit override for the SQLite database file path.",
    )

    @field_validator("ae_title")
    @classmethod
    def validate_ae_title(cls, value: str) -> str:
        """Enforces DICOM standard AE title constraints: 1-16 ASCII characters."""
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("AE Title cannot be empty.")
        if len(cleaned) > 16:
            raise ValueError(f"AE Title '{cleaned}' exceeds maximum 16 characters.")
        if any(char in cleaned for char in ("\\", "\"", "\'", " ")):
            raise ValueError(f"AE Title '{cleaned}' contains illegal characters (backslash, quotes, spaces).")
        return cleaned

    @property
    def database_path(self) -> Path:
        """Returns the fully qualified path to the primary SQLite database."""
        if self.db_path_override is not None:
            return self.db_path_override.resolve()
        return (self.archive_dir / "database.db").resolve()

    @property
    def staging_dir(self) -> Path:
        """Directory where incoming raw DICOM files are staged before processing."""
        return (self.archive_dir / "staging").resolve()

    @property
    def processed_dir(self) -> Path:
        """Directory where anonymized and losslessly transcoded DICOM files are placed."""
        return (self.archive_dir / "processed").resolve()

    @property
    def quarantine_dir(self) -> Path:
        """Directory where corrupted or non-compliant DICOM files are isolated."""
        return (self.archive_dir / "quarantine").resolve()

    @property
    def backup_dir(self) -> Path:
        """Directory where daily database WAL snapshots and audit exports are retained."""
        return (self.archive_dir / "backups").resolve()

    def ensure_directories(self) -> None:
        """Creates the required archive directory tree if not already present."""
        for target_dir in (
            self.archive_dir,
            self.staging_dir,
            self.processed_dir,
            self.quarantine_dir,
            self.backup_dir,
        ):
            target_dir.mkdir(parents=True, exist_ok=True)


# Singleton configuration instance for edge services
settings = EdgeSettings()
