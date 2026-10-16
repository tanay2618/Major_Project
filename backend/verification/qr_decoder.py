"""
Find and decode the Aadhaar QR code in a page image, then parse it.

Two kinds of QR exist on Aadhaar documents:

* SECURE QR (printed on cards/letters since 2018, also e-Aadhaar). A very long string of
  decimal digits. It is a big number whose bytes are a gzip stream. After decompressing:

      [ header and detail fields separated by 0xFF ][ photo (JPEG2000) ][ 256-byte RSA signature ]

  The signature covers every byte before it.

  Detail field order (reconstructed from UIDAI's published layout as implemented by
  open-source decoders such as pyaadhaar; VERIFY against a real card of yours):

      Newer cards (data starts with 'V' + digit, e.g. 'V2'):
          version, email_mobile_status, reference_id, name, dob, gender, care_of, district,
          landmark, house, location, pincode, post_office, state, street, sub_district, vtc,
          mobile_last4
      Older cards (no version marker):
          email_mobile_status, reference_id, name, dob, gender, care_of, district, landmark,
          house, location, pincode, post_office, state, street, sub_district, vtc
          (then the photo, then optional 32-byte email/mobile hashes, then the signature)

  `reference_id` = last 4 digits of the Aadhaar number + a timestamp. The full number is
  NOT in the QR.

* OLD QR (before 2018): plain XML, no signature. It contains the full Aadhaar number,
  which we deliberately never keep - only the last 4 digits.

Only the fields we need are returned. The photo is never decoded or stored.
"""
import re
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import zxingcpp
from defusedxml import ElementTree as SafeET  # XML from a QR is untrusted input

from . import config

DELIM = 0xFF
SIGNATURE_LEN = 256

_BASE_FIELDS: List[str] = [
    "email_mobile_status", "reference_id", "name", "dob", "gender", "care_of", "district",
    "landmark", "house", "location", "pincode", "post_office", "state", "street",
    "sub_district", "vtc",
]
_VERSIONED_FIELDS: List[str] = ["version"] + _BASE_FIELDS + ["mobile_last4"]


@dataclass
class QrData:
    qr_type: str  # "secure" | "old"
    fields: Optional[Dict[str, str]] = None  # name, dob, gender, last4, pincode
    signed_data: Optional[bytes] = None  # secure only: bytes covered by the signature
    signature: Optional[bytes] = None  # secure only: 256 bytes
    version: Optional[str] = None
    note: Optional[str] = None  # set when the QR was found but could not be fully parsed
    page_index: int = 0
    rotation: int = 0  # 0/90/180/270: turn the page this many degrees counter-clockwise to read it upright


class QrDecodeError(Exception):
    """The payload looked like a Secure QR but could not be parsed. Message is user-safe."""


# --------------------------------------------------------------------------
# 1. Locate + read the QR code in an image
# --------------------------------------------------------------------------
def _variants(gray: np.ndarray):
    """Progressively heavier preprocessing, tried in order until one decodes."""
    yield "original", gray
    h, w = gray.shape
    for scale in (1.5, 2.0):
        if max(h, w) * scale <= 6000:
            yield f"upscale{scale}", cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    yield "clahe", clahe
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    yield "sharpen", cv2.addWeighted(gray, 1.8, blur, -0.8, 0)
    yield "otsu", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    yield "adaptive", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10)


def _tiles(gray: np.ndarray):
    """
    Zoomed-in crops of the image, for a QR that is small compared with the whole photo (a card
    photographed from far away, or a downsized screenshot). Decoders find the QR much more reliably
    when it fills a good part of the picture, so we cut overlapping windows and enlarge each one.
    """
    h, w = gray.shape
    for frac in (0.5, 0.34):
        wh, ww = int(h * frac), int(w * frac)
        step_y, step_x = max(wh // 2, 1), max(ww // 2, 1)
        for y in range(0, max(h - wh, 0) + 1, step_y):
            for x in range(0, max(w - ww, 0) + 1, step_x):
                crop = gray[y:y + wh, x:x + ww]
                scale = min(max(900.0 / max(crop.shape), 1.0), 8.0)
                if scale > 1.0:
                    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                yield crop


def _snap_rotation(angle: float) -> int:
    """Snap the QR's reported angle to 0/90/180/270. Small tilts are left for the OCR to cope with."""
    a = int(round(angle / 90.0)) * 90 % 360
    return a if abs(((angle - a) + 180) % 360 - 180) <= 20 else 0


def read_qr(png_bytes: bytes) -> Optional[Tuple[str, int]]:
    """
    Return (text, rotation) for the best QR code in the image, or None.

    `rotation` is how many degrees the page must be turned COUNTER-CLOCKWISE to be upright. A card
    photographed sideways reports 90 here. The printed text sits in the same direction as the QR, so
    the OCR step uses this to straighten the page first (checked against a real sideways card photo).
    """
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    for _name, variant in _variants(img):
        codes = zxingcpp.read_barcodes(variant, formats=zxingcpp.BarcodeFormat.QRCode)
        found = [c for c in codes if c.text]
        if found:
            # An Aadhaar page has one QR; if several, prefer the longest (the Secure QR).
            best = max(found, key=lambda c: len(c.text))
            return best.text, _snap_rotation(float(best.orientation))
    # Last resort: look at zoomed-in parts of the picture (a small QR in a big photo).
    for crop in _tiles(img):
        sharp = cv2.addWeighted(crop, 1.8, cv2.GaussianBlur(crop, (0, 0), 3), -0.8, 0)
        for candidate in (crop, sharp):
            found = [c for c in zxingcpp.read_barcodes(candidate, formats=zxingcpp.BarcodeFormat.QRCode) if c.text]
            if found:
                best = max(found, key=lambda c: len(c.text))
                return best.text, _snap_rotation(float(best.orientation))
    return None


def read_qr_text(png_bytes: bytes) -> Optional[str]:
    """Text of the best QR code found in the image, or None."""
    found = read_qr(png_bytes)
    return found[0] if found else None


# --------------------------------------------------------------------------
# 2. Parse the payload
# --------------------------------------------------------------------------
def classify(text: str) -> str:
    t = text.strip()
    if t.startswith("<?xml") or "<PrintLetterBarcodeData" in t:
        return "old"
    if t.isdigit() and len(t) >= 100:
        return "secure"
    return "unknown"


def _normalise_dob(raw: str) -> Optional[str]:
    raw = raw.strip()
    m = re.fullmatch(r"(\d{2})[-/.](\d{2})[-/.](\d{4})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.fullmatch(r"(\d{4})[-/.](\d{2})[-/.](\d{2})", raw)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if re.fullmatch(r"\d{4}", raw):  # year of birth only
        return raw
    return None


def _normalise_gender(raw: str) -> Optional[str]:
    r = raw.strip().lower()
    if r in ("m", "male"):
        return "M"
    if r in ("f", "female"):
        return "F"
    if r in ("t", "transgender", "other", "o"):
        return "T"
    return None


def _gunzip_limited(data: bytes) -> bytes:
    """Decompress gzip data but refuse to expand beyond the configured limit (zip-bomb guard)."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(data, config.MAX_DECOMPRESSED_QR_BYTES + 1)
    except zlib.error:
        raise QrDecodeError("The QR code data is corrupt.")
    if len(out) > config.MAX_DECOMPRESSED_QR_BYTES:
        raise QrDecodeError("The QR code data is too large.")
    return out


MAX_QR_DIGITS = 8000  # a QR code holds at most 7089 digits


def _digits_to_bytes(digits: str) -> bytes:
    """
    Decimal digit string -> big-endian bytes.

    NOT int(digits): Python refuses int<->str conversions above 4300 digits by default
    (a denial-of-service guard), and real Secure QR codes are often longer than that.
    We convert in 9-digit chunks instead, with our own length cap.
    """
    if not digits.isdigit() or len(digits) > MAX_QR_DIGITS:
        raise QrDecodeError("This is not a valid Aadhaar Secure QR code.")
    n = 0
    for i in range(0, len(digits), 9):
        chunk = digits[i:i + 9]
        n = n * (10 ** len(chunk)) + int(chunk)
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def parse_secure_qr(text: str) -> QrData:
    t = text.strip()
    raw = _digits_to_bytes(t)
    data = _gunzip_limited(raw)
    if len(data) <= SIGNATURE_LEN + 10:
        raise QrDecodeError("The QR code data is too short.")

    signature = data[-SIGNATURE_LEN:]
    signed = data[:-SIGNATURE_LEN]

    versioned = bool(re.match(rb"V\d", signed[:2]))
    names = _VERSIONED_FIELDS if versioned else _BASE_FIELDS
    version = signed[:2].decode("latin-1") if versioned else None

    # Split ONLY the detail fields. The photo that follows is binary and may contain 0xFF.
    parts: Dict[str, str] = {}
    pos = 0
    for name in names:
        end = signed.find(bytes([DELIM]), pos)
        if end == -1:
            return QrData("secure", None, signed, signature, version,
                          note="The QR code is a Secure QR but its details could not be read.")
        parts[name] = signed[pos:end].decode("latin-1")
        pos = end + 1

    ref = parts.get("reference_id", "")
    last4 = ref[:4] if re.match(r"\d{4}", ref) else None
    dob = _normalise_dob(parts.get("dob", ""))
    gender = _normalise_gender(parts.get("gender", ""))
    name_text = parts.get("name", "").strip()

    # Names are UTF-8 in the QR; latin-1 decoding above keeps the bytes lossless.
    try:
        name_text = name_text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    fields = {
        "name": name_text or None,
        "dob": dob,
        "gender": gender,
        "last4": last4,
        "pincode": parts.get("pincode", "").strip() or None,
    }
    note = None
    if not (fields["name"] and fields["dob"] and fields["last4"]):
        note = "The QR code was read, but some details inside it look unusual."
    return QrData("secure", fields, signed, signature, version, note)


def parse_old_qr(text: str) -> QrData:
    try:
        root = SafeET.fromstring(text.strip())
    except Exception:
        raise QrDecodeError("The QR code looks like an old-format QR but could not be read.")
    a = root.attrib
    uid = "".join((a.get("uid") or "").split())
    dob = _normalise_dob(a.get("dob") or a.get("yob") or "")
    # uid is 12 digits on old letters, or masked like "xxxxxxxx1234" on masked-Aadhaar prints.
    # Either way only the last 4 digits are kept.
    has_uid = bool(re.fullmatch(r"\d{12}|[xX*]{4,8}\d{4}", uid))
    pincode = (a.get("pc") or a.get("pincode") or "").strip()
    fields = {
        "name": (a.get("name") or "").strip() or None,
        "dob": dob,
        "gender": _normalise_gender(a.get("gender") or ""),
        "last4": uid[-4:] if has_uid else None,  # the full uid is dropped here
        "pincode": pincode if re.fullmatch(r"\d{6}", pincode) else None,
    }
    return QrData("old", fields, note="Old unsigned QR: it cannot be cryptographically verified.")


def decode_pages(pages: List[bytes]) -> Tuple[Optional[QrData], Optional[str]]:
    """
    Try each page image in turn. Returns (QrData, None) on success, (None, None) when
    no QR was found, or (None, message) when a QR was found but is not an Aadhaar QR.
    """
    unsupported: Optional[str] = None
    for i, page in enumerate(pages):
        found = read_qr(page)
        if found is None:
            continue
        text, rotation = found
        kind = classify(text)
        try:
            if kind == "secure":
                qr = parse_secure_qr(text)
            elif kind == "old":
                qr = parse_old_qr(text)
            else:
                unsupported = "A QR code was found, but it is not an Aadhaar QR code."
                continue
        except QrDecodeError as e:
            unsupported = str(e)
            continue
        qr.page_index = i
        qr.rotation = rotation
        return qr, None
    return None, unsupported
