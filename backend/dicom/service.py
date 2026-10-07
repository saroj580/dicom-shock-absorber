"""ProRadCS Enterprise DICOM Gateway & Edge Node - DicomReceiverService Daemon.

Standalone daemon entrypoint for the DICOM ingestion service (proradcs-receiver.exe).
Orchestrates graceful signal handling, schema verification, and the C-STORE/C-ECHO SCP server.
"""

import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Optional
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_SERVICE_LIFECYCLE,
    AuditLogger,
    audit_logger,
)
from backend.core.config import settings
from backend.core.database import DatabaseManager, db_manager
from backend.dicom.scp import DicomScpService, scp_service


# Structured logger configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("proradcs.receiver.service")


class DicomReceiverDaemon:
    """Manages the lifecycle of the DicomReceiverService background daemon."""

    def __init__(
        self,
        service: DicomScpService = scp_service,
        db: Optional[DatabaseManager] = None,
        audit: Optional[AuditLogger] = None,
    ) -> None:
        self.service = service
        self.db = db if db is not None else db_manager
        self.audit = audit if audit is not None else (AuditLogger(db=self.db) if db is not None else audit_logger)
        self._stop_event = threading.Event()

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handles termination signals for clean Windows/NSSM service shutdown."""
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info(f"Received termination signal ({sig_name}). Initiating graceful shutdown...")
        self.stop()

    def setup_signals(self) -> None:
        """Hooks POSIX and Windows termination signals (main thread only)."""
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        if hasattr(signal, "SIGBREAK"):
            # Windows Console Break signal (sent by SCM / NSSM)
            signal.signal(signal.SIGBREAK, self._handle_signal)

    def start(self) -> None:
        """Initializes storage directories, validates SQLite schema, and launches SCP listener."""
        logger.info("=================================================================")
        logger.info("  ProRadCS Enterprise DICOM Gateway & Edge Node - Ingestion SCP   ")
        logger.info(f"  Version: 1.0.0-PROD | Service Account: PacsServiceWorker       ")
        logger.info(f"  Listening Port: {settings.dicom_port} | AE Title: {settings.ae_title}   ")
        logger.info(f"  Archive Root: {settings.archive_dir}                            ")
        logger.info("=================================================================")

        # Step 1: Ensure directory structure exists
        settings.ensure_directories()

        # Step 2: Ensure database schema is ready
        self.db.initialize_schema(seed_defaults=True)

        # Step 3: Record service start in audit trail
        self.audit.record_event(
            event_type=EVENT_SERVICE_LIFECYCLE,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "action": "START",
                "service": "DicomReceiverService",
                "port": settings.dicom_port,
                "ae_title": settings.ae_title,
            },
        )

        # Step 4: Hook OS shutdown signals
        self.setup_signals()

        # Step 5: Start SCP network listener in background thread
        self.service.start_server(block=False)
        logger.info("DicomReceiverService is ONLINE and ready for clinical modality connections.")

        # Keep main thread alive until stop signal received
        try:
            while not self._stop_event.is_set():
                time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self) -> None:
        """Shuts down SCP listener and logs termination event."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        logger.info("Stopping DICOM SCP network server...")
        self.service.stop_server()

        self.audit.record_event(
            event_type=EVENT_SERVICE_LIFECYCLE,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "action": "STOP",
                "service": "DicomReceiverService",
            },
        )
        logger.info("DicomReceiverService stopped cleanly.")


def main() -> None:
    """Entry point for standalone execution and PyInstaller binary packaging."""
    daemon = DicomReceiverDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
