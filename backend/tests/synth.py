"""
Test helpers: make a SYNTHETIC Aadhaar-style Secure QR and card image.

Everything here is invented. The QR is signed with a throwaway key we generate, never with a
UIDAI key, and the numbers are made up (the check digit is computed so the checksum passes).
The byte layout follows qr_decoder.py's description, so these tests prove the code is
internally consistent; they cannot prove it matches a real UIDAI card. Test with your own card
for that.
"""
import datetime as dt
import gzip
import io
import os
from typing import Dict, Optional

import segno
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from PIL import Image, ImageDraw, ImageFont

from verification import verhoeff

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def bytes_to_digits(data: bytes) -> str:
    """Big-endian bytes -> decimal digit string (str(int) refuses more than 4300 digits)."""
    n = int.from_bytes(data, "big")
    parts = []
    while n:
        n, r = divmod(n, 10 ** 9)
        parts.append(f"{r:09d}")
    return (str(int(parts[-1])) + "".join(reversed(parts[:-1]))) if parts else "0"


def make_aadhaar_number(prefix11: str = "78234567123") -> str:
    return prefix11 + verhoeff.generate_check_digit(prefix11)


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def write_cert(key: rsa.RSAPrivateKey, path, expired: bool = False) -> None:
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test UIDAI (throwaway)"),
        x509.NameAttribute(NameOID.COMMON_NAME, "test-secure-qr"),
    ])
    now = dt.datetime.now(dt.timezone.utc)
    start, end = (now - dt.timedelta(days=3000), now - dt.timedelta(days=1000)) if expired \
        else (now - dt.timedelta(days=1), now + dt.timedelta(days=3000))
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(start).not_valid_after(end).sign(key, hashes.SHA256()))
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.DER))


def make_secure_qr_text(
    key: rsa.RSAPrivateKey,
    *, name="Asha Mehta", dob="15-08-1990", gender="F", number: Optional[str] = None,
    pincode="411001", versioned=True, photo: Optional[bytes] = None,
) -> str:
    number = number or make_aadhaar_number()
    ref_id = number[-4:] + "20240315123045000"
    base = ["3", ref_id, name, dob, gender, "", "", "", "", "", pincode, "", "", "", "", ""]
    details = (["V2"] + base + ["9876"]) if versioned else base
    # Random photo bytes on purpose: they contain 0xFF, which must not confuse the parser.
    photo = photo if photo is not None else os.urandom(1400)
    signed = b"".join(d.encode("utf-8") + b"\xff" for d in details) + photo
    signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    return bytes_to_digits(gzip.compress(signed + signature))


def make_old_qr_xml(*, name="Asha Mehta", dob="15/08/1990", gender="F", number=None, pincode="411001") -> str:
    number = number or make_aadhaar_number()
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<PrintLetterBarcodeData uid="{number}" name="{name}" gender="{gender}" '
            f'dob="{dob}" pc="{pincode}" />')


def render_card(
    qr_text: str, *, name="Asha Mehta", dob="15/08/1990", gender="Female",
    number: Optional[str] = None, width=2400, height=1500, with_qr=True,
) -> bytes:
    number = number or make_aadhaar_number()
    img = Image.new("RGB", (width, height), (150, 150, 150))
    d = ImageDraw.Draw(img)
    d.rectangle([120, 100, width - 120, height - 100], fill=(250, 250, 248))
    big, mid, small = (ImageFont.truetype(FONT, s) for s in (74, 58, 44))
    d.text((200, 160), "Government of India", font=ImageFont.truetype(FONT_BOLD, 64), fill=(20, 20, 20))
    d.text((200, 260), "Unique Identification Authority of India", font=small, fill=(60, 60, 60))
    d.text((200, 520), name, font=big, fill=(10, 10, 10))
    d.text((200, 640), f"DOB: {dob}", font=big, fill=(10, 10, 10))
    d.text((200, 760), gender, font=big, fill=(10, 10, 10))
    pretty = f"{number[:4]} {number[4:8]} {number[8:]}"
    d.text((200, 980), pretty, font=ImageFont.truetype(FONT_BOLD, 96), fill=(10, 10, 10))
    d.text((200, 1180), "VID : 9123 4567 8901 2345", font=mid, fill=(40, 40, 40))
    if with_qr:
        buf = io.BytesIO()
        segno.make(qr_text, mode=("numeric" if qr_text.isdigit() else None), error="L", micro=False).save(
            buf, kind="png", scale=5, border=2, dark="black", light="white")
        qr_img = Image.open(buf).convert("RGB")
        img.paste(qr_img, (width - 120 - 100 - qr_img.width, 300))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
