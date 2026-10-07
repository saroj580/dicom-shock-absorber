"""Unit tests for ProRadCS Edge Gateway configuration subsystem."""

from pathlib import Path
import pytest
from backend.core.config import EdgeSettings


def test_default_config_initialization(tmp_path: Path) -> None:
    """Verifies default settings conform to IEC 62304 specification."""
    cfg = EdgeSettings(archive_dir=tmp_path / "DICOM_Archive")
    assert cfg.ae_title == "PRCS_EDGE_01"
    assert cfg.dicom_port == 104
    assert cfg.web_port == 8080
    assert cfg.cloud_endpoint == "https://vna.hospital.org/stow"
    assert cfg.upload_max_retries == 10

    # Check derived filesystem paths
    assert cfg.staging_dir == (cfg.archive_dir / "staging").resolve()
    assert cfg.processed_dir == (cfg.archive_dir / "processed").resolve()
    assert cfg.quarantine_dir == (cfg.archive_dir / "quarantine").resolve()
    assert cfg.backup_dir == (cfg.archive_dir / "backups").resolve()
    assert cfg.database_path == (cfg.archive_dir / "database.db").resolve()


def test_environment_variable_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verifies machine environment variables override defaults cleanly."""
    custom_archive = tmp_path / "CustomArchive"
    monkeypatch.setenv("PRCS_AE_TITLE", "CUSTOM_SCP_01")
    monkeypatch.setenv("PRCS_DICOM_PORT", "11112")
    monkeypatch.setenv("PRCS_WEB_PORT", "9090")
    monkeypatch.setenv("PRCS_ARCHIVE_DIR", str(custom_archive))
    monkeypatch.setenv("PRCS_CLOUD_ENDPOINT", "https://custom.cloud.pacs/stow")

    cfg = EdgeSettings()
    assert cfg.ae_title == "CUSTOM_SCP_01"
    assert cfg.dicom_port == 11112
    assert cfg.web_port == 9090
    assert cfg.archive_dir == custom_archive
    assert cfg.cloud_endpoint == "https://custom.cloud.pacs/stow"


def test_ae_title_validation() -> None:
    """Verifies DICOM standard AE title constraints."""
    # Valid
    cfg = EdgeSettings(ae_title="VALID_AET")
    assert cfg.ae_title == "VALID_AET"

    # Too long (> 16 chars)
    with pytest.raises(ValueError, match="exceeds maximum 16 characters"):
        EdgeSettings(ae_title="VERY_LONG_AE_TITLE_OVER_16")

    # Illegal characters (spaces, quotes)
    with pytest.raises(ValueError, match="contains illegal characters"):
        EdgeSettings(ae_title="INVALID AET")


def test_ensure_directories_creates_tree(tmp_path: Path) -> None:
    """Verifies directory provisioning creates all required storage roots."""
    target_root = tmp_path / "AutoProvisionArchive"
    cfg = EdgeSettings(archive_dir=target_root)

    assert not target_root.exists()
    cfg.ensure_directories()

    assert target_root.exists()
    assert cfg.staging_dir.exists()
    assert cfg.processed_dir.exists()
    assert cfg.quarantine_dir.exists()
    assert cfg.backup_dir.exists()
