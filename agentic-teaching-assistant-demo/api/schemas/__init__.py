"""
API Schemas Package

Contains Pydantic models for API request/response validation.
"""

from .user import *
from .curriculum import *
from .chat import *
from .quiz import *
from .calendar import *

__all__ = [
    # User schemas
    "UserCreate",
    "UserResponse",
    "AuthCheckResponse",
    "AuthLoginRequest",
    "AuthLoginResponse",
    # Curriculum schemas
    "SubTopicResponse",
    "ChapterResponse",
    "StudyPlanResponse",
    "CurriculumResponse",
    "CurriculumGenerateRequest",
    "CurriculumGenerateResponse",
    "SubtopicStatusUpdateRequest",
    # Chat schemas
    "ChatRouteRequest",
    "ChatRouteResponse",
    "ChatStreamRequest",
    # Quiz schemas
    "QuizGenerateRequest",
    "QuizQuestion",
    "QuizGenerateResponse",
    "QuizSubmitRequest",
    "QuizSubmitResponse",
    # Calendar schemas
    "CalendarCreateRequest",
    "CalendarEventResponse",
]

