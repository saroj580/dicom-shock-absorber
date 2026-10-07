"""ProRadCS Enterprise DICOM Gateway & Edge Node - WebDashboardService Daemon.

Standalone daemon entrypoint for the local telemetry web server (proradcs-web.exe).
Serves the FastAPI REST API, mounts pre-compiled React static assets, and handles
Windows/NSSM service signals cleanly.
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import signal
import sys
import threading
from typing import Any, AsyncGenerator, Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from backend.core.audit import (
    ACTOR_SERVICE_WORKER,
    EVENT_SERVICE_LIFECYCLE,
    AuditLogger,
    audit_logger,
)
from backend.core.config import settings
from backend.core.database import DatabaseManager, db_manager
from backend.api.routes import api_router


# Structured logger configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("proradcs.web.service")


def create_app(dist_dir: Optional[Path] = None, audit: Optional[AuditLogger] = None) -> FastAPI:
    """Creates and configures the FastAPI application with routes and static asset hosting."""
    active_audit = audit if audit is not None else audit_logger

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        active_audit.record_event(
            event_type=EVENT_SERVICE_LIFECYCLE,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "action": "START",
                "service": "WebDashboardService",
                "host": settings.web_host,
                "port": settings.web_port,
            },
        )
        yield
        active_audit.record_event(
            event_type=EVENT_SERVICE_LIFECYCLE,
            actor=ACTOR_SERVICE_WORKER,
            details={
                "action": "STOP",
                "service": "WebDashboardService",
            },
        )

    app = FastAPI(
        title="ProRadCS Edge Node Telemetry API",
        version="1.0.0-PROD",
        description="Local telemetry, queue monitoring, and management API for ProRadCS Edge Gateway.",
        lifespan=lifespan,
    )

    # Allow local loopback and LAN dashboard origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include REST API endpoints
    app.include_router(api_router)

    # Static Assets & React Dashboard Hosting
    static_root = dist_dir or (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist")
    index_html = static_root / "index.html"

    if static_root.exists() and index_html.exists():
        # Mount static assets directory
        assets_dir = static_root / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa_fallback(request: Request, full_path: str) -> Any:
            """SPA catch-all: serves static files or falls back to index.html for client routing."""
            candidate = static_root / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(index_html))
    else:
        @app.get("/", include_in_schema=False)
        async def serve_placeholder_index() -> HTMLResponse:
            """Fallback landing page displayed before React frontend is compiled."""
            return HTMLResponse(
                """
                <!DOCTYPE html>
                <html>
                <head><title>ProRadCS Edge Node</title></head>
                <body style="font-family: sans-serif; background: #090d16; color: #fff; padding: 40px;">
                    <h2>ProRadCS Edge Node (v1.0.0-PROD)</h2>
                    <p>WebDashboardService is online. REST API available at <a style="color: #38bdf8;" href="/docs">/docs</a>.</p>
                </body>
                </html>
                """
            )

    return app


class WebDashboardDaemon:
    """Manages the Uvicorn web server lifecycle under Windows SCM / NSSM."""

    def __init__(
        self,
        app: Optional[FastAPI] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
        audit: Optional[AuditLogger] = None,
    ) -> None:
        self.host = host or settings.web_host
        self.port = port or settings.web_port
        self.db = db if db is not None else db_manager
        self.audit = audit if audit is not None else audit_logger
        self.app = app or create_app(audit=self.audit)
        self.server: Optional[uvicorn.Server] = None
        self._stop_event = threading.Event()

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handles termination signals for clean Windows/NSSM service shutdown."""
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info(f"Received termination signal ({sig_name}). Initiating web server shutdown...")
        self.stop()

    def setup_signals(self) -> None:
        """Hooks POSIX and Windows termination signals (main thread only)."""
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, self._handle_signal)

    def start(self) -> None:
        """Initializes schema and runs Uvicorn server."""
        logger.info("=================================================================")
        logger.info("  ProRadCS Enterprise DICOM Gateway & Edge Node - Web Dashboard   ")
        logger.info(f"  Version: 1.0.0-PROD | Service Account: PacsServiceWorker       ")
        logger.info(f"  Binding: http://{self.host}:{self.port}                         ")
        logger.info("=================================================================")

        settings.ensure_directories()
        self.db.initialize_schema(seed_defaults=True)
        self.setup_signals()

        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.server.run()

    def stop(self) -> None:
        """Shuts down Uvicorn server."""
        if self.server is not None:
            self.server.should_exit = True


def main() -> None:
    """Entry point for standalone execution and PyInstaller binary packaging."""
    daemon = WebDashboardDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
