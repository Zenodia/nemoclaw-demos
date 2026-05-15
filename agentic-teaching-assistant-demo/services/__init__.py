"""
Services layer for AgenticTA.

This package contains Gradio-agnostic business logic services.
Services return DTOs (dataclasses) that can be converted to any UI framework format.

Usage:
    from services import QuizService, CurriculumService

    quiz_svc = QuizService(mnt_folder="/path/to/mnt")
    state = quiz_svc.init_quiz(username="user123")
    
    # For LLM, use the separate llm package:
    from llm import create_llm
    llm = create_llm("fast")
"""

from .quiz_service import QuizService
from .curriculum_service import CurriculumService, StudyMaterialInfo, TopicCompletionResult
from .file_service import FileService, FileValidationResult, FileUploadResult
from .calendar_service import CalendarService, CalendarEventResult, CalendarEventData

__all__ = [
    "QuizService",
    "CurriculumService",
    "StudyMaterialInfo",
    "TopicCompletionResult",
    "FileService",
    "FileValidationResult",
    "FileUploadResult",
    "CalendarService",
    "CalendarEventResult",
    "CalendarEventData",
]
