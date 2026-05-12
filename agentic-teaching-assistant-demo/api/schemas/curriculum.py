"""
Curriculum-related Pydantic schemas for API requests/responses.

These schemas mirror the states.py Curriculum, StudyPlan, Chapter, SubTopic structures.
"""

from typing import Optional, List, Any
from pydantic import BaseModel, Field
from enum import Enum


class StatusEnum(str, Enum):
    """Status enum matching states.py Status."""
    NA = "NA"
    STARTED = "started"
    PROGRESSING = "progressing"
    COMPLETED = "completed"


class QuizSchema(BaseModel):
    """Quiz schema matching backend quiz dict format."""
    question: str
    choices: List[str]
    answer: str  # The answer TEXT, not index
    explanation: str


class SubTopicResponse(BaseModel):
    """Response schema for a subtopic."""
    number: int = Field(..., description="Subtopic number (0-indexed)")
    sub_topic: str = Field(..., description="Name of this sub-topic")
    status: Optional[StatusEnum] = None
    study_material: Optional[str] = Field(None, description="Markdown study content")
    display_markdown: Optional[str] = Field(None, description="Rendered markdown with images")
    reference: str = Field(..., description="PDF document name")
    quizzes: Optional[List[QuizSchema]] = None
    feedback: Optional[List[str]] = None

    class Config:
        from_attributes = True


class ChapterResponse(BaseModel):
    """Response schema for a chapter."""
    number: int = Field(..., description="Chapter number (0-indexed)")
    name: str = Field(..., description="Name of this chapter")
    status: Optional[StatusEnum] = None
    sub_topics: Optional[List[SubTopicResponse]] = None
    reference: str = Field(..., description="PDF document name")
    pdf_loc: str = Field(..., description="Absolute path to PDF")
    quizzes: Optional[List[QuizSchema]] = None
    feedback: Optional[List[str]] = None

    class Config:
        from_attributes = True


class StudyPlanResponse(BaseModel):
    """Response schema for study plan."""
    study_plan: List[ChapterResponse]

    class Config:
        from_attributes = True


class CurriculumResponse(BaseModel):
    """Response schema for curriculum."""
    active_chapter: Optional[ChapterResponse] = None
    next_chapter: Optional[ChapterResponse] = None
    study_plan: Optional[StudyPlanResponse] = None
    status: Optional[List[Optional[StatusEnum]]] = None

    class Config:
        from_attributes = True


class CurriculumGenerateRequest(BaseModel):
    """Request schema for generating curriculum."""
    user_id: str = Field(..., description="User identifier")
    study_buddy_preference: str = Field(
        ..., 
        description="User's preference for study buddy personality"
    )
    study_buddy_name: str = Field(
        "Study Buddy",
        description="Name for the study buddy"
    )


class CurriculumGenerateResponse(BaseModel):
    """Response schema for curriculum generation."""
    success: bool
    user: Optional[dict] = None  # Full user object with curriculum
    message: Optional[str] = None


class SubtopicStatusUpdateRequest(BaseModel):
    """Request schema for updating subtopic status."""
    status: StatusEnum
    feedback: Optional[List[str]] = None


class SubtopicStatusUpdateResponse(BaseModel):
    """Response schema for subtopic status update."""
    success: bool
    subtopic: Optional[SubTopicResponse] = None
    message: Optional[str] = None


class NextChapterResponse(BaseModel):
    """Response schema for moving to next chapter."""
    success: bool
    chapter: Optional[ChapterResponse] = None
    message: Optional[str] = None

