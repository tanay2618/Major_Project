"""
Read the printed text on the card (PaddleOCR) and pull out name, date of birth, gender,
Aadhaar number and pincode.

* run_ocr()          image bytes -> list of OcrLine (text, confidence, position)
* parse_card_text()  OcrLine list -> CardFields  (pure function, no OCR needed, easy to test)

Engines (OCR_ENGINE in .env):
  paddle  PaddleOCR (default). Needs `pip install paddleocr paddlepaddle`; the first run
          downloads the recognition models, so the server needs internet once.
  rapid   RapidOCR: the same PaddleOCR models run through ONNX. Handy for tests and as a
          fallback if PaddlePaddle will not install on your Python version.

Anything that cannot be read stays None. We never guess a value.
"""
import os
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import cv2
import numpy as np

from . import config
log = logging.getLogger(__name__)

# ---------------------------------------------------------------- OCR engines
_engine = None
_engine_kind = None
_engine_lock = threading.Lock()  # inference is not guaranteed thread-safe
_infer_lock = threading.Lock()


@dataclass
class OcrLine:
    text: str
    conf: float  # 0..1
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


def _load_rapid():
    from rapidocr_onnxruntime import RapidOCR

    return "rapid", RapidOCR()


def _load_paddle():
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")  # oneDNN crashes on many Windows/CPU setups
    import paddleocr
    from paddleocr import PaddleOCR

    major = int(str(getattr(paddleocr, "__version__", "3")).split(".")[0])
    if major >= 3:
        kwargs = dict(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False,
                      use_textline_orientation=False)
        try:
            return "paddle3", PaddleOCR(enable_mkldnn=False, **kwargs)
        except (TypeError, ValueError):  # this version does not know the option
            return "paddle3", PaddleOCR(**kwargs)
    return "paddle2", PaddleOCR(lang="en", use_angle_cls=False, show_log=False)


def _load_engine():
    """Load the configured engine. If PaddleOCR cannot start, fall back to RapidOCR (same models)."""
    global _engine, _engine_kind
    with _engine_lock:
        if _engine is not None:
            return _engine_kind, _engine
        if config.OCR_ENGINE == "rapid":
            _engine_kind, _engine = _load_rapid()
        else:
            try:
                _engine_kind, _engine = _load_paddle()
            except Exception:
                log.exception("PaddleOCR could not start; falling back to RapidOCR")
                _engine_kind, _engine = _load_rapid()
        return _engine_kind, _engine


def _switch_to_rapid():
    global _engine, _engine_kind
    with _engine_lock:
        _engine_kind, _engine = _load_rapid()


def _box_to_rect(box) -> tuple:
    pts = np.array(box, dtype=float).reshape(-1, 2)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def rotate_upright(png_bytes: bytes, rotation_ccw: int) -> bytes:
    """Turn a page counter-clockwise by 0/90/180/270 degrees (the angle the QR decoder reported)."""
    ops = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_CLOCKWISE}
    if rotation_ccw not in ops:
        return png_bytes
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return png_bytes
    ok, buf = cv2.imencode(".png", cv2.rotate(img, ops[rotation_ccw]))
    return buf.tobytes() if ok else png_bytes


def run_ocr(png_bytes: bytes) -> List[OcrLine]:
    """Blocking and CPU heavy - call through run_in_threadpool."""
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side > config.OCR_MAX_LONG_SIDE_PX:
        s = config.OCR_MAX_LONG_SIDE_PX / long_side
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)

    kind, eng = _load_engine()
    try:
        return _infer(kind, eng, img)
    except Exception:
        if kind == "rapid":
            raise
        log.exception("%s failed while reading the card; retrying with RapidOCR", kind)
        _switch_to_rapid()
        kind, eng = _load_engine()
        return _infer(kind, eng, img)


def _infer(kind, eng, img) -> List[OcrLine]:
    lines: List[OcrLine] = []
    with _infer_lock:
        if kind == "rapid":
            result, _ = eng(img)
            for box, text, score in (result or []):
                x0, y0, x1, y1 = _box_to_rect(box)
                lines.append(OcrLine(str(text), float(score), x0, y0, x1, y1))
        elif kind == "paddle3":
            for res in eng.predict(img):
                data = res if isinstance(res, dict) else res.json.get("res", {})
                texts = data.get("rec_texts", [])
                scores = data.get("rec_scores", [])
                polys = data.get("rec_polys", data.get("dt_polys", []))
                for text, score, poly in zip(texts, scores, polys):
                    x0, y0, x1, y1 = _box_to_rect(poly)
                    lines.append(OcrLine(str(text), float(score), x0, y0, x1, y1))
        else:  # paddle2
            result = eng.ocr(img, cls=False)
            for item in (result[0] if result and result[0] else []):
                box, (text, score) = item
                x0, y0, x1, y1 = _box_to_rect(box)
                lines.append(OcrLine(str(text), float(score), x0, y0, x1, y1))
    return lines


# --------------------------------------------------------------- field parsing
@dataclass
class CardFields:
    name: Optional[str] = None
    name_conf: float = 0.0
    dob: Optional[str] = None  # "DD-MM-YYYY", or "YYYY" when only the year is printed
    dob_conf: float = 0.0
    gender: Optional[str] = None  # "M" | "F" | "T"
    gender_conf: float = 0.0
    number: Optional[str] = None  # full 12 digits, no spaces (never leaves the server)
    number_masked: bool = False  # card prints XXXX XXXX 1234
    last4: Optional[str] = None
    number_conf: float = 0.0
    pincode: Optional[str] = None
    pincode_conf: float = 0.0
    # Every standalone 6-digit number on the page. Addresses end with the pincode but often
    # without a "PIN" label, so the cross-match looks the QR's pincode up in this list.
    six_digit_tokens: List[str] = field(default_factory=list)
    avg_conf: float = 0.0
    line_count: int = 0


_HEADER_WORDS = {
    "government", "india", "aadhaar", "aadhar", "uidai", "authority", "unique", "identification",
    "address", "dob", "birth", "male", "female", "transgender", "vid", "help", "www", "gov", "enrolment",
    "enrollment", "download", "issue", "issued", "date", "year", "of", "mera", "pehchaan", "to",
    "virtual", "id", "no", "number",
}

_RE_NUMBER = re.compile(r"(?<!\d)(?<!\d )(\d{4})\s?(\d{4})\s?(\d{4})(?!\s?\d)")
_RE_MASKED = re.compile(r"(?:[Xx*•]{4}[\s-]*){2}(\d{4})(?!\d)")
_RE_DOB_LABELLED = re.compile(
    r"(?:DOB|D\.?O\.?B\.?|Date\s*of\s*Birth|Birth)\s*[:\-]?\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})", re.I
)
_RE_DATE = re.compile(r"(?<!\d)(\d{2})\s*[/\-.]\s*(\d{2})\s*[/\-.]\s*(\d{4})(?!\d)")
_RE_YOB = re.compile(r"(?:Year\s*of\s*Birth|YOB)\s*[:\-]?\s*(\d{4})", re.I)
_RE_GENDER = re.compile(r"\b(female|male|transgender)\b", re.I)
_RE_PIN = re.compile(r"PIN\s*(?:Code)?\s*[:\-]?\s*(\d{6})(?!\d)", re.I)


def _valid_date(d: int, m: int, y: int) -> bool:
    try:
        date(y, m, d)
    except ValueError:
        return False
    return 1900 <= y <= date.today().year


def _clean_name(text: str) -> Optional[str]:
    t = re.sub(r"[^A-Za-z.'\-\s]", " ", text)
    t = re.sub(r"\s+", " ", t).strip(" .-'")
    return t or None


# Older cards print "Father: ..." / "S/O: ..." between the name and the date of birth.
_RE_RELATION = re.compile(r"^\W*(father|mother|husband|wife|guardian|[sdwc]\s*/\s*o)\b", re.I)


def _looks_like_name(text: str) -> bool:
    if _RE_RELATION.match(text) or re.match(r"^\W*(father|mother|husband)", text, re.I):
        return False
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return False
    if any(c.isdigit() for c in text):
        return False
    if sum(c.isascii() for c in letters) / len(letters) < 0.9:
        return False
    cleaned = _clean_name(text)
    if not cleaned:
        return False
    words = cleaned.lower().replace(".", " ").split()
    if not words or len(words) > 6:
        return False
    if any(w in _HEADER_WORDS for w in words):
        return False
    return True


def _merge_rows(ordered: List[OcrLine]) -> List[OcrLine]:
    """
    Join OCR pieces that sit on the same text row into one line, left to right.

    Aadhaar numbers are printed in three groups with wide gaps, and OCR often returns
    "7823", "4567", "1239" as three separate pieces. Only rows with 2+ pieces are returned.
    """
    if not ordered:
        return []
    heights = sorted(max(l.y1 - l.y0, 1.0) for l in ordered)
    tol = 0.5 * heights[len(heights) // 2]
    rows: List[List[OcrLine]] = []
    for l in sorted(ordered, key=lambda l: l.yc):
        if rows and abs(l.yc - sum(x.yc for x in rows[-1]) / len(rows[-1])) <= tol:
            rows[-1].append(l)
        else:
            rows.append([l])
    merged = []
    for row in rows:
        if len(row) < 2:
            continue
        row.sort(key=lambda l: l.x0)
        merged.append(OcrLine(
            " ".join(l.text for l in row),
            sum(l.conf for l in row) / len(row),
            min(l.x0 for l in row), min(l.y0 for l in row), max(l.x1 for l in row), max(l.y1 for l in row)))
    return merged


def parse_card_text(lines: List[OcrLine]) -> CardFields:
    out = CardFields(line_count=len(lines))
    if not lines:
        return out

    ordered = sorted(lines, key=lambda l: (round(l.yc / 12), l.x0))
    total_chars = sum(max(len(l.text), 1) for l in ordered)
    out.avg_conf = sum(l.conf * max(len(l.text), 1) for l in ordered) / total_chars

    dob_idx = gender_idx = number_idx = None

    seen = set()
    for l in ordered:
        for tok in re.findall(r"(?<![\d])\d{6}(?![\d])", l.text):
            if tok not in seen:
                seen.add(tok)
                out.six_digit_tokens.append(tok)

    # Aadhaar number: look at single lines AND at same-row pieces joined together.
    number_cands = [(i, l) for i, l in enumerate(ordered)]
    row_lines = _merge_rows(ordered)
    number_cands += [(None, l) for l in row_lines]
    for i, l in number_cands:
        if re.search(r"\bVID\b", l.text, re.I):
            continue
        m = _RE_NUMBER.search(l.text)
        if m and l.conf >= out.number_conf:
            out.number = "".join(m.groups())
            out.last4, out.number_masked, out.number_conf = m.group(3), False, l.conf
            number_idx = i if i is not None else number_idx
        elif out.number is None:
            mm = _RE_MASKED.search(l.text)
            if mm and l.conf >= out.number_conf:
                out.last4, out.number_masked, out.number_conf = mm.group(1), True, l.conf
                number_idx = i if i is not None else number_idx

    for i, l in enumerate(ordered):
        t = l.text

        # --- date of birth (labelled date wins over a bare date) ---
        if out.dob is None or (out.dob_conf < l.conf and _RE_DOB_LABELLED.search(t)):
            m = _RE_DOB_LABELLED.search(t)
            if m and _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3))):
                out.dob = f"{int(m.group(1)):02d}-{int(m.group(2)):02d}-{m.group(3)}"
                out.dob_conf, dob_idx = l.conf, i
            elif out.dob is None:
                y = _RE_YOB.search(t)
                if y and 1900 <= int(y.group(1)) <= date.today().year:
                    out.dob, out.dob_conf, dob_idx = y.group(1), l.conf, i
                else:
                    m = _RE_DATE.search(t)
                    if m and not re.search(r"issue|download|enrol|generated|print", t, re.I) \
                            and _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3))):
                        out.dob = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                        out.dob_conf, dob_idx = l.conf, i

        # --- gender ---
        if out.gender is None:
            g = _RE_GENDER.search(t)
            if g:
                out.gender = {"male": "M", "female": "F", "transgender": "T"}[g.group(1).lower()]
                out.gender_conf, gender_idx = l.conf, i

        # --- pincode (only when the card labels it) ---
        if out.pincode is None:
            p = _RE_PIN.search(t)
            if p:
                out.pincode, out.pincode_conf = p.group(1), l.conf

    # --- name: nearest English-looking line ABOVE the date of birth line ---
    # The anchor must be the DOB or gender line. Anchoring on the number alone made the address
    # side of a card (which prints no name) produce a bogus name from an address line.
    anchor = next((x for x in (dob_idx, gender_idx) if x is not None), None)
    if anchor is not None:
        for j in range(anchor - 1, max(anchor - 4, -1), -1):
            if _looks_like_name(ordered[j].text):
                out.name = _clean_name(ordered[j].text)
                out.name_conf = ordered[j].conf
                break
    return out
