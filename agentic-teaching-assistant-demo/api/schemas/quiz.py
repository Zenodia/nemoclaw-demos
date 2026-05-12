"""
Quiz-related Pydantic schemas for API requests/responses.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class QuizQuestion(BaseModel):
    """Schema for a single quiz question."""
    question: str
    choices: List[str]
    answer: str  # The answer TEXT (e.g., "A" or the full answer text)
    explanation: str


class QuizGenerateRequest(BaseModel):
    """Request schema for generating quiz questions."""
    user_id: str = Field(..., description="User identifier")
    subtopic_number: int = Field(0, description="Subtopic index (0-based). Use GET /api/quiz/subtopics/{user_id} to list available subtopics.")
    pdf_filename: Optional[str] = Field(None, description="Optional specific PDF to use")


class QuizGenerateResponse(BaseModel):
    """Response schema for quiz generation."""
    success: bool
    questions: Optional[List[QuizQuestion]] = None
    message: Optional[str] = None


class QuizSubmitRequest(BaseModel):
    """Request schema for submitting quiz answers."""
    user_id: str = Field(..., description="User identifier")
    subtopic_number: int = Field(..., description="Subtopic number")
    answers: List[str] = Field(..., description="One answer per question. Accept letter (A/B/C/D), numeric index (0/1/2/3), or full choice text. E.g. ['A', 'B', 'C'] or ['0', '1', '2']")


class QuizSubmitResponse(BaseModel):
    """Response schema for quiz submission."""
    success: bool
    correct: int = Field(..., description="Number of correct answers")
    total: int = Field(..., description="Total number of questions")
    passed: bool = Field(..., description="Whether all answers were correct")
    feedback: Optional[List[str]] = Field(None, description="Feedback for each question")
    message: Optional[str] = None

