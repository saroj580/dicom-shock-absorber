"""ProRadCS Enterprise DICOM Gateway & Edge Node - Processor Worker Package.

Provides out-of-band DICOM de-identification (PS 3.15 Annex E), lossless image transcoding
(JPEG-LS & JPEG 2000 Part 1 via pylibjpeg), and resilient WAN STOW-RS cloud relay.
"""

__all__ = ["anonymizer", "transcoder", "uploader", "service"]
