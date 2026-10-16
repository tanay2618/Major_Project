"""
Image quality gate (OpenCV).

Runs on the first page image. Each check returns a QualityCheck. Only resolution and blur are
`critical` (block with "please re-upload"); the others only produce a warning. All thresholds come from config.py - tune them on your
own sample photos, the defaults are starting points, not truths.
"""
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import config
from .schemas import QualityCheck, QualityResult

# Weights used for the 0-100 score.
_WEIGHTS = {"resolution": 20, "blur": 30, "brightness": 15, "glare": 15, "contrast": 10, "card": 10}


def _decode(png_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


def _check_resolution(img: np.ndarray) -> QualityCheck:
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side < config.QUALITY_MIN_LONG_SIDE_PX:  # hopelessly small: nothing can be read
        return QualityCheck(
            key="resolution", label="Resolution", value=float(long_side),
            threshold=f">= {config.QUALITY_MIN_LONG_SIDE_PX}px", passed=False, critical=True,
            message="Image resolution is too low. Please upload a higher-quality photo or scan.")
    ok = long_side >= config.QUALITY_WARN_LONG_SIDE_PX
    return QualityCheck(
        key="resolution", label="Resolution", value=float(long_side),
        threshold=f">= {config.QUALITY_WARN_LONG_SIDE_PX}px", passed=ok, critical=False,
        message="Resolution is good." if ok else
        "Resolution is on the low side. The QR code may be hard to read; a larger photo works better.")


def _check_blur(gray: np.ndarray) -> QualityCheck:
    # Resize so the score does not depend on how many megapixels the phone has.
    h, w = gray.shape
    scale = config.QUALITY_BLUR_NORMALISED_LONG_SIDE / max(h, w)
    if scale != 1.0:
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=interp)
    var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    ok = var >= config.QUALITY_BLUR_MIN_LAPLACIAN_VAR
    return QualityCheck(
        key="blur", label="Sharpness", value=round(var, 1),
        threshold=f">= {config.QUALITY_BLUR_MIN_LAPLACIAN_VAR:g}", passed=ok, critical=True,
        message="Image is sharp." if ok else
        "Image is too blurry. Hold the camera steady, tap to focus and retake in good light.",
    )


def _check_brightness(gray: np.ndarray) -> QualityCheck:
    mean = float(gray.mean())
    p1 = float(np.percentile(gray, 1))  # brightness of the darkest 1% (ink / dark pixels)
    if mean < config.QUALITY_BRIGHTNESS_CRITICAL_MIN:
        return QualityCheck(key="brightness", label="Brightness", value=round(mean, 1),
                            threshold=f">= {config.QUALITY_BRIGHTNESS_CRITICAL_MIN:g}", passed=False, critical=False,
                            message="Image is too dark. Retake in better light.")
    if p1 > config.QUALITY_OVEREXPOSED_P1_CRITICAL:
        return QualityCheck(key="brightness", label="Brightness", value=round(mean, 1),
                            threshold=f"darkest pixels < {config.QUALITY_OVEREXPOSED_P1_CRITICAL:g}", passed=False,
                            critical=False,
                            message="Image is overexposed and the text has washed out. Move away from direct light and retake.")
    ok = mean >= config.QUALITY_BRIGHTNESS_WARN_MIN and p1 <= config.QUALITY_OVEREXPOSED_P1_WARN
    return QualityCheck(key="brightness", label="Brightness", value=round(mean, 1),
                        threshold=f">= {config.QUALITY_BRIGHTNESS_WARN_MIN:g}", passed=ok, critical=False,
                        message="Lighting is good." if ok else
                        "Lighting is not ideal. Results may be less reliable.")


def _glare_percent(img: np.ndarray) -> float:
    """
    Percent of the image covered by blown-out (pure white) patches.

    Patches that touch the image border are ignored: that is the white scanner lid, the white
    page around a card, or a PDF page background - not a reflection on the card.
    """
    saturated = (img.min(axis=2) >= 253).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(saturated, connectivity=8)
    h, w = saturated.shape
    area = 0
    for i in range(1, n):
        x, y, cw, ch, a_ = stats[i]
        if x == 0 or y == 0 or x + cw >= w or y + ch >= h:
            continue
        area += a_
    return area * 100.0 / (h * w)


def _check_glare(img: np.ndarray) -> QualityCheck:
    pct = _glare_percent(img)
    if pct >= config.QUALITY_GLARE_CRITICAL_PCT:
        return QualityCheck(key="glare", label="Glare", value=round(pct, 1),
                            threshold=f"< {config.QUALITY_GLARE_CRITICAL_PCT:g}%", passed=False,
                            critical=False,
                            message="Strong glare detected. Tilt the card to avoid reflections and retake.")
    ok = pct < config.QUALITY_GLARE_WARN_PCT
    return QualityCheck(key="glare", label="Glare", value=round(pct, 1),
                        threshold=f"< {config.QUALITY_GLARE_WARN_PCT:g}%", passed=ok, critical=False,
                        message="No significant glare." if ok else
                        "Some glare detected. Make sure the QR code is not covered by it.")


def _check_contrast(gray: np.ndarray) -> QualityCheck:
    std = float(gray.std())
    if std < config.QUALITY_CONTRAST_CRITICAL_MIN:
        return QualityCheck(key="contrast", label="Contrast", value=round(std, 1),
                            threshold=f">= {config.QUALITY_CONTRAST_CRITICAL_MIN:g}", passed=False,
                            critical=False,
                            message="Image has very low contrast (washed out or faded). Retake it.")
    ok = std >= config.QUALITY_CONTRAST_WARN_MIN
    return QualityCheck(key="contrast", label="Contrast", value=round(std, 1),
                        threshold=f">= {config.QUALITY_CONTRAST_WARN_MIN:g}", passed=ok, critical=False,
                        message="Contrast is good." if ok else "Contrast is low. Results may be less reliable.")


def _find_card(gray: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """Return (coverage 0-1, skew in degrees) of the largest card-like quadrilateral."""
    h, w = gray.shape
    scale = 800.0 / max(h, w)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None
    best = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(best)
    coverage = area / float(small.shape[0] * small.shape[1])
    (_, _), (rw, rh), angle = cv2.minAreaRect(best)
    if rw < rh:  # normalise: angle relative to the horizontal
        angle = angle - 90.0
    skew = abs(((angle + 45.0) % 90.0) - 45.0)  # 0 = perfectly straight
    return coverage, float(skew)


def _check_card(gray: np.ndarray) -> QualityCheck:
    coverage, skew = _find_card(gray)
    if coverage is None:
        return QualityCheck(key="card", label="Card framing", value=None, threshold=None,
                            passed=False, critical=False,
                            message="Could not find the card edges. Place the card on a plain background.")
    problems = []
    if coverage < config.QUALITY_CARD_MIN_COVERAGE:
        problems.append("The card looks small in the frame. Move closer.")
    if skew is not None and skew > config.QUALITY_MAX_SKEW_DEG:
        problems.append("The card is tilted. Hold the camera parallel to the card.")
    return QualityCheck(
        key="card", label="Card framing", value=round(coverage * 100, 1),
        threshold=f"covers >= {config.QUALITY_CARD_MIN_COVERAGE * 100:g}% of the frame",
        passed=not problems, critical=False,
        message="Card is well framed." if not problems else " ".join(problems),
    )


def assess_quality(png_bytes: bytes, source_type: str = "image") -> QualityResult:
    """
    Blocking (CPU) work - call it through run_in_threadpool.

    source_type "pdf": the page is a rendered document, not a camera photo, so the
    "card framing" check does not apply and is skipped.
    """
    img = _decode(png_bytes)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if source_type == "pdf":
        # A rendered PDF (e.g. DigiLocker) is a clean digital page, not a camera photo. Its mostly-white
        # background makes blur / glare / contrast numbers meaningless, so only resolution is checked.
        checks: List[QualityCheck] = [_check_resolution(img)]
    else:
        # Only resolution and blur can block. Everything else is advice shown to the user; if the
        # image is truly unreadable the OCR / QR steps send it to manual review anyway.
        checks = [
            _check_resolution(img),
            _check_blur(gray),
            _check_brightness(gray),
            _check_glare(img),
            _check_contrast(gray),
            _check_card(gray),
        ]

    total = sum(_WEIGHTS[c.key] for c in checks)
    earned = sum(_WEIGHTS[c.key] for c in checks if c.passed)
    score = int(round(earned * 100 / total))

    failed_critical = [c for c in checks if c.critical and not c.passed]
    return QualityResult(
        passed=not failed_critical,
        score=score,
        reason=failed_critical[0].message if failed_critical else None,
        checks=checks,
    )
