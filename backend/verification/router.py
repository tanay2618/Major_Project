"""
Verification endpoints (all require a logged-in user).

POST   /api/verify/upload            validate + store the document (in memory only)
POST   /api/verify/{id}/quality      image quality gate
POST   /api/verify/{id}/qr           find + decode the Aadhaar QR code
POST   /api/verify/{id}/signature    check the UIDAI digital signature
POST   /api/verify/{id}/crossmatch   OCR the card, compare with the QR, give the final decision
DELETE /api/verify/{id}              wipe the session

The steps must run in that order. Next chunk adds: /forensics (tamper signals).
"""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool

import auth
import models

from . import crossmatch as crossmatch_mod
from . import decision, file_validation, ocr, qr_decoder, quality, signature
from .schemas import (
    CrossMatchField,
    CrossMatchResult,
    OcrInfo,
    QrFields,
    QrResult,
    QualityResult,
    SignatureResult,
    UploadResponse,
)
from .session_store import RateLimitError, VerificationSession, store

# Log events only. Never log file contents, extracted fields or document numbers.
log = logging.getLogger("verification")

router = APIRouter(prefix="/api/verify", tags=["verification"])


def _get_session(session_id: str, user: models.User) -> VerificationSession:
    session = store.get(session_id, user.id)
    if session is None:
        # Same answer for "does not exist", "expired" and "not yours".
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verification session not found or expired.")
    return session


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    docType: str = Form("aadhaar"),
    consent: str = Form(...),
    user: models.User = Depends(auth.get_current_user),
):
    if consent.strip().lower() != "true":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consent is required to process your document.")
    if docType != "aadhaar":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only Aadhaar verification is supported right now.")

    try:
        raw = await file_validation.read_limited(file)
        doc = await run_in_threadpool(file_validation.validate_and_normalise, raw)
    except file_validation.FileValidationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    finally:
        raw = b""  # drop the original bytes as early as possible

    try:
        session = store.create(user.id, doc.pages, doc.source_type, doc.meta)
    except RateLimitError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))

    log.info("upload accepted session=%s type=%s", session.id[:6], doc.source_type)
    return UploadResponse(session_id=session.id)


@router.post("/{session_id}/quality", response_model=QualityResult)
async def check_quality(session_id: str, user: models.User = Depends(auth.get_current_user)):
    session = _get_session(session_id, user)
    try:
        result = await run_in_threadpool(quality.assess_quality, session.pages[0], session.source_type)
    except Exception:
        log.exception("quality check failed session=%s", session_id[:6])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The image could not be analysed.")
    session.results["quality"] = result
    log.info("quality session=%s passed=%s score=%s", session_id[:6], result.passed, result.score)
    return result


@router.post("/{session_id}/qr", response_model=QrResult)
async def read_qr(session_id: str, user: models.User = Depends(auth.get_current_user)):
    session = _get_session(session_id, user)
    try:
        qr, problem = await run_in_threadpool(qr_decoder.decode_pages, session.pages)
    except Exception:
        log.exception("qr decode failed session=%s", session_id[:6])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The QR code could not be processed.")

    session.results["qr"] = qr  # keeps the signed bytes server-side; they are never returned
    session.results.pop("signature", None)
    session.results.pop("crossmatch", None)
    if qr is None:
        log.info("qr session=%s found=False", session_id[:6])
        return QrResult(qr_found=False, note=problem)

    log.info("qr session=%s found=True type=%s", session_id[:6], qr.qr_type)
    return QrResult(
        qr_found=True,
        qr_type=qr.qr_type,
        fields=QrFields(**qr.fields) if qr.fields else None,
        note=qr.note,
    )


@router.post("/{session_id}/signature", response_model=SignatureResult)
async def check_signature(session_id: str, user: models.User = Depends(auth.get_current_user)):
    session = _get_session(session_id, user)
    if "qr" not in session.results:
        raise HTTPException(status.HTTP_409_CONFLICT, "Read the QR code first.")
    qr = session.results["qr"]

    if qr is None:
        outcome = signature.SignatureOutcome(None, None, "There is no QR code, so there is no signature to check.")
    elif qr.qr_type == "old":
        outcome = signature.SignatureOutcome(
            None, None, "Old unsigned QR: there is no digital signature to verify.")
    else:
        outcome = await run_in_threadpool(signature.verify_secure_qr, qr.signed_data, qr.signature)

    session.results["signature"] = outcome
    log.info("signature session=%s valid=%s", session_id[:6], outcome.valid)
    return SignatureResult(signature_valid=outcome.valid, issuer=outcome.issuer, reason=outcome.reason)


@router.post("/{session_id}/crossmatch", response_model=CrossMatchResult)
async def cross_match(session_id: str, user: models.User = Depends(auth.get_current_user)):
    session = _get_session(session_id, user)
    if "signature" not in session.results:
        raise HTTPException(status.HTTP_409_CONFLICT, "Check the signature first.")
    qr = session.results["qr"]
    sig = session.results["signature"]
    q = session.results.get("quality")

    try:
        # OCR the page the QR was found on (or the first page when there is no QR).
        page = session.pages[qr.page_index if qr else 0]
        if qr and qr.rotation:
            # A sideways photo: turn it upright (the QR tells us how) so the text can be read.
            page = await run_in_threadpool(ocr.rotate_upright, page, qr.rotation)
        lines = await run_in_threadpool(ocr.run_ocr, page)
        card = ocr.parse_card_text(lines)
    except Exception:
        log.exception("ocr failed session=%s", session_id[:6])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The text on the card could not be read.")

    cross = crossmatch_mod.compare(card, qr.fields or {}) if qr else crossmatch_mod.compare(card, {})
    result = decision.decide(q.passed if q else None, qr, sig, cross)
    session.results["crossmatch"] = cross

    log.info("crossmatch session=%s outcome=%s lines=%s", session_id[:6], result.outcome, card.line_count)
    return CrossMatchResult(
        fields=[CrossMatchField(key=f.key, printed=f.printed, qr=f.qr, status=f.status, similarity=f.similarity)
                for f in cross.fields],
        ocr=OcrInfo(confidence=round(cross.avg_conf, 3), number_masked=cross.number_masked,
                    verhoeff_valid=cross.verhoeff_valid),
        mismatch_count=cross.mismatch_count,
        outcome=result.outcome,
        risk_score=result.risk_score,
        reasons=result.reasons,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user: models.User = Depends(auth.get_current_user)):
    store.delete(session_id, user.id)  # idempotent: no error if already gone
    return Response(status_code=status.HTTP_204_NO_CONTENT)
