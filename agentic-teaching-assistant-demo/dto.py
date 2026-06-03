"""
Data Transfer Objects (DTOs) for AgenticTA services.

These dataclasses define the contract between services and UI layers.
Services return DTOs (not Gradio components), which UI adapters convert to framework-specific formats.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any
from enum import Enum


# =============================================================================
# Quiz DTOs
# =============================================================================

@dataclass
class QuizQuestion:
    """A single quiz question with choices and answer."""
    question: str
    choices: List[str]
    correct_answer: str
    explanation: str
    user_answer: Optional[str] = None


@dataclass
class QuizState:
    """Current state of a quiz session."""
    questions: List[QuizQuestion]
    current_index: int
    total: int
    progress_text: str
    show_prev: bool
    show_next: bool
    show_submit: bool
    
    @classmethod
    def from_quiz_data(cls, quiz_data: List[dict], current_index: int, user_answers: List[Optional[str]]) -> "QuizState":
        """Create QuizState from raw quiz data."""
        questions = [
            QuizQuestion(
                question=q["question"],
                choices=q["choices"],
                correct_answer=q["answer"],
                explanation=q["explanation"],
                user_answer=user_answers[i] if i < len(user_answers) else None
            )
            for i, q in enumerate(quiz_data)
        ]
        
        total = len(quiz_data)
        return cls(
            questions=questions,
            current_index=current_index,
            total=total,
            progress_text=f"Question {current_index + 1} of {total}",
            show_prev=current_index > 0,
            show_next=current_index < total - 1,
            show_submit=current_index == total - 1
        )


@dataclass
class QuizResult:
    """Result of a submitted quiz."""
    score: int
    total: int
    percentage: int
    results_text: str
    question_results: List[Dict[str, Any]]


# =============================================================================
# Curriculum DTOs
# =============================================================================

@dataclass
class TopicInfo:
    """Information about a curriculum topic."""
    name: str
    is_subtopic: bool
    is_completed: bool
    is_visible: bool
    is_unlocked: bool = True


@dataclass
class CurriculumResult:
    """Result of curriculum generation or update."""
    topics: List[TopicInfo]
    study_material: str
    unlocked_topics: Set[str]
    expanded_topics: Set[str]
    completed_topics: Set[str]
    success: bool
    error_message: Optional[str] = None


@dataclass
class TopicCompleteResult:
    """Result of marking a topic as complete."""
    completed_topics: Set[str]
    unlocked_topics: Set[str]
    quiz_data: Optional[List[dict]] = None
    study_material: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None


# =============================================================================
# Chat DTOs
# =============================================================================

class RouteType(Enum):
    """Types of chat query routes."""
    STUDY_MATERIAL = "study_material"
    CHITCHAT = "chitchat"
    SUPPLEMENT = "supplement"
    CALENDAR = "calendar"
    MINIGAME = "minigame"


@dataclass
class ChatRequest:
    """A chat request from the user."""
    message: str
    images: List[str] = field(default_factory=list)
    session_id: Optional[str] = None


@dataclass
class ChatResponse:
    """Response from the chat service."""
    content: str
    route_type: RouteType
    is_streaming: bool = False
    calendar_file: Optional[str] = None
    calendar_status: Optional[str] = None
    calendar_preview: Optional[str] = None


# =============================================================================
# File Upload DTOs
# =============================================================================

@dataclass
class FileValidationResult:
    """Result of file validation."""
    is_valid: bool
    message: str
    validated_files: List[str] = field(default_factory=list)


@dataclass
class FileUploadResult:
    """Result of file upload and processing."""
    success: bool
    message: str
    processed_files: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


# =============================================================================
# Calendar DTOs
# =============================================================================

@dataclass
class CalendarEventRequest:
    """Request to create a calendar event."""
    description: str  # Natural language description


@dataclass
class CalendarEventResult:
    """Result of calendar event creation."""
    success: bool
    file_path: Optional[str] = None
    status_message: str = ""
    preview: Optional[str] = None
    event_data: Optional[Dict[str, Any]] = None


