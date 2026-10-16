"""
UIDAI signature verification for Secure QR codes.

The 256-byte signature at the end of the QR is checked against UIDAI's public
certificates with RSA PKCS#1 v1.5 + SHA-256 (the "SHA256withRSA" scheme UIDAI uses).
CONFIRM this against the current UIDAI specification and a real card.

Security rules:
* Keys come ONLY from the certificate files you placed in the certs folder - never from
  anything inside the uploaded document.
* UIDAI rotates keys, so every certificate in the folder is tried. Cards printed years
  ago are signed with older keys, so an EXPIRED certificate is still accepted for the
  signature (the signature was valid when it was made); we just say so in the message.
"""
import datetime as dt
import logging
from dataclasses import dataclass
from typing import List, Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from . import config

log = logging.getLogger("verification")

_CERT_SUFFIXES = {".cer", ".crt", ".pem", ".der"}


@dataclass
class SignatureOutcome:
    valid: Optional[bool]  # True / False / None (cannot be checked)
    issuer: Optional[str]
    reason: str


@dataclass
class _LoadedCert:
    filename: str
    public_key: rsa.RSAPublicKey
    subject: str
    not_after: dt.datetime


def _subject_text(cert: x509.Certificate) -> str:
    parts = []
    for oid in (x509.NameOID.ORGANIZATION_NAME, x509.NameOID.COMMON_NAME):
        attrs = cert.subject.get_attributes_for_oid(oid)
        if attrs:
            parts.append(str(attrs[0].value))
    return ", ".join(parts) or "UIDAI"


def load_certificates() -> List[_LoadedCert]:
    certs: List[_LoadedCert] = []
    folder = config.UIDAI_CERT_DIR
    if not folder.is_dir():
        return certs
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in _CERT_SUFFIXES:
            continue
        data = path.read_bytes()
        cert = None
        for loader in (x509.load_der_x509_certificate, x509.load_pem_x509_certificate):
            try:
                cert = loader(data)
                break
            except ValueError:
                continue
        if cert is None:
            log.warning("could not read certificate file %s", path.name)
            continue
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            log.warning("certificate %s does not hold an RSA key", path.name)
            continue
        certs.append(_LoadedCert(path.name, key, _subject_text(cert), cert.not_valid_after_utc))
    return certs


def verify_secure_qr(signed_data: bytes, signature: bytes) -> SignatureOutcome:
    certs = load_certificates()
    if not certs:
        return SignatureOutcome(
            None, None,
            "UIDAI certificate is not installed on the server, so the signature cannot be checked. "
            "Add the UIDAI .cer files to backend/verification/certs/ (see the README there).",
        )

    for c in certs:
        try:
            c.public_key.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            continue
        except Exception:  # wrong signature length for this key, etc.
            continue
        expired = c.not_after < dt.datetime.now(dt.timezone.utc)
        note = (
            f" It was signed with an older UIDAI key (certificate expired {c.not_after:%d %b %Y}); "
            "this is normal for cards printed some years ago."
            if expired else ""
        )
        return SignatureOutcome(
            True, f"UIDAI ({c.subject})",
            f"RSA signature verified against the UIDAI certificate '{c.filename}'.{note}",
        )

    return SignatureOutcome(
        False, None,
        "The digital signature does not match any installed UIDAI certificate. "
        "The QR data may have been altered or created by someone other than UIDAI.",
    )
