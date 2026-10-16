"""
Settings for the document-verification package.
Everything tunable lives here so thresholds can be adjusted in one place.
Override any value from backend/.env (names in CAPS below).
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


# ---- Upload limits -------------------------------------------------------
MAX_UPLOAD_BYTES = _int("VERIFY_MAX_UPLOAD_BYTES", 5 * 1024 * 1024)  # 5 MB
MAX_IMAGE_PIXELS = _int("VERIFY_MAX_IMAGE_PIXELS", 50_000_000)  # decompression-bomb guard
MAX_PDF_PAGES = _int("VERIFY_MAX_PDF_PAGES", 2)
PDF_RENDER_DPI = _int("VERIFY_PDF_RENDER_DPI", 300)
ALLOWED_MIME = {"image/jpeg", "image/png", "application/pdf"}

# ---- Sessions ------------------------------------------------------------
SESSION_TTL_SECONDS = _int("VERIFY_SESSION_TTL_SECONDS", 600)  # 10 minutes
MAX_ACTIVE_SESSIONS_PER_USER = _int("VERIFY_MAX_ACTIVE_SESSIONS_PER_USER", 3)
MAX_UPLOADS_PER_MINUTE_PER_USER = _int("VERIFY_MAX_UPLOADS_PER_MINUTE", 6)

# ---- Quality gate thresholds --------------------------------------------
# These are starting values. Tune them on your own sample photos.
# "critical" checks block verification when they fail; the others only warn.
QUALITY_MIN_LONG_SIDE_PX = _int("QUALITY_MIN_LONG_SIDE_PX", 300)          # critical
QUALITY_WARN_LONG_SIDE_PX = _int("QUALITY_WARN_LONG_SIDE_PX", 900)    # warn only
QUALITY_BLUR_MIN_LAPLACIAN_VAR = _float("QUALITY_BLUR_MIN", 25.0)          # critical
QUALITY_BLUR_NORMALISED_LONG_SIDE = 1200  # image is resized to this before measuring blur
QUALITY_BRIGHTNESS_CRITICAL_MIN = _float("QUALITY_BRIGHT_CRIT_MIN", 40.0)   # critical: mean gray below this = too dark
QUALITY_BRIGHTNESS_WARN_MIN = _float("QUALITY_BRIGHT_WARN_MIN", 70.0)
# Overexposed / washed out = even the DARKEST 1% of pixels is bright (printed text has faded away).
# A white scan or PDF page still has dark text, so it is not flagged.
QUALITY_OVEREXPOSED_P1_CRITICAL = _float("QUALITY_OVEREXP_P1_CRIT", 170.0)   # critical
QUALITY_OVEREXPOSED_P1_WARN = _float("QUALITY_OVEREXP_P1_WARN", 120.0)
QUALITY_GLARE_CRITICAL_PCT = _float("QUALITY_GLARE_CRIT_PCT", 12.0)        # critical
QUALITY_GLARE_WARN_PCT = _float("QUALITY_GLARE_WARN_PCT", 3.0)
QUALITY_CONTRAST_CRITICAL_MIN = _float("QUALITY_CONTRAST_CRIT_MIN", 15.0)  # critical
QUALITY_CONTRAST_WARN_MIN = _float("QUALITY_CONTRAST_WARN_MIN", 25.0)
QUALITY_CARD_MIN_COVERAGE = _float("QUALITY_CARD_MIN_COVERAGE", 0.25)      # warn only
QUALITY_MAX_SKEW_DEG = _float("QUALITY_MAX_SKEW_DEG", 20.0)                # warn only

# ---- QR scanning ---------------------------------------------------------
QR_MIN_SECURE_DIGITS = _int("QR_MIN_SECURE_DIGITS", 500)       # a Secure QR is thousands of digits
QR_MAX_SECURE_DIGITS = _int("QR_MAX_SECURE_DIGITS", 20_000)    # refuse absurd payloads
QR_MAX_DECOMPRESSED_BYTES = _int("QR_MAX_DECOMPRESSED_BYTES", 200_000)

# ---- UIDAI certificates --------------------------------------------------
# Every *.cer / *.crt / *.pem / *.der file in this folder is trusted as a possible
# UIDAI signing certificate. NEVER put test certificates here.
_default_cert_dir = os.path.join(os.path.dirname(__file__), "certs")
UIDAI_CERT_DIR = os.getenv("UIDAI_CERT_DIR", _default_cert_dir)

# ---- OCR -----------------------------------------------------------------
OCR_MAX_LONG_SIDE_PX = _int("OCR_MAX_LONG_SIDE_PX", 2000)       # downscale big photos before OCR
OCR_MIN_AVG_CONFIDENCE = _float("OCR_MIN_AVG_CONFIDENCE", 0.60)
OCR_WARMUP = os.getenv("OCR_WARMUP", "true").lower() == "true"  # load models in background at startup

# ---- Cross-match ---------------------------------------------------------
NAME_MATCH_MIN = _float("NAME_MATCH_MIN", 90.0)                 # >= match
NAME_PARTIAL_MIN = _float("NAME_PARTIAL_MIN", 75.0)             # >= partial, below = mismatch
MIN_COMPARABLE_CRITICAL_FIELDS = _int("MIN_COMPARABLE_CRITICAL_FIELDS", 2)

# ---- Decision ------------------------------------------------------------
RISK_MEDIUM = _int("RISK_MEDIUM", 40)
RISK_HIGH = _int("RISK_HIGH", 70)

# ---- QR / signature ------------------------------------------------------
import pathlib

# Folder holding UIDAI public certificates (.cer / .crt / .pem). See certs/README.md.
UIDAI_CERT_DIR = pathlib.Path(
    os.getenv("UIDAI_CERT_DIR", str(pathlib.Path(__file__).parent / "certs"))
)
MAX_DECOMPRESSED_QR_BYTES = _int("VERIFY_MAX_DECOMPRESSED_QR_BYTES", 1_000_000)  # zip-bomb guard

# ---- OCR / cross-match ---------------------------------------------------
OCR_ENGINE = os.getenv("OCR_ENGINE", "paddle")  # "paddle" (default) or "rapid" (bundled models)
OCR_MAX_LONG_SIDE_PX = _int("OCR_MAX_LONG_SIDE_PX", 2000)
OCR_MIN_AVG_CONFIDENCE = _float("OCR_MIN_AVG_CONFIDENCE", 0.50)  # below this = text unreadable
# A printed value that disagrees with the QR is only called a mismatch when the OCR
# was confident about it; otherwise it is "partial" (needs a person to look).
OCR_FIELD_MISMATCH_MIN_CONFIDENCE = _float("OCR_FIELD_MISMATCH_MIN_CONF", 0.80)
NAME_MATCH_MIN_SIMILARITY = _int("NAME_MATCH_MIN", 90)
NAME_PARTIAL_MIN_SIMILARITY = _int("NAME_PARTIAL_MIN", 75)
# Old, unsigned QR: Name and Aadhaar (last 4) must match, plus EITHER the pincode (address side) OR at
# least MIN_SUPPORTING_MATCHES of DOB / Gender / checksum (front side of an older card, no address).
CORE_FIELDS = ("Name", "Aadhaar (last 4)")
SUPPORTING_FIELDS = ("Pincode", "DOB", "Gender", "Aadhaar checksum")
MIN_SUPPORTING_MATCHES = _int("MIN_SUPPORTING_MATCHES", 2)
MIN_MATCHED_FIELDS_FOR_VERIFIED = _int("MIN_MATCHED_FIELDS", 3)
