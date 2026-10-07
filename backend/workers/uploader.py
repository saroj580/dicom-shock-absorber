"""ProRadCS Enterprise DICOM Gateway & Edge Node - WAN STOW-RS Uploader.

Implements FR-FWD-001 (DICOMweb STOW-RS PS 3.18 REST over HTTPS cloud relay),
FR-FWD-002 (offline buffer retention on WAN dropouts), and FR-FWD-003 (exponential
backoff with jitter).
"""

import logging
from pathlib import Path
import random
import time
from typing import Optional, Tuple
import httpx
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_FORWARD_FAILURE,
    EVENT_FORWARD_SUCCESS,
    AuditLogger,
    audit_logger,
)
from backend.core.config import settings


logger = logging.getLogger("proradcs.workers.uploader")


class StowRsUploader:
    """Manages resilient HTTPS multipart DICOMweb STOW-RS uploads to upstream Cloud VNA."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        audit: Optional[AuditLogger] = None,
    ) -> None:
        self.endpoint = endpoint or settings.cloud_endpoint
        self.token = token or settings.node_token
        self.timeout = timeout or settings.upload_timeout_seconds
        self.max_retries = max_retries or settings.upload_max_retries
        self.audit = audit if audit is not None else audit_logger

    def _build_multipart_payload(self, file_bytes: bytes, boundary: str = "PRCS_DICOM_BOUNDARY") -> Tuple[bytes, str]:
        """Encapsulates raw DICOM binary data into standard PS 3.18 multipart/related envelope."""
        delimiter = f"--{boundary}\r\n".encode("utf-8")
        headers = b"Content-Type: application/dicom\r\n\r\n"
        closing = f"\r\n--{boundary}--\r\n".encode("utf-8")
        
        body = delimiter + headers + file_bytes + closing
        content_type = f'multipart/related; type="application/dicom"; boundary="{boundary}"'
        return body, content_type

    def calculate_backoff_delay(self, retry_count: int, base: float = 2.0, max_delay: float = 300.0) -> float:
        """Calculates exponential backoff delay with random jitter (FR-FWD-003)."""
        calculated = min(max_delay, base * (2.0 ** retry_count))
        jitter = random.uniform(0.1, 1.0)
        return calculated + jitter

    def upload_instance(
        self,
        file_path: Path,
        study_instance_uid: str,
        sop_instance_uid: str,
        current_retry_count: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Uploads a single transcoded DICOM file to the cloud via STOW-RS."""
        if not file_path.exists():
            err_msg = f"File not found on disk: {file_path}"
            logger.error(err_msg)
            return False, err_msg

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            body, content_type = self._build_multipart_payload(file_bytes)

            headers = {
                "Content-Type": content_type,
                "Accept": "application/dicom+json, application/json",
            }
            if self.token:
                headers["Authorization"] = self.token

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint,
                    content=body,
                    headers=headers,
                )

            # Standard STOW-RS responses: 200 OK or 202 Accepted
            if response.status_code in (200, 202):
                logger.info(
                    f"STOW-RS Success: {sop_instance_uid} pushed to {self.endpoint} "
                    f"(HTTP {response.status_code})"
                )
                self.audit.record_event(
                    event_type=EVENT_FORWARD_SUCCESS,
                    actor=ACTOR_SERVICE_WORKER,
                    details={
                        "sop_instance_uid": sop_instance_uid,
                        "study_instance_uid": study_instance_uid,
                        "http_status": response.status_code,
                        "endpoint": self.endpoint,
                    },
                )
                return True, None
            else:
                err_msg = f"Cloud VNA rejected payload (HTTP {response.status_code}): {response.text[:200]}"
                logger.warning(err_msg)
                self.audit.record_event(
                    event_type=EVENT_FORWARD_FAILURE,
                    actor=ACTOR_SERVICE_WORKER,
                    details={
                        "sop_instance_uid": sop_instance_uid,
                        "study_instance_uid": study_instance_uid,
                        "http_status": response.status_code,
                        "error": err_msg,
                        "retry_count": current_retry_count + 1,
                    },
                )
                return False, err_msg

        except Exception as exc:
            err_msg = f"WAN transport exception: {exc}"
            logger.warning(f"STOW-RS Network failure for {sop_instance_uid}: {exc}")
            self.audit.record_event(
                event_type=EVENT_FORWARD_FAILURE,
                actor=ACTOR_SERVICE_WORKER,
                details={
                    "sop_instance_uid": sop_instance_uid,
                    "study_instance_uid": study_instance_uid,
                    "error": str(exc),
                    "retry_count": current_retry_count + 1,
                },
            )
            return False, err_msg


# Global uploader singleton
uploader = StowRsUploader()
