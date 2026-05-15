"""
Planner-related Pydantic schemas for academic study planning.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlannerRequest(BaseModel):
    """Request schema for creating a study plan."""

    user_id: str = Field(..., description="User identifier")
    request: str = Field(default="Plan my week", description="User's planning request")
    course_schedule: str = Field(
        default="",
        description="Known class schedule, recurring commitments, or fixed study constraints",
    )
    assignments: List[str] = Field(
        default_factory=list,
        description="Assignment, exam, or deadline descriptions",
    )
    availability: str = Field(
        default="",
        description="Free study windows or preferred study times",
    )
    timezone: str = Field(
        default="Europe/Paris",
        description="User timezone, e.g. America/New_York",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Plan start date in YYYY-MM-DD format; defaults to today",
    )
    days: int = Field(default=7, ge=1, le=31, description="Number of days to plan")
    daily_study_limit_hours: float = Field(
        default=3.0,
        ge=0.5,
        le=12.0,
        description="Maximum recommended study hours per day",
    )
    create_calendar_events: bool = Field(
        default=False,
        description="Whether to include ICS content for each study block",
    )


class PlannerBlockResponse(BaseModel):
    """One scheduled block in a planner response."""

    day: str
    date: str
    start_time: str
    duration_hours: float
    title: str
    focus: str
    priority: str = "medium"
    task_type: str = "study"
    source: str = "planner"
    calendar_text: str = ""
    ics_content: Optional[str] = None


class PlannerResponse(BaseModel):
    """Planner API response."""

    success: bool
    markdown: str
    blocks: List[PlannerBlockResponse] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    curriculum_context: Dict[str, Any] = Field(default_factory=dict)
    raw_plan: Dict[str, Any] = Field(default_factory=dict)
    calendar_filename: Optional[str] = None
    calendar_file_path: Optional[str] = None
    calendar_download_path: Optional[str] = None
    calendar_download_url: Optional[str] = None
    error: Optional[str] = None

