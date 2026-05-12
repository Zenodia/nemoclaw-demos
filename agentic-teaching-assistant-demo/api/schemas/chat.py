"""
Chat-related Pydantic schemas for API requests/responses.
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class ToolType(str, Enum):
    """Tool types for chat routing."""
    CHITCHAT = "chitchat"
    SUPPLEMENT = "supplement"
    BOOK_CALENDAR = "book_calendar"
    MINIGAME = "minigame"
    STUDY_MATERIAL = "study_material"
    UNCLEAR = "unclear"


class ChatRouteRequest(BaseModel):
    """Request schema for routing a chat message to the appropriate tool."""
    message: str = Field(..., description="User's message")
    context: Optional[str] = Field(None, description="Additional context")
    chat_history: Optional[List[dict]] = Field(None, description="Previous messages")


class ChatRouteResponse(BaseModel):
    """Response schema for chat routing."""
    tool: ToolType
    parameters: Optional[dict] = None


class ChatStreamRequest(BaseModel):
    """Request schema for streaming chat response."""
    user_id: str = Field(..., description="User identifier")
    message: str = Field(..., description="User's message")
    tool: Optional[ToolType] = Field(None, description="Pre-determined tool to use")
    chapter_number: Optional[int] = Field(None, description="Current chapter number")
    subtopic_number: Optional[int] = Field(None, description="Current subtopic number")


class ChatMessageResponse(BaseModel):
    """Response schema for a complete chat message."""
    content: str
    tool_used: Optional[ToolType] = None
    youtube_video: Optional[dict] = None
    calendar_event: Optional[dict] = None
    minigame_link: Optional[str] = None

