# ProRadCS Enterprise DICOM Gateway & Edge Node (v1.0.0-PROD)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Compliance](https://img.shields.io/badge/Standard-IEC%2062304%20Class%20B-blue.svg)]()
[![DICOM](https://img.shields.io/badge/DICOM-PS%203.15%20%7C%20PS%203.18-green.svg)]()
[![Tests](https://img.shields.io/badge/Tests-37%2F37%20Passing%20(100%25)-brightgreen.svg)]()

> **Medical Device Software Appliance Notice:**  
> ProRadCS Enterprise DICOM Gateway is an IEC 62304 Class B medical imaging buffer appliance engineered to ingest high-slice imaging modalities (CT, MRI, PET, CR, DX) at wire speed ($\ge 100\text{ MB/s}$), acknowledge with DIMSE status `0x0000`, anonymize out-of-band adhering to DICOM PS 3.15 Annex E Basic Application Level Confidentiality Profile, transcode losslessly via JPEG 2000 Part 1 / JPEG-LS, and relay optimized studies to upstream Cloud VNAs over WAN using DICOMweb STOW-RS with exponential backoff and jitter.

---

## Architecture Overview

```
                                      HOSPITAL LAN (Wire Speed >= 100 MB/s)
[CT / MRI Scanner (SCU)] ───────────────> [ Inbound C-STORE Port 104 ]
                                                      │
                                                      ▼ (MANDATE-DATA-002: Atomic .tmp -> fsync -> .dcm)
                                        [ D:\DICOM_Archive\staging ]
                                                      │
                                                      ▼ (Atomic UPDATE ... RETURNING)
                                            [ SQLite WAL Queue ]
                                            (pipeline_status: STAGED)
                                                      │
                        ┌─────────────────────────────┴─────────────────────────────┐
                        ▼                                                           ▼
         [ ProcessorWorkerDaemon ]                                     [ WebDashboardService ]
  - DICOM PS 3.15 De-Identification                               - FastAPI Telemetry Server (Port 8080)
    (Deterministic Salted Pseudonyms)                              - React Glassmorphism Dashboard
  - Lossless Image Transcoding (OpenJPEG)                         - Whitelist Modality Registry CRUD
    (JPEG 2000 Part 1 / JPEG-LS)                                   - Cryptographic Audit Verification
  - Cryptographic Blockchain Audit Trail                          - PRAGMA wal_checkpoint(TRUNCATE)
                        │
                        ▼ (DICOMweb STOW-RS PS 3.18 REST over HTTPS)
           [ Upstream Cloud VNA / PACS ]
```

---

## Key Capabilities & Architectural Mandates

### 1. Ingestion Performance & Transaction Finality
- **DIMSE C-STORE Ingestion (`DicomReceiverService`):** High-throughput C-STORE SCP listening on Port 104 with configurable association limits (default: 16).
- **MANDATE-DATA-002 (Atomic Write Protocol):** Inbound payloads are streamed to `.tmp` files, flushed to physical disk with `os.fsync`, and atomically renamed to `.dcm` before emitting a `0x0000` (Success) C-STORE response.
- **NFR-002 (Storage Safety Floor):** Continuously monitors the archive volume partition (`D:\DICOM_Archive`). If free disk space drops below the configured safety floor (default: 10%), incoming associations are rejected with DIMSE status `0xA700` (Out of Resources) to prevent file system starvation.

### 2. Zero-PHI De-Identification & Longitudinal Linkage
- **DICOM PS 3.15 Annex E Basic Profile:** Direct patient identifiers are stripped and replaced with deterministic pseudonyms (`PatientName` $\to$ `ANONYMIZED`, `PatientID` $\to$ `ANON-PT-<HASH>`, `AccessionNumber` $\to$ `ACC-<HASH>`).
- **MANDATE-PHI-001 (Zero-PHI in Logs & Storage):** Plain-text Protected Health Information is strictly barred from all logging channels, console streams, and database error columns. Only salted SHA-256 hashes (`patient_hash`) are logged.
- **Deterministic Longitudinal Linkage:** Salted SHA-256 hashing allows follow-up scans for the same patient to be linked consistently without exposing identifiable information.

### 3. Lossless Image Transcoding
- **Diagnostic Integrity (FR-PROC-002):** Uncompressed pixels are compressed using `openjpeg` to JPEG 2000 Part 1 Lossless (`1.2.840.10008.1.2.4.90`) or JPEG-LS Lossless (`1.2.840.10008.1.2.4.80`).
- **Multi-Process Concurrency:** CPU-heavy compression workers execute in dedicated OS processes via `ProcessPoolExecutor`, completely bypassing the Python Global Interpreter Lock (GIL).

### 4. Resilient Store-and-Forward Cloud Relay
- **DICOMweb STOW-RS (PS 3.18):** Encapsulates compressed DICOM binaries into RFC 2387 `multipart/related; type="application/dicom"` HTTP requests over TLS 1.3.
- **WAN Dropout Resilience (FR-FWD-002):** If WAN connectivity is interrupted, instances remain safely staged on disk in `PROCESSED` state.
- **Exponential Backoff with Jitter (FR-FWD-003):** Retries failed transmissions using exponential backoff with random jitter to prevent server thundering herd problems.

### 5. Cryptographic Blockchain Audit Trail
- **HIPAA § 164.312(b) Compliance:** Every security, ingest, transcode, forward, and administrative event is recorded in a tamper-evident SHA-256 hash-chained log.
- **Real-Time Verification:** The `/api/audit/verify` API cryptographically traverses the entire hash chain and immediately flags any altered or deleted records.

---

## Subsystem Services

The application runs as three decoupled background daemons managed by Windows Service Control Manager:

| Service Name | Executable | Port | Responsibilities |
| :--- | :--- | :--- | :--- |
| `DicomReceiverService` | `proradcs-receiver.exe` | `104` | C-STORE SCP ingestion, atomic disk staging, watermark enforcement. |
| `ProcessorWorker` | `proradcs-worker.exe` | N/A | Queue polling, PS 3.15 de-identification, OpenJPEG compression, STOW-RS upload. |
| `WebDashboardService` | `proradcs-web.exe` | `8080` | REST API, static asset hosting, telemetry, modality whitelist management. |

---

## Directory Structure

```
d:\Dicom Gateway\
├── backend/
│   ├── api/                   # FastAPI routes, models, and WebDashboardService daemon
│   ├── core/                  # Configuration (Pydantic), SQLite WAL database, Audit logger, Telemetry
│   ├── dicom/                 # C-STORE SCP server, association handling, and storage engine
│   └── workers/               # De-identification engine, OpenJPEG transcoder, STOW-RS uploader
├── deployment/
│   ├── build_binaries.py      # Automated PyInstaller & React build release pipeline
│   ├── installer.nsi          # Modern UI 2 NSIS Windows Setup Wizard
│   ├── proradcs-receiver.spec # PyInstaller spec for receiver daemon
│   ├── proradcs-worker.spec   # PyInstaller spec for worker daemon
│   └── proradcs-web.spec      # PyInstaller spec for web API daemon
├── docs/                      # Technical specifications, PRD, and regulatory rules
├── frontend/                  # React telemetry single-page dashboard
├── scripts/                   # PowerShell deployment and security hardening suite
└── tests/
    ├── integration/           # End-to-end pipeline integration tests
    └── unit/                  # Comprehensive unit tests (37 passing tests)
```

---

## Automated PowerShell Provisioning Suite

Located in `scripts/`, these scripts automate production server provisioning:

1. `checkPrereqs.ps1`: Validates Windows OS version (64-bit), CPU cores ($\ge 4$), RAM ($\ge 8\text{ GB}$), disk space ($\ge 100\text{ GB}$), PowerShell 5.1+, and port availability.
2. `createUserAccounts.ps1`: Provisions the unprivileged local service account `PacsServiceWorker` with `SeServiceLogonRight`.
3. `configureStorageAcls.ps1`: Applies strict NTFS Discretionary Access Control Lists (icacls) to `D:\DICOM_Archive`, granting full access to `PacsServiceWorker` and Administrators while blocking standard users.
4. `setupFirewall.ps1`: Configures Windows Defender Firewall rules for inbound Port 104 (restricted to modality subnets) and inbound Port 8080 (restricted to management subnets).
5. `setEnvironmentVars.ps1`: Configures persistent system-level environment variables (`PRCS_*`) and broadcasts `WM_SETTINGCHANGE`.
6. `installServices.ps1`: Registers and starts the 3 services via NSSM with automatic recovery policies and standard output redirection.
7. `backupScheduler.ps1`: Configures daily automated SQLite WAL truncate checkpointing and 14-day backup retention.
8. `healthCheck.ps1`: Validates end-to-end system health, services, port listeners, and database integrity.
9. `uninstallAll.ps1`: Gracefully tears down all services, firewall rules, and tasks while preserving clinical data by default.

---

## Configuration Reference

All settings can be configured via environment variables prefixed with `PRCS_`:

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PRCS_AE_TITLE` | `PRCS_EDGE_01` | Local DICOM Application Entity Title ($\le 16$ characters). |
| `PRCS_DICOM_PORT` | `104` | TCP listening port for inbound DICOM associations. |
| `PRCS_WEB_HOST` | `127.0.0.1` | Binding IP address for the local telemetry web server. |
| `PRCS_WEB_PORT` | `8080` | HTTP port for the web dashboard and REST API. |
| `PRCS_ARCHIVE_DIR` | `D:\DICOM_Archive` | Root storage directory for staged, processed, and database files. |
| `PRCS_STORAGE_MIN_FREE_PERCENT` | `10.0` | Minimum free disk space floor before rejecting scans with `0xA700`. |
| `PRCS_CLOUD_ENDPOINT` | `https://vna.hospital.org/stow` | Upstream Cloud VNA DICOMweb STOW-RS URL. |
| `PRCS_NODE_TOKEN` | `Bearer test-token-value` | Authorization bearer token for cloud relay. |
| `PRCS_UPLOAD_TIMEOUT_SECONDS` | `60.0` | HTTP request timeout for STOW-RS uploads. |
| `PRCS_UPLOAD_MAX_RETRIES` | `10` | Maximum retry attempts before parking failed uploads. |
| `PRCS_SALT` | `PRCS_LOCAL_SECURE_SALT...` | Site-specific salt for deterministic de-identification. |

---

## REST API Reference

The local API is accessible on port `8080` (`http://localhost:8080/docs`):

- `GET /api/health`: Overall health state, database connectivity, and storage watermark status.
- `GET /api/telemetry`: Hardware resource consumption (CPU, RAM, disk partitions) and live queue metrics.
- `GET /api/queue`: Real-time queue inspection with pagination and status filtering (`STAGED`, `PROCESSING`, `PROCESSED`, `FORWARDED`, `FAILED`, `QUARANTINED`).
- `GET /api/modalities`: List authorized DICOM SCU devices.
- `POST /api/modalities`: Add an authorized modality to the whitelist.
- `POST /api/modalities/{ae_title}/toggle`: Enable or disable an authorized modality.
- `GET /api/audit`: Paginated audit records (strictly Zero-PHI compliant).
- `GET /api/audit/verify`: Cryptographically traverses and validates the SHA-256 audit blockchain.
- `POST /api/actions/checkpoint`: Executes manual SQLite WAL `PRAGMA wal_checkpoint(TRUNCATE)`.

---

## Testing & Quality Assurance

The test suite covers unit and end-to-end integration scenarios:

```powershell
# Run the complete test suite
& "backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

### Test Suite Summary:
- `tests/unit/test_config.py` (4 tests) — Environment variable parsing, AE title constraints, directory initialization.
- `tests/unit/test_database.py` (5 tests) — Schema enforcement, WAL mode, atomic claim queries, foreign key validation.
- `tests/unit/test_audit.py` (4 tests) — Hash chaining, tamper detection, MANDATE-PHI-001 violation protection.
- `tests/unit/test_telemetry.py` (3 tests) — Storage watermark math, queue counting, system resource sampling.
- `tests/unit/test_anonymizer.py` (4 tests) — PS 3.15 Annex E de-identification, deterministic linkage, audit logging.
- `tests/unit/test_transcoder.py` (3 tests) — Bit-for-bit lossless JPEG 2000 Part 1 compression, non-image passthrough.
- `tests/unit/test_uploader.py` (6 tests) — PS 3.18 multipart formatting, exponential backoff with jitter, error handling.
- `tests/unit/test_api.py` (6 tests) — FastAPI route validation, modality CRUD, queue inspection, WAL checkpoints.
- `tests/integration/test_pipeline_e2e.py` (2 tests) — Complete end-to-end pipeline (Ingest $\to$ STAGED $\to$ Anonymize $\to$ Transcode $\to$ STOW-RS $\to$ FORWARDED) and WAN dropout buffering.

---

## Building the Installer

To compile the standalone binaries and build the Windows Setup installer:

```powershell
# Step 1: Run the automated release build orchestrator
& "backend\.venv\Scripts\python.exe" deployment\build_binaries.py

# Step 2: Compile the NSIS Setup Wizard
& "C:\Program Files (x86)\NSIS\makensis.exe" deployment\installer.nsi
```

Output installer is generated at:  
`deployment\dist\ProRadCS_Gateway_Setup_v1.0.0.0.exe`

---

## License

This software is released under the [MIT License](LICENSE).
