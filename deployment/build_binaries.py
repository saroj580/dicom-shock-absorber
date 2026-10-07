#!/usr/bin/env python3
"""ProRadCS Enterprise DICOM Gateway & Edge Node - Binary Build Orchestrator.

Automates the complete release build pipeline for IEC 62304 Class B packaging:
  1. Validates and compiles React SPA frontend (npm run build).
  2. Freezes decoupled Python services via PyInstaller:
     - proradcs-receiver.exe (DicomReceiverService)
     - proradcs-worker.exe   (ProcessorWorker)
     - proradcs-web.exe      (WebDashboardService)
  3. Prepares the release staging directory (deployment/staging/) for NSIS bundling.
"""

import argparse
import logging
from pathlib import Path
import shutil
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("proradcs.build")


class BuildOrchestrator:
    """Manages compilation, freezing, and staging of ProRadCS release artifacts."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.backend_dir = self.workspace_root / "backend"
        self.frontend_dir = self.workspace_root / "frontend"
        self.deployment_dir = self.workspace_root / "deployment"
        self.scripts_dir = self.workspace_root / "scripts"
        self.staging_dir = self.deployment_dir / "staging"
        self.dist_dir = self.deployment_dir / "dist"
        self.build_dir = self.deployment_dir / "build"

    def clean_artifacts(self) -> None:
        """Cleans intermediate build and distribution directories."""
        logger.info("Cleaning build artifacts...")
        for path in [self.staging_dir, self.dist_dir, self.build_dir]:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                logger.info(f"  Removed: {path.name}")

    def build_frontend(self) -> bool:
        """Compiles the React SPA if not already built or fresh build requested."""
        dist_index = self.frontend_dir / "dist" / "index.html"
        logger.info("Checking React frontend assets...")

        if dist_index.exists():
            logger.info("  Frontend assets already compiled at frontend/dist.")
            return True

        logger.info("  Compiling React SPA via npm run build...")
        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm_cmd:
            logger.error("NPM executable not found on PATH. Cannot compile frontend.")
            return False

        result = subprocess.run([npm_cmd, "run", "build"], cwd=self.frontend_dir)
        if result.returncode != 0:
            logger.error(f"Frontend compilation failed with code {result.returncode}")
            return False

        logger.info("  Frontend compiled successfully.")
        return True

    def freeze_binaries(self) -> bool:
        """Runs PyInstaller against all 3 service specifications."""
        specs = [
            self.deployment_dir / "proradcs-receiver.spec",
            self.deployment_dir / "proradcs-worker.spec",
            self.deployment_dir / "proradcs-web.spec",
        ]

        pyinstaller_cmd = shutil.which("pyinstaller.exe") or shutil.which("pyinstaller")
        if not pyinstaller_cmd:
            # Check virtualenv Scripts folder
            venv_pyinstaller = self.backend_dir / ".venv" / "Scripts" / "pyinstaller.exe"
            if venv_pyinstaller.exists():
                pyinstaller_cmd = str(venv_pyinstaller)
            else:
                logger.error("PyInstaller executable not found.")
                return False

        logger.info(f"Using PyInstaller: {pyinstaller_cmd}")
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        self.build_dir.mkdir(parents=True, exist_ok=True)

        for spec in specs:
            logger.info(f"Freezing binary from spec: {spec.name}...")
            cmd = [
                pyinstaller_cmd,
                "--noconfirm",
                f"--distpath={str(self.dist_dir)}",
                f"--workpath={str(self.build_dir)}",
                str(spec),
            ]
            result = subprocess.run(cmd, cwd=self.workspace_root)
            if result.returncode != 0:
                logger.error(f"PyInstaller failed on {spec.name} (exit code {result.returncode})")
                return False

        logger.info("All 3 binaries successfully frozen by PyInstaller.")
        return True

    def assemble_staging(self) -> bool:
        """Assembles all runtime files into deployment/staging/ for NSIS packaging."""
        logger.info(f"Assembling release staging tree at: {self.staging_dir}...")
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        bin_dir = self.staging_dir / "bin"
        scripts_dest = self.staging_dir / "scripts"
        frontend_dest = self.staging_dir / "frontend_dist"

        bin_dir.mkdir(parents=True, exist_ok=True)
        scripts_dest.mkdir(parents=True, exist_ok=True)

        # 1. Copy frozen executables if present
        binaries = [
            "proradcs-receiver.exe",
            "proradcs-worker.exe",
            "proradcs-web.exe",
        ]
        for b_name in binaries:
            src_exe = self.dist_dir / b_name
            if src_exe.exists():
                shutil.copy2(src_exe, bin_dir / b_name)
                logger.info(f"  Staged binary: {b_name}")
            else:
                logger.warning(f"  Binary not yet generated in dist/: {b_name}")

        # 2. Copy PowerShell automation scripts
        if self.scripts_dir.exists():
            for ps1_file in self.scripts_dir.glob("*.ps1"):
                shutil.copy2(ps1_file, scripts_dest / ps1_file.name)
            logger.info(f"  Staged {len(list(scripts_dest.glob('*.ps1')))} PowerShell scripts.")

        # 3. Copy compiled frontend assets
        fe_dist_src = self.frontend_dir / "dist"
        if fe_dist_src.exists():
            if frontend_dest.exists():
                shutil.rmtree(frontend_dest)
            shutil.copytree(fe_dist_src, frontend_dest)
            logger.info("  Staged frontend distribution assets.")

        logger.info("Staging assembly complete.")
        return True

    def execute_pipeline(self, clean: bool = False, skip_pyinstaller: bool = False) -> bool:
        """Runs the complete build pipeline."""
        logger.info("=================================================================")
        logger.info("  ProRadCS Enterprise DICOM Gateway - Build Pipeline Orchestrator ")
        logger.info("  Target: Release 1.0.0-PROD | Compliance: IEC 62304 Class B      ")
        logger.info("=================================================================")

        if clean:
            self.clean_artifacts()

        if not self.build_frontend():
            return False

        if not skip_pyinstaller:
            if not self.freeze_binaries():
                return False

        if not self.assemble_staging():
            return False

        logger.info("Build pipeline completed successfully!")
        return True


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="ProRadCS Binary Build Pipeline")
    parser.add_argument("--clean", action="store_true", help="Clean build directories before running")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Skip PyInstaller freeze step")
    args = parser.parse_args()

    orchestrator = BuildOrchestrator(workspace_root=Path(__file__).resolve().parent.parent)
    success = orchestrator.execute_pipeline(clean=args.clean, skip_pyinstaller=args.skip_pyinstaller)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
