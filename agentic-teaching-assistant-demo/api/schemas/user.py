"""
User-related Pydantic schemas for API requests/responses.

These schemas mirror the states.py User TypedDict structure.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """Request schema for creating a new user."""
    user_id: str = Field(..., description="Unique user identifier")
    password: Optional[str] = Field(None, description="Password for authentication")
    study_buddy_preference: Optional[str] = Field(
        None, 
        description="User's preference for study buddy personality"
    )
    study_buddy_name: str = Field(
        "Study Buddy", 
        description="Name of the study buddy"
    )


class UserResponse(BaseModel):
    """Response schema for user data."""
    user_id: str
    study_buddy_preference: Optional[str] = None
    study_buddy_persona: Optional[str] = None
    study_buddy_name: str
    curriculum: Optional[List[dict]] = None  # Full curriculum structure
    uploaded_files: Optional[List[str]] = None

    class Config:
        from_attributes = True


class AuthCheckResponse(BaseModel):
    """Response for checking if user exists."""
    exists: bool


class AuthLoginRequest(BaseModel):
    """Request schema for user login."""
    user_id: str = Field(..., description="Username to login with")
    password: Optional[str] = Field(None, description="Password (optional for backward compatibility)")


class AuthLoginResponse(BaseModel):
    """Response schema for login."""
    user: UserResponse
    is_new_user: bool
    has_curriculum: bool = False
    token: Optional[str] = Field(None, description="Authentication token (JWT)")

