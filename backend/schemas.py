from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from models import UserRole

# Base schema
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole = UserRole.APPLICANT

# Registration schema
class UserCreate(UserBase):
    password: str

# Login schema
class UserLogin(BaseModel):
    email: EmailStr
    password: str

# Response schema (never return raw passwords)
class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# Token response schema
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse