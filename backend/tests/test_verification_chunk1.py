import io
import types

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
from verification import config, quality
from verification.router import router
from verification.session_store import store


# ---------- helpers: synthetic "card" images --------------------------------
def make_card(width=1600, height=1100) -> np.ndarray:
    """A white card with lots of text on a dark table - sharp, well lit."""
    img = np.full((height, width, 3), 60, np.uint8)
    cv2.rectangle(img, (150, 120), (width - 150, height - 120), (245, 245, 245), -1)
    rng = np.random.default_rng(1)
    for i in range(14):
        text = "".join(rng.choice(list("ABCDEFGHJKLMNPRSTUVWXYZ0123456789 "), 28))
        cv2.putText(img, text, (190, 200 + i * 55), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def jpg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    fake_user = types.SimpleNamespace(id=1, is_active=True)
    app.dependency_overrides[auth.get_current_user] = lambda: fake_user
    store._sessions.clear()
    store._upload_times.clear()
    return TestClient(app)


def upload(client, data: bytes, name="card.png", consent="true", doc_type="aadhaar"):
    return client.post(
        "/api/verify/upload",
        files={"file": (name, data, "application/octet-stream")},
        data={"consent": consent, "docType": doc_type},
    )


# ---------- quality gate -----------------------------------------------------
def test_sharp_card_passes():
    r = quality.assess_quality(png(make_card()))
    assert r.passed, [c for c in r.checks if not c.passed]
    assert r.score >= 80


def test_blurry_card_fails_on_blur():
    blurred = cv2.GaussianBlur(make_card(), (0, 0), 9)
    r = quality.assess_quality(png(blurred))
    assert not r.passed
    assert "blurry" in r.reason.lower()


def test_dark_card_is_flagged_but_not_blocked():
    dark = (make_card().astype(np.float32) * 0.18).astype(np.uint8)
    r = quality.assess_quality(png(dark))
    assert any(c.key == "brightness" and not c.passed and not c.critical for c in r.checks)


def test_small_image_fails_resolution():
    r = quality.assess_quality(png(make_card(250, 175)))
    assert not r.passed
    assert any(c.key == "resolution" and not c.passed for c in r.checks)


def test_glare_is_flagged_but_not_blocked():
    img = make_card()
    cv2.circle(img, (800, 550), 380, (255, 255, 255), -1)
    r = quality.assess_quality(png(img))
    assert any(c.key == "glare" and not c.passed for c in r.checks)


# ---------- endpoints --------------------------------------------------------
def test_requires_login():
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    r = c.post("/api/verify/upload", files={"file": ("a.png", b"x")}, data={"consent": "true"})
    assert r.status_code == 401


def test_upload_then_quality_then_delete(client):
    r = upload(client, jpg(make_card()), "card.jpg")
    assert r.status_code == 201
    sid = r.json()["sessionId"]  # camelCase

    q = client.post(f"/api/verify/{sid}/quality")
    assert q.status_code == 200
    body = q.json()
    assert body["passed"] is True
    assert {"key", "label", "passed", "critical", "message"} <= set(body["checks"][0])

    assert client.delete(f"/api/verify/{sid}").status_code == 204
    assert client.post(f"/api/verify/{sid}/quality").status_code == 404


def test_consent_required(client):
    assert upload(client, jpg(make_card()), consent="false").status_code == 400


def test_pan_not_supported_yet(client):
    assert upload(client, jpg(make_card()), doc_type="pan").status_code == 400


def test_rejects_non_image_even_if_named_png(client):
    r = upload(client, b"this is not an image at all" * 50, "evil.png")
    assert r.status_code == 400


def test_rejects_oversize(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10_000)
    from verification import file_validation
    monkeypatch.setattr(file_validation.config, "MAX_UPLOAD_BYTES", 10_000)
    big = jpg(make_card())  # well over 10 KB
    # read_limited has the default bound at import time, so patch the default too
    monkeypatch.setattr(file_validation.read_limited, "__defaults__", (10_000,))
    r = upload(client, big)
    assert r.status_code == 400 and "too large" in r.json()["detail"].lower()


def test_pdf_is_rasterised(client):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Aadhaar test page", fontsize=20)
    data = doc.tobytes()
    r = upload(client, data, "card.pdf")
    assert r.status_code == 201
    sid = r.json()["sessionId"]
    q = client.post(f"/api/verify/{sid}/quality")
    assert q.status_code == 200  # rendered page was analysable (result may be pass or fail)


def test_pdf_with_javascript_rejected(client):
    doc = pymupdf.open()
    doc.new_page()
    data = bytearray(doc.tobytes())
    data = bytes(data) + b"\n% /JavaScript (app.alert(1))\n"
    assert upload(client, data, "x.pdf").status_code == 400


def test_pdf_too_many_pages_rejected(client):
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    assert upload(client, doc.tobytes(), "x.pdf").status_code == 400


def test_session_not_visible_to_other_user(client):
    sid = upload(client, jpg(make_card())).json()["sessionId"]
    assert store.get(sid, user_id=2) is None  # different user cannot read it
    assert store.get(sid, user_id=1) is not None


def test_session_expires(client, monkeypatch):
    sid = upload(client, jpg(make_card())).json()["sessionId"]
    store._sessions[sid].created_at -= config.SESSION_TTL_SECONDS + 1
    assert client.post(f"/api/verify/{sid}/quality").status_code == 404


def test_upload_rate_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOADS_PER_MINUTE_PER_USER", 2)
    data = jpg(make_card())
    assert upload(client, data).status_code == 201
    assert upload(client, data).status_code == 201
    assert upload(client, data).status_code == 429


# ---------- quality gate: scans and PDF pages (white backgrounds) ------------
def white_page_with_text(width=1700, height=2200) -> np.ndarray:
    """Like a rendered e-Aadhaar PDF page: pure white background, black text."""
    img = np.full((height, width, 3), 255, np.uint8)
    rng = np.random.default_rng(3)
    for i in range(30):
        text = "".join(rng.choice(list("ABCDEFGHJKLMNPRSTUVWXYZ0123456789 "), 34))
        cv2.putText(img, text, (150, 150 + i * 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (15, 15, 15), 2, cv2.LINE_AA)
    return img


def test_white_pdf_page_is_not_called_overexposed_or_glary():
    r = quality.assess_quality(png(white_page_with_text()), "pdf")
    assert r.passed, [c for c in r.checks if not c.passed]
    assert all(c.key != "card" for c in r.checks)          # card framing does not apply to a PDF page


def test_flatbed_scan_with_white_lid_passes():
    card = make_card(1200, 800)
    scan = np.full((1500, 1900, 3), 255, np.uint8)         # white scanner lid all around the card
    scan[300:1100, 350:1550] = card
    r = quality.assess_quality(png(scan))
    assert r.passed, [c for c in r.checks if not c.passed]


def test_washed_out_overexposed_photo_is_flagged_but_not_blocked():
    washed = (255 - (255 - make_card().astype(np.float32)) * 0.2).astype(np.uint8)
    r = quality.assess_quality(png(washed))
    assert any(c.key in ("brightness", "contrast") and not c.passed and not c.critical for c in r.checks)


def test_pdf_page_only_checks_resolution():
    # a mostly-white digital page must not be judged on blur / glare / contrast
    page = np.full((1600, 1130, 3), 255, np.uint8)
    cv2.putText(page, "Aadhaar", (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 6)
    r = quality.assess_quality(png(page), source_type="pdf")
    assert r.passed and [c.key for c in r.checks] == ["resolution"]
