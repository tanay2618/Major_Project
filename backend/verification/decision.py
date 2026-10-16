"""
Final decision. A pure function: easy to test, no I/O.

Outcomes:
  verified       signature valid, enough fields match, nothing disagrees
  tampered       genuine-looking signature but the printed card disagrees with it
  forged         the digital signature is invalid
  likely_authentic  old unsigned QR, but name, Aadhaar last 4 and pincode (or DOB/gender/checksum) match it
  low_quality    the image or its text could not be read well enough to judge
  manual_review  cannot be decided automatically (old unsigned QR, missing certificate, ...)

Order matters: the first rule that applies wins.
"""
from dataclasses import dataclass
from typing import List, Optional

from . import config
from .crossmatch import CrossMatch
from .qr_decoder import QrData
from .signature import SignatureOutcome


@dataclass
class Decision:
    outcome: str
    risk_score: Optional[int]
    reasons: List[str]


def decide(
    quality_passed: Optional[bool],
    qr: Optional[QrData],
    sig: Optional[SignatureOutcome],
    cross: Optional[CrossMatch],
) -> Decision:
    # 1. image quality
    if quality_passed is False:
        return Decision("low_quality", None, ["The image quality was too low to check."])

    # 2. no QR at all
    if qr is None:
        return Decision("manual_review", 45, ["No readable Aadhaar QR code was found on the document."])

    # 3. unreadable printed text
    if cross is not None and not cross.readable:
        return Decision("low_quality", None,
                        ["The printed text on the card could not be read clearly. Please upload a sharper photo."])

    mismatches = [f for f in (cross.fields if cross else []) if f.critical and f.status == "mismatch"]
    partials = [f for f in (cross.fields if cross else []) if f.critical and f.status == "partial"]
    matched = cross.count("match") if cross else 0

    # 4. forged: a Secure QR whose signature fails
    if qr.qr_type == "secure" and sig is not None and sig.valid is False:
        return Decision("forged", 95, [
            "The digital signature on the QR code is not valid.",
            "A genuine UIDAI QR code cannot be edited or recreated without breaking its signature.",
        ])

    # 5. old unsigned QR: cannot be verified, but a clear disagreement is still evidence
    if qr.qr_type == "old":
        if mismatches:
            return Decision("tampered", min(80 + 3 * len(mismatches), 90), _mismatch_reasons(mismatches) + [
                "This is an old unsigned QR, so it is a weaker check than a Secure QR."])
        status = {f.key: f.status for f in (cross.fields if cross else [])}
        core_ok = all(status.get(k) == "match" for k in config.CORE_FIELDS)
        support = [k for k in config.SUPPORTING_FIELDS if status.get(k) == "match"]
        if core_ok and (("Pincode" in support) or len(support) >= config.MIN_SUPPORTING_MATCHES):
            return Decision("likely_authentic", 15, [
                "The name and the last 4 digits of the Aadhaar number match the QR code, along with: "
                + ", ".join(k.lower() if k != "DOB" else "DOB" for k in support) + ".",
                "The QR code is the old unsigned kind, so this is a strong sign but not cryptographic proof.",
            ])
        return Decision("manual_review", 45, [
            "This document has an old QR code with no digital signature, so it cannot be verified automatically."])

    # 6. Secure QR whose signature could not be checked (no certificate installed)
    if sig is None or sig.valid is None:
        return Decision("manual_review", 45, [
            "The digital signature could not be checked on this server.",
            *( [sig.reason] if sig else [] ),
        ])

    # 7. signature is valid: do the printed details agree?
    if qr.fields is None or cross is None:
        return Decision("manual_review", 45, ["The signature is valid, but the QR details could not be compared."])

    if mismatches:
        return Decision("tampered", min(80 + 3 * len(mismatches), 90), _mismatch_reasons(mismatches) + [
            "The QR signature is valid, so the card was probably altered after it was issued."])

    if partials:
        return Decision("manual_review", 40, [
            "Some printed details only partly match the signed QR data: "
            + ", ".join(f.key for f in partials) + ".",
            "A person should confirm them."])

    if matched < config.MIN_MATCHED_FIELDS_FOR_VERIFIED:
        return Decision("manual_review", 40, [
            "The signature is valid, but too few printed details could be read to compare them with it.",
            "Upload the side of the card that shows your name, date of birth and number."])

    return Decision("verified", 8, [
        "The digital signature is valid and was issued by UIDAI.",
        f"{matched} printed details match the signed QR data.",
    ])


def _mismatch_reasons(mismatches) -> List[str]:
    return [f"The printed {f.key} does not match the signed QR data." for f in mismatches]
