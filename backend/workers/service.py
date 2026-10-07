"""ProRadCS Enterprise DICOM Gateway & Edge Node - ProcessorWorker Daemon.

Standalone daemon entrypoint for the background compute engine (proradcs-worker.exe).
Polls SQLite for STAGED instances, applies PS 3.15 de-identification, executes lossless
compression via openjpeg, and relays optimized studies to Cloud VNA via STOW-RS.
"""

import logging
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any, Optional
import pydicom
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_SERVICE_LIFECYCLE,
    AuditLogger,
    audit_logger,
)
from backend.core.config import settings
from backend.core.database import DatabaseManager, db_manager
from backend.workers.anonymizer import DicomAnonymizer, anonymizer
from backend.workers.transcoder import DicomTranscoder, transcoder
from backend.workers.uploader import StowRsUploader, uploader


# Structured logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("proradcs.worker.service")


class ProcessorWorkerDaemon:
    """Orchestrates asynchronous pipeline processing from STAGED to FORWARDED."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        anon: Optional[DicomAnonymizer] = None,
        trans: Optional[DicomTranscoder] = None,
        up: Optional[StowRsUploader] = None,
        audit: Optional[AuditLogger] = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.db = db if db is not None else db_manager
        self.audit = audit if audit is not None else (AuditLogger(db=self.db) if db is not None else audit_logger)
        self.anon = anon if anon is not None else (DicomAnonymizer(audit=self.audit) if audit is not None else anonymizer)
        self.trans = trans if trans is not None else (DicomTranscoder(audit=self.audit) if audit is not None else transcoder)
        self.up = up if up is not None else (StowRsUploader(audit=self.audit) if audit is not None else uploader)
        self.poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handles termination signals for clean Windows/NSSM service shutdown."""
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info(f"Received termination signal ({sig_name}). Initiating worker shutdown...")
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

    def process_claimed_instance(self, record: dict) -> None:
        """Processes a single locked instance through anonymization, transcoding, and upload."""
        sop_uid = str(record["sop_instance_uid"])
        study_uid = str(record["study_instance_uid"])
        original_path = Path(record["original_file_path"])
        retry_count = int(record["retry_count"])

        logger.info(f"Processing claimed instance {sop_uid} (Study: {study_uid})...")

        if not original_path.exists():
            err_msg = f"Original file missing on disk: {original_path}"
            logger.error(err_msg)
            self.db.update_instance_status(sop_uid, status="FAILED", error_message=err_msg)
            return

        try:
            # Step 1: Read staged DICOM file and apply PS 3.15 Anonymization
            dataset = pydicom.dcmread(str(original_path), stop_before_pixels=False)
            sanitized_dataset = self.anon.anonymize_dataset(dataset)

            # Save sanitized dataset to temporary staging file before transcoding
            temp_anon_path = original_path.with_suffix(".anon.tmp")
            sanitized_dataset.save_as(str(temp_anon_path), write_like_original=False)

            # Step 2: Transcode pixels losslessly to JPEG 2000 Part 1
            processed_dir = settings.processed_dir / study_uid
            processed_dir.mkdir(parents=True, exist_ok=True)
            target_processed_path = processed_dir / f"{sop_uid}.dcm"

            final_processed_path, file_size, file_hash = self.trans.transcode_file(
                input_path=temp_anon_path,
                output_path=target_processed_path,
            )

            # Remove intermediate anonymized temp file
            temp_anon_path.unlink(missing_ok=True)

            # Step 3: Transition database state to PROCESSED
            self.db.update_instance_status(
                sop_instance_uid=sop_uid,
                status="PROCESSED",
                processed_file_path=str(final_processed_path),
            )

            # Step 4: Transmit compressed payload to Cloud VNA via STOW-RS
            self.db.update_instance_status(sop_instance_uid=sop_uid, status="UPLOADING")
            upload_ok, upload_err = self.up.upload_instance(
                file_path=final_processed_path,
                study_instance_uid=study_uid,
                sop_instance_uid=sop_uid,
                current_retry_count=retry_count,
            )

            if upload_ok:
                self.db.update_instance_status(sop_instance_uid=sop_uid, status="FORWARDED")
                logger.info(f"Successfully forwarded instance {sop_uid} to Cloud VNA.")
            else:
                new_retry = retry_count + 1
                if new_retry >= settings.upload_max_retries:
                    self.db.update_instance_status(
                        sop_instance_uid=sop_uid,
                        status="FAILED",
                        error_message=f"Exceeded max retries ({new_retry}): {upload_err}",
                        increment_retry=True,
                    )
                    logger.error(f"Instance {sop_uid} marked FAILED after {new_retry} retries.")
                else:
                    self.db.update_instance_status(
                        sop_instance_uid=sop_uid,
                        status="PROCESSED",
                        error_message=upload_err,
                        increment_retry=True,
                    )
                    logger.warning(f"Instance {sop_uid} parked in PROCESSED for retry {new_retry}.")

        except Exception as exc:
            err_msg = f"Internal pipeline failure: {exc}"
            logger.error(f"Pipeline error for {sop_uid}: {exc}")
            self.db.update_instance_status(
                sop_instance_uid=sop_uid,
                status="FAILED",
                error_message=err_msg,
                increment_retry=True,
            )

    def run_loop(self) -> None:
        """Continuous polling loop consuming STAGED instances."""
        logger.info("=================================================================")
        logger.info("  ProRadCS Enterprise DICOM Gateway & Edge Node - Worker Service  ")
        logger.info(f"  Version: 1.0.0-PROD | Service Account: PacsServiceWorker       ")
        logger.info(f"  Cloud Endpoint: {settings.cloud_endpoint}                      ")
        logger.info(f"  Archive Directory: {settings.archive_dir}                       ")
        logger.info("=================================================================")

        settings.ensure_directories()
        self.db.initialize_schema(seed_defaults=True)

        self.audit.record_event(
            event_type=EVENT_SERVICE_LIFECYCLE,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "action": "START",
                "service": "ProcessorWorkerService",
                "endpoint": settings.cloud_endpoint,
            },
        )

        self.setup_signals()
        logger.info("ProcessorWorker is ONLINE and actively polling for STAGED instances.")

        while not self._stop_event.is_set():
            try:
                # Atomically claim next STAGED instance (User Guidance Q2)
                record = self.db.claim_next_staged_instance()
                if record is not None:
                    self.process_claimed_instance(record)
                else:
                    # Queue is empty; sleep poll interval
                    time.sleep(self.poll_interval)
            except Exception as poll_err:
                logger.error(f"Unexpected error in worker poll loop: {poll_err}")
                time.sleep(self.poll_interval)

    def start(self) -> None:
        """Starts the worker daemon loop."""
        self.run_loop()

    def stop(self) -> None:
        """Gracefully signals the worker loop to terminate."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self.audit.record_event(
            event_type=EVENT_SERVICE_LIFECYCLE,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "action": "STOP",
                "service": "ProcessorWorkerService",
            },
        )
        logger.info("ProcessorWorker stopped cleanly.")


def main() -> None:
    """Entry point for standalone execution and PyInstaller binary packaging."""
    daemon = ProcessorWorkerDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
