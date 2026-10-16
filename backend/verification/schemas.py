"""Response models. JSON field names are camelCase to match the React frontend."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UploadResponse(CamelModel):
    session_id: str


class QualityCheck(CamelModel):
    key: str
    label: str
    value: Optional[float] = None
    threshold: Optional[str] = None
    passed: bool
    critical: bool
    message: str


class QualityResult(CamelModel):
    passed: bool
    score: int  # 0-100
    reason: Optional[str] = None
    checks: List[QualityCheck]


class QrFields(CamelModel):
    name: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    last4: Optional[str] = None
    pincode: Optional[str] = None


class QrResult(CamelModel):
    qr_found: bool
    qr_type: Optional[str] = None  # "secure" | "old" | None
    fields: Optional[QrFields] = None
    note: Optional[str] = None


class SignatureResult(CamelModel):
    signature_valid: Optional[bool] = None  # None = cannot be checked
    issuer: Optional[str] = None
    reason: str


class CrossMatchField(CamelModel):
    key: str
    printed: Optional[str] = None
    qr: Optional[str] = None
    status: str  # match | partial | mismatch | not_checked
    similarity: Optional[int] = None


class OcrInfo(CamelModel):
    confidence: float
    number_masked: Optional[str] = None
    verhoeff_valid: Optional[bool] = None


class CrossMatchResult(CamelModel):
    fields: List[CrossMatchField]
    ocr: OcrInfo
    mismatch_count: int
    outcome: str  # verified | likely_authentic | tampered | forged | low_quality | manual_review
    risk_score: Optional[int] = None
    reasons: List[str]
