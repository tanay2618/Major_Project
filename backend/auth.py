import os
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from database import get_db
import models

load_dotenv()

_FALLBACK_SECRET = "fallbacksecret"
SECRET_KEY = os.getenv("SECRET_KEY", _FALLBACK_SECRET)
ALGORITHM = os.getenv("ALGORITHM", "HS256")

# Refuse to run outside development with the well-known fallback secret,
# otherwise anyone could forge login tokens.
if os.getenv("ENV", "development") != "development" and SECRET_KEY == _FALLBACK_SECRET:
    raise RuntimeError("SECRET_KEY must be set in backend/.env when ENV is not 'development'")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against the stored bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ---------------------------------------------------------------------------
# Current-user dependency: protects endpoints that need a logged-in user.
# Usage:  user: models.User = Depends(auth.get_current_user)
# The frontend must send:  Authorization: Bearer <kyc_token>
# ---------------------------------------------------------------------------
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise unauthorized

    user = db.get(models.User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user
