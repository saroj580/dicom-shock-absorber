"""ProRadCS Enterprise DICOM Gateway & Edge Node - DICOM Data Models.

Defines Pydantic metadata schemas, standard DIMSE status codes, supported SOP Class UIDs,
and Transfer Syntax constants adhering to DICOM PS 3.4 and PS 3.5.
"""

from enum import IntEnum
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class DimseStatus(IntEnum):
    """Standard DICOM DIMSE service response status codes."""
    SUCCESS = 0x0000
    OUT_OF_RESOURCES = 0xA700       # NFR-002: Emitted when storage watermark falls below 10%
    DATASET_MISMATCH = 0xA900       # Emitted when received dataset does not match negotiated SOP Class
    PROCESSING_FAILURE = 0xC000     # Emitted on internal parse or I/O failure
    NOT_AUTHORIZED = 0x0122         # Emitted when calling AE title is rejected


# Standard Storage & Verification SOP Classes (FR-DICOM-002 & FR-DICOM-003)
VERIFICATION_SOP_CLASS = "1.2.840.10008.1.1"

SUPPORTED_STORAGE_SOP_CLASSES = [
    "1.2.840.10008.5.1.4.1.1.2",       # CT Image Storage
    "1.2.840.10008.5.1.4.1.1.2.1",     # Enhanced CT Image Storage
    "1.2.840.10008.5.1.4.1.1.4",       # MR Image Storage
    "1.2.840.10008.5.1.4.1.1.4.1",     # Enhanced MR Image Storage
    "1.2.840.10008.5.1.4.1.1.7",       # Secondary Capture Image Storage
    "1.2.840.10008.5.1.4.1.1.1.1",     # Digital X-Ray Image Storage (Presentation)
    "1.2.840.10008.5.1.4.1.1.1.1.1",   # Digital X-Ray Image Storage (Processing)
]

# Supported Inbound Transfer Syntaxes (FR-DICOM-004)
TRANSFER_SYNTAX_IMPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2"
TRANSFER_SYNTAX_EXPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2.1"
TRANSFER_SYNTAX_DEFLATED_EXPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2.1.99"

SUPPORTED_INBOUND_TRANSFER_SYNTAXES = [
    TRANSFER_SYNTAX_IMPLICIT_VR_LITTLE_ENDIAN,
    TRANSFER_SYNTAX_EXPLICIT_VR_LITTLE_ENDIAN,
    TRANSFER_SYNTAX_DEFLATED_EXPLICIT_VR_LITTLE_ENDIAN,
]

# Target Lossless Transcoding Syntaxes (FR-PROC-002)
TRANSFER_SYNTAX_JPEG_LS_LOSSLESS = "1.2.840.10008.1.2.4.80"
TRANSFER_SYNTAX_JPEG_2000_LOSSLESS = "1.2.840.10008.1.2.4.90"


class DicomInstanceMetadata(BaseModel):
    """Metadata extracted deterministically from an incoming DICOM instance."""
    sop_instance_uid: str = Field(..., description="Unique SOP Instance UID (0008,0018)")
    sop_class_uid: str = Field(..., description="SOP Class UID (0008,0016)")
    study_instance_uid: str = Field(..., description="Study Instance UID (0020,000D)")
    series_instance_uid: str = Field(..., description="Series Instance UID (0020,000E)")
    calling_ae_title: str = Field(..., description="AE Title of the sending modality")
    modality: Optional[str] = Field(None, description="Modality type e.g. CT, MR, DX (0008,0060)")
    transfer_syntax_uid: Optional[str] = Field(None, description="Transfer syntax UID")
    raw_patient_id: Optional[str] = Field(None, description="Raw Patient ID - strictly used for in-memory hashing")


class StoreResult(BaseModel):
    """Outcome of attempting to persist an incoming DICOM C-STORE dataset to disk."""
    status_code: int = Field(..., description="DIMSE integer status code returned to SCU")
    file_path: Optional[Path] = Field(None, description="Final file location on disk (.dcm or quarantine)")
    file_size_bytes: int = Field(0, description="Persisted file size in bytes")
    sha256_hash: Optional[str] = Field(None, description="Cryptographic SHA-256 digest of stored file")
    is_duplicate: bool = Field(False, description="True if identical instance already existed in database")
    error_message: Optional[str] = Field(None, description="Diagnostic error reason if operation failed")
