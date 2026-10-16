"""
Compare what is PRINTED on the card (read by OCR) with what is in the signed QR.

Each field gets one of:
  match        values agree
  partial      close but not identical, or the OCR was not confident enough to call it a mismatch
  mismatch     values disagree and the OCR was confident about what it read
  not_checked  one side is missing (e.g. the card does not print a pincode)

A value the OCR failed to read is "not_checked", never "mismatch": a blurry digit must not
make a genuine card look forged.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from rapidfuzz import fuzz

from . import config, verhoeff
from .ocr import CardFields

CRITICAL_KEYS = ("Name", "DOB", "Gender", "Aadhaar (last 4)", "Aadhaar checksum")
_GENDER_LABEL = {"M": "Male", "F": "Female", "T": "Transgender"}


@dataclass
class FieldResult:
    key: str
    printed: Optional[str]
    qr: Optional[str]
    status: str
    similarity: Optional[int] = None

    @property
    def critical(self) -> bool:
        return self.key in CRITICAL_KEYS


@dataclass
class CrossMatch:
    fields: List[FieldResult] = field(default_factory=list)
    readable: bool = True  # False when the OCR text is too poor to use
    avg_conf: float = 0.0
    number_masked: Optional[str] = None
    verhoeff_valid: Optional[bool] = None

    @property
    def mismatch_count(self) -> int:
        return sum(1 for f in self.fields if f.critical and f.status == "mismatch")

    def count(self, status: str, critical_only: bool = True) -> int:
        return sum(1 for f in self.fields if f.status == status and (f.critical or not critical_only))


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _mask(last4: Optional[str]) -> Optional[str]:
    return f"XXXX XXXX {last4}" if last4 else None


def _disagree(conf: float) -> str:
    """Status for a clear disagreement: a mismatch only if the OCR was confident."""
    return "mismatch" if conf >= config.OCR_FIELD_MISMATCH_MIN_CONFIDENCE else "partial"


def compare(card: CardFields, qr: dict) -> CrossMatch:
    res = CrossMatch(avg_conf=card.avg_conf)
    res.readable = card.line_count > 0 and card.avg_conf >= config.OCR_MIN_AVG_CONFIDENCE
    res.number_masked = _mask(card.last4)

    # --- Name ---
    if card.name and qr.get("name"):
        a, b = _norm_name(card.name), _norm_name(qr["name"])
        # OCR often drops the spaces between words ("TanayAtmaramBandekar"), so also compare without spaces.
        sim = int(round(max(fuzz.token_sort_ratio(a, b), fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")))))
        if sim >= config.NAME_MATCH_MIN_SIMILARITY:
            status = "match"
        elif sim >= config.NAME_PARTIAL_MIN_SIMILARITY:
            status = "partial"
        else:
            status = _disagree(card.name_conf)
        res.fields.append(FieldResult("Name", card.name, qr["name"], status, sim))
    else:
        res.fields.append(FieldResult("Name", card.name, qr.get("name"), "not_checked"))

    # --- Date of birth (a card that prints only the year is compared by year) ---
    qdob = qr.get("dob")
    if card.dob and qdob:
        year_only = len(card.dob) == 4 or len(qdob) == 4
        a = card.dob[-4:]
        b = qdob[-4:]
        same = (a == b) if year_only else (card.dob == qdob)
        res.fields.append(FieldResult("DOB", card.dob, qdob, "match" if same else _disagree(card.dob_conf)))
    else:
        res.fields.append(FieldResult("DOB", card.dob, qdob, "not_checked"))

    # --- Gender ---
    qg = qr.get("gender")
    if card.gender and qg:
        res.fields.append(FieldResult(
            "Gender", _GENDER_LABEL.get(card.gender), _GENDER_LABEL.get(qg),
            "match" if card.gender == qg else _disagree(card.gender_conf)))
    else:
        res.fields.append(FieldResult("Gender", _GENDER_LABEL.get(card.gender or ""), _GENDER_LABEL.get(qg or ""), "not_checked"))

    # --- Aadhaar last 4 digits ---
    if card.last4 and qr.get("last4"):
        same = card.last4 == qr["last4"]
        res.fields.append(FieldResult("Aadhaar (last 4)", _mask(card.last4), _mask(qr["last4"]),
                                      "match" if same else _disagree(card.number_conf)))
    else:
        res.fields.append(FieldResult("Aadhaar (last 4)", _mask(card.last4), _mask(qr.get("last4")), "not_checked"))

    # --- Aadhaar checksum (Verhoeff) on the full printed number ---
    if card.number and not card.number_masked:
        ok = verhoeff.is_valid_aadhaar_number(card.number)
        res.verhoeff_valid = ok
        res.fields.append(FieldResult("Aadhaar checksum", _mask(card.last4), None,
                                      "match" if ok else _disagree(card.number_conf)))
    else:
        res.fields.append(FieldResult("Aadhaar checksum", _mask(card.last4), None, "not_checked"))

    # --- Pincode (informational: addresses are hard to OCR, so never a hard mismatch) ---
    # Addresses print the pincode at the end, usually without a "PIN" label, so we look for the
    # QR's pincode among all 6-digit numbers on the page.
    qpin = qr.get("pincode")
    seen_pins = list(card.six_digit_tokens) + ([card.pincode] if card.pincode else [])
    if qpin and qpin in seen_pins:
        res.fields.append(FieldResult("Pincode", qpin, qpin, "match"))
    elif qpin and seen_pins:
        res.fields.append(FieldResult("Pincode", seen_pins[-1], qpin, "partial"))
    else:
        res.fields.append(FieldResult("Pincode", card.pincode, qpin, "not_checked"))
    return res
