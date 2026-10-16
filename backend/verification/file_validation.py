"""
Upload validation.

Security rules:
* The file type is decided from the file's magic bytes, never from the extension
  or the browser-supplied content type.
* The size limit is enforced while streaming, before the whole file is in memory.
* Images are decoded and re-encoded to a fresh PNG, which discards any hidden
  payload and metadata. Metadata that matters for forensics (editing software,
  PDF producer) is captured BEFORE re-encoding.
* PDFs: max 2 pages, no passwords, no JavaScript/launch actions.
"""
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List

import filetype
import pymupdf
from fastapi import UploadFile
from PIL import Image, ImageOps

from . import config

Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS


class FileValidationError(Exception):
    """Raised with a user-safe message."""


@dataclass
class ValidatedDocument:
    pages: List[bytes]  # PNG bytes
    source_type: str  # "image" | "pdf"
    meta: Dict[str, Any] = field(default_factory=dict)


async def read_limited(upload: UploadFile, max_bytes: int = config.MAX_UPLOAD_BYTES) -> bytes:
    """Read the upload in chunks and stop as soon as it exceeds the limit."""
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FileValidationError(
                f"File too large. Maximum size is {max_bytes // (1024 * 1024)} MB."
            )
        chunks.append(chunk)
    if total == 0:
        raise FileValidationError("The uploaded file is empty.")
    return b"".join(chunks)


def validate_and_normalise(data: bytes) -> ValidatedDocument:
    """Blocking (CPU) work - call it through run_in_threadpool."""
    kind = filetype.guess(data)
    mime = kind.mime if kind else None
    if mime not in config.ALLOWED_MIME:
        raise FileValidationError("Unsupported file type. Please upload a JPG, PNG or PDF.")
    if mime == "application/pdf":
        return _handle_pdf(data)
    return _handle_image(data)


# --------------------------------------------------------------------------
def _handle_image(data: bytes) -> ValidatedDocument:
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size  # header only, nothing decoded yet
        if width * height > config.MAX_IMAGE_PIXELS:
            raise FileValidationError("Image dimensions are too large.")

        # Grab forensic metadata before we re-encode (which strips it).
        exif_software = None
        try:
            exif = img.getexif()
            software = exif.get(0x0131)  # EXIF "Software" tag
            exif_software = str(software) if software else None
        except Exception:
            pass

        img.load()  # decode fully; raises on corrupt/truncated files
        img = ImageOps.exif_transpose(img)  # apply phone rotation
        img = img.convert("RGB")
    except FileValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise FileValidationError("Image dimensions are too large.")
    except Exception:
        raise FileValidationError("The image could not be read. It may be corrupt.")

    out = io.BytesIO()
    img.save(out, format="PNG")
    return ValidatedDocument(
        pages=[out.getvalue()],
        source_type="image",
        meta={"exif_software": exif_software, "had_exif": exif_software is not None},
    )


def _handle_pdf(data: bytes) -> ValidatedDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise FileValidationError("The PDF could not be read. It may be corrupt.")

    try:
        if doc.needs_pass or doc.is_encrypted:
            raise FileValidationError("Password-protected PDFs are not supported.")
        if doc.page_count < 1:
            raise FileValidationError("The PDF has no pages.")
        if doc.page_count > config.MAX_PDF_PAGES:
            raise FileValidationError(
                f"The PDF has too many pages (max {config.MAX_PDF_PAGES})."
            )

        # Crude but effective: reject active content.
        lowered = data.lower()
        for marker in (b"/javascript", b"/js ", b"/launch", b"/embeddedfile"):
            if marker in lowered:
                raise FileValidationError("This PDF contains active or embedded content.")

        md = doc.metadata or {}
        meta = {
            "pdf_producer": md.get("producer") or None,
            "pdf_creator": md.get("creator") or None,
            "pdf_creation_date": md.get("creationDate") or None,
            "pdf_mod_date": md.get("modDate") or None,
        }

        pages: List[bytes] = []
        zoom = config.PDF_RENDER_DPI / 72.0
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            if pix.width * pix.height > config.MAX_IMAGE_PIXELS:
                raise FileValidationError("The PDF page is too large.")
            pages.append(pix.tobytes("png"))
        return ValidatedDocument(pages=pages, source_type="pdf", meta=meta)
    finally:
        doc.close()
