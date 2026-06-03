"""
Calendar-related Pydantic schemas for API requests/responses.
"""

from typing import Optional
from pydantic import BaseModel, Field


class CalendarCreateRequest(BaseModel):
    """Request schema for creating a calendar event from natural language."""
    user_id: str = Field(..., description="User identifier")
    description: str = Field(
        ..., 
        description="Natural language description of the event"
    )
    timezone: str = Field(
        default=None,
        description="User's timezone (e.g., 'America/Los_Angeles'). If not provided, defaults to Europe/Paris."
    )


class CalendarEventResponse(BaseModel):
    """Response schema for a calendar event."""
    success: bool
    id: Optional[str] = None
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    ics_content: Optional[str] = Field(None, description="ICS file content for download")
    raw_data: Optional[str] = Field(None, description="Raw parsed event data")
    message: Optional[str] = None

