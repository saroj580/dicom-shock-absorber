"""ProRadCS Enterprise DICOM Gateway & Edge Node - DICOM SCP Network Daemon.

Implements FR-DICOM-001 (multi-association listener), FR-DICOM-002 (C-ECHO),
FR-DICOM-003/004 (presentation context negotiation), NFR-002 (watermark safeguard 0xA700),
and calling AE Title access control validation.
"""

import logging
from typing import Optional
from pynetdicom import AE, evt
from pynetdicom.events import Event
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import Verification
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_SECURITY_VIOLATION,
    EVENT_STORAGE_WATERMARK,
    audit_logger,
)
from backend.core.config import settings
from backend.core.database import DatabaseManager, db_manager
from backend.core.telemetry import TelemetryCollector, telemetry_collector
from backend.dicom.models import (
    DimseStatus,
    SUPPORTED_INBOUND_TRANSFER_SYNTAXES,
    SUPPORTED_STORAGE_SOP_CLASSES,
    VERIFICATION_SOP_CLASS,
)
from backend.dicom.storage import DicomStorageEngine, storage_engine


logger = logging.getLogger("proradcs.dicom.scp")


class DicomScpService:
    """Production-grade DICOM C-STORE and C-ECHO Service Class Provider (SCP)."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        storage: Optional[DicomStorageEngine] = None,
        telemetry: Optional[TelemetryCollector] = None,
    ) -> None:
        self.db = db if db is not None else db_manager
        self.storage = storage if storage is not None else storage_engine
        self.telemetry = telemetry if telemetry is not None else telemetry_collector
        self.ae = AE(ae_title=settings.ae_title)
        self._server = None
        self._configure_presentation_contexts()

    def _configure_presentation_contexts(self) -> None:
        """Configures supported SOP classes and transfer syntaxes per DICOM PS 3.4/3.5."""
        # 1. Verification SOP Class (C-ECHO - FR-DICOM-002)
        self.ae.add_supported_context(
            Verification,
            SUPPORTED_INBOUND_TRANSFER_SYNTAXES,
        )

        # 2. Supported Clinical Storage SOP Classes (FR-DICOM-003 & FR-DICOM-004)
        for sop_class_uid in SUPPORTED_STORAGE_SOP_CLASSES:
            self.ae.add_supported_context(
                sop_class_uid,
                SUPPORTED_INBOUND_TRANSFER_SYNTAXES,
            )

        # Maximum concurrent incoming associations
        self.ae.maximum_associations = settings.max_associations

    def handle_c_echo(self, event: Event) -> int:
        """Handles inbound C-ECHO verification ping from modality (FR-DICOM-002)."""
        raw_ae = getattr(event.assoc.requestor, "ae_title", "")
        calling_ae = (raw_ae.decode("ascii", errors="replace") if isinstance(raw_ae, bytes) else str(raw_ae)).strip()
        calling_ip = getattr(event.assoc.requestor, "address", None) or getattr(event.assoc, "remote_ip", None) or "127.0.0.1"
        logger.info(f"C-ECHO received from Calling AE='{calling_ae}' IP={calling_ip}")
        return DimseStatus.SUCCESS

    def handle_c_store(self, event: Event) -> int:
        """Handles inbound C-STORE image push with storage safeguard and atomic persistence."""
        raw_ae = getattr(event.assoc.requestor, "ae_title", "")
        calling_ae = (raw_ae.decode("ascii", errors="replace") if isinstance(raw_ae, bytes) else str(raw_ae)).strip()
        calling_ip = getattr(event.assoc.requestor, "address", None) or getattr(event.assoc, "remote_ip", None) or "127.0.0.1"

        # Step 1: Storage Watermark Safeguard (NFR-002)
        if not self.telemetry.is_storage_safe():
            storage_info = self.telemetry.get_storage_telemetry()
            logger.warning(
                f"REJECTING C-STORE: Partition free space ({storage_info.free_percent}%) "
                f"below safety floor ({storage_info.min_required_percent}%). Emitting 0xA700."
            )
            audit_logger.record_event(
                event_type=EVENT_STORAGE_WATERMARK,
                actor=ACTOR_SERVICE_WORKER,
                details={
                    "warning": "Partition storage capacity exceeded watermark floor",
                    "free_percent": storage_info.free_percent,
                    "calling_ae": calling_ae,
                    "dimse_status": "0xA700",
                },
            )
            return DimseStatus.OUT_OF_RESOURCES

        # Step 2: Validate Calling AE Title & IP against Modality Whitelist
        if not self.db.is_ae_title_allowed(calling_ae, calling_ip):
            logger.warning(f"REJECTING C-STORE: Modality '{calling_ae}' from {calling_ip} is not authorized.")
            audit_logger.record_event(
                event_type=EVENT_SECURITY_VIOLATION,
                actor=ACTOR_SERVICE_WORKER,
                details={
                    "warning": "Unauthorized AE Title attempted C-STORE",
                    "calling_ae": calling_ae,
                    "calling_ip": calling_ip,
                },
            )
            return DimseStatus.NOT_AUTHORIZED

        # Step 3: Persist dataset atomically before acknowledging (FR-DICOM-005)
        result = self.storage.persist_dataset(event.dataset, calling_ae=calling_ae)
        if result.status_code != DimseStatus.SUCCESS:
            logger.error(f"C-STORE storage failed for {calling_ae}: {result.error_message}")
        return result.status_code

    def start_server(self, block: bool = True) -> None:
        """Binds and starts the network listener on configured port (FR-DICOM-001)."""
        handlers = [
            (evt.EVT_C_ECHO, self.handle_c_echo),
            (evt.EVT_C_STORE, self.handle_c_store),
        ]
        logger.info(f"Starting ProRadCS DICOM SCP on port {settings.dicom_port} (AE: {settings.ae_title})...")
        self._server = self.ae.start_server(
            (settings.web_host if settings.web_host == "127.0.0.1" else "", settings.dicom_port),
            evt_handlers=handlers,
            block=block,
        )

    def stop_server(self) -> None:
        """Gracefully halts the DICOM network listener."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            logger.info("ProRadCS DICOM SCP stopped.")


# Global SCP service singleton
scp_service = DicomScpService()
