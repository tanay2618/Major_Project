"""
End to end through the HTTP API with a rendered card image, a real QR code, real zxing decoding
and real OCR (RapidOCR = PaddleOCR models). Only the UIDAI key is a throwaway.
"""
import io
import types

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("rapidocr_onnxruntime")

import auth
from verification import config
from verification.router import router
from verification.session_store import store

from . import synth

NUMBER = synth.make_aadhaar_number()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fresh app, an installed 'UIDAI' certificate we control, and the matching private key."""
    monkeypatch.setattr(config, "UIDAI_CERT_DIR", tmp_path)
    # Rendered test fonts give lower OCR confidence than clean real prints; relax this one
    # threshold so the tests exercise the matching logic, not the OCR engine's confidence.
    monkeypatch.setattr(config, "OCR_FIELD_MISMATCH_MIN_CONFIDENCE", 0.6)
    key = synth.new_key()
    synth.write_cert(key, tmp_path / "uidai_test.cer")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.get_current_user] = lambda: types.SimpleNamespace(id=1, is_active=True)
    store._sessions.clear()
    store._upload_times.clear()
    return types.SimpleNamespace(client=TestClient(app), key=key, certdir=tmp_path)


def run(client, data: bytes, filename="card.png"):
    """Run every step; return (qr, signature, crossmatch) JSON bodies."""
    r = client.post("/api/verify/upload", files={"file": (filename, data)}, data={"consent": "true", "docType": "aadhaar"})
    assert r.status_code == 201, r.text
    sid = r.json()["sessionId"]
    q = client.post(f"/api/verify/{sid}/quality")
    assert q.status_code == 200
    qr = client.post(f"/api/verify/{sid}/qr").json()
    sig = client.post(f"/api/verify/{sid}/signature").json()
    cm = client.post(f"/api/verify/{sid}/crossmatch").json()
    client.delete(f"/api/verify/{sid}")
    return q.json(), qr, sig, cm


def card(key, *, printed=None, qr=None, with_qr=True, **render):
    qr_kw = dict(name="Asha Mehta", dob="15-08-1990", gender="F", number=NUMBER)
    qr_kw.update(qr or {})
    text = synth.make_secure_qr_text(key, **qr_kw)
    kw = dict(name="Asha Mehta", dob="15/08/1990", gender="Female", number=NUMBER, with_qr=with_qr)
    kw.update(printed or {})
    kw.update(render)
    return synth.render_card(text, **kw)


def status(cm, key):
    return next(f["status"] for f in cm["fields"] if f["key"] == key)


# ------------------------------------------------------------------ scenarios
def test_genuine_card_is_verified(env):
    q, qr, sig, cm = run(env.client, card(env.key))
    assert q["passed"], q
    assert qr["qrFound"] and qr["qrType"] == "secure"
    assert qr["fields"] == {"name": "Asha Mehta", "dob": "15-08-1990", "gender": "F",
                            "last4": NUMBER[-4:], "pincode": "411001"}
    assert sig["signatureValid"] is True
    assert cm["outcome"] == "verified", cm
    assert [status(cm, k) for k in ("Name", "DOB", "Gender", "Aadhaar (last 4)", "Aadhaar checksum")] == ["match"] * 5
    assert cm["ocr"]["verhoeffValid"] is True and cm["ocr"]["numberMasked"] == f"XXXX XXXX {NUMBER[-4:]}"
    assert cm["mismatchCount"] == 0 and cm["riskScore"] < 40


def test_response_never_contains_full_number_photo_or_signed_bytes(env):
    _, qr, sig, cm = run(env.client, card(env.key))
    blob = str(qr) + str(sig) + str(cm)
    assert NUMBER not in blob and "".join([NUMBER[:4], " ", NUMBER[4:8]]) not in blob
    assert "signedData" not in blob and "photo" not in blob.lower()


def test_edited_name_on_printed_card_is_tampered(env):
    _, _, sig, cm = run(env.client, card(env.key, printed={"name": "Rohan Verma"}))
    assert sig["signatureValid"] is True                  # the QR itself is untouched
    assert status(cm, "Name") == "mismatch"
    assert cm["outcome"] == "tampered" and cm["riskScore"] >= 80


def test_edited_birth_date_is_tampered(env):
    _, _, _, cm = run(env.client, card(env.key, printed={"dob": "15/08/1985"}))
    assert status(cm, "DOB") == "mismatch" and cm["outcome"] == "tampered"


def test_invented_number_with_bad_checksum_is_tampered(env):
    bad = NUMBER[:-1] + str((int(NUMBER[-1]) + 1) % 10)
    _, _, _, cm = run(env.client, card(env.key, printed={"number": bad}))
    assert cm["ocr"]["verhoeffValid"] is False and cm["outcome"] == "tampered"


def test_qr_signed_by_someone_else_is_forged(env):
    attacker = synth.new_key()                            # signs a perfectly consistent fake card
    _, qr, sig, cm = run(env.client, card(attacker))
    assert qr["qrFound"] and sig["signatureValid"] is False
    assert cm["outcome"] == "forged" and cm["riskScore"] >= 90


def test_old_unsigned_qr_with_matching_details_is_likely_authentic_not_verified(env):
    xml = synth.make_old_qr_xml(number=NUMBER)
    data = synth.render_card(xml, number=NUMBER)
    _, qr, sig, cm = run(env.client, data)
    assert qr["qrType"] == "old" and sig["signatureValid"] is None
    assert cm["outcome"] == "likely_authentic"  # never "verified": there is no signature


def test_no_certificate_installed_goes_to_manual_review(env):
    for f in env.certdir.iterdir():
        f.unlink()
    _, _, sig, cm = run(env.client, card(env.key))
    assert sig["signatureValid"] is None and "certs" in sig["reason"]
    assert cm["outcome"] == "manual_review"


def test_card_without_qr(env):
    _, qr, sig, cm = run(env.client, card(env.key, with_qr=False))
    assert qr["qrFound"] is False and qr["fields"] is None
    assert sig["signatureValid"] is None


def test_non_aadhaar_qr_is_reported(env):
    import segno
    buf = io.BytesIO()
    segno.make("https://example.com/menu", error="m").save(buf, kind="png", scale=12, border=4)
    from PIL import Image
    img = Image.new("RGB", (1600, 1000), (235, 235, 235))
    img.paste(Image.open(buf).convert("RGB"), (100, 100))
    out = io.BytesIO(); img.save(out, format="PNG")
    r = env.client.post("/api/verify/upload", files={"file": ("x.png", out.getvalue())}, data={"consent": "true"})
    sid = r.json()["sessionId"]
    qr = env.client.post(f"/api/verify/{sid}/qr").json()
    assert qr["qrFound"] is False and "not an Aadhaar" in qr["note"]


# ----------------------------------------------------------- real-world noise
def test_photo_taken_at_slight_angle_and_blur_still_decodes(env):
    data = card(env.key)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 4.0, 0.9)           # 4 degree tilt, a bit smaller
    img = cv2.warpAffine(img, m, (w, h), borderValue=(110, 110, 110))
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    noise = np.random.default_rng(0).normal(0, 6, img.shape)
    img = np.clip(img + noise, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    _, qr, sig, cm = run(env.client, buf.tobytes(), "photo.jpg")
    assert qr["qrFound"] and sig["signatureValid"] is True
    assert cm["outcome"] in ("verified", "manual_review")           # never tampered/forged on a genuine card
    assert cm["mismatchCount"] == 0


def test_pdf_of_a_genuine_card_works(env):
    png_bytes = card(env.key)
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
    png_bytes = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()   # real PDFs embed JPEGs
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(20, 100, 575, 450), stream=png_bytes)
    q, qr, sig, cm = run(env.client, doc.tobytes(), "aadhaar.pdf")
    assert q["passed"], q
    assert qr["qrFound"] and sig["signatureValid"] is True
    assert cm["outcome"] in ("verified", "manual_review") and cm["mismatchCount"] == 0


# ------------------------------------------------------------- step ordering
def test_steps_must_run_in_order(env):
    sid = env.client.post("/api/verify/upload", files={"file": ("c.png", card(env.key))},
                          data={"consent": "true"}).json()["sessionId"]
    assert env.client.post(f"/api/verify/{sid}/signature").status_code == 409
    assert env.client.post(f"/api/verify/{sid}/crossmatch").status_code == 409
    env.client.post(f"/api/verify/{sid}/qr")
    assert env.client.post(f"/api/verify/{sid}/crossmatch").status_code == 409   # signature still missing
