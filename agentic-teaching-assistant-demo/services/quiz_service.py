"""
Quiz Service - Gradio-agnostic quiz business logic.

This service handles quiz state management, question navigation, and scoring.
It returns DTOs that can be converted to any UI framework format.

Usage:
    from services import QuizService
    
    svc = QuizService(mnt_folder="/path/to/mnt")
    state = svc.init_quiz(username="user123")
    # state is a QuizState dataclass, NOT Gradio components
"""
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from colorama import Fore

from dto import QuizState, QuizResult, QuizQuestion
from nodes import init_user_storage, load_user_state
from standalone_quizes_gen import get_quiz, quiz_output_parser
from quiz_utils import get_question, get_answer, get_citation_as_explain, get_choices


class QuizService:
    """
    Gradio-agnostic quiz service.
    
    Manages quiz state and provides methods for quiz operations.
    All methods return DTOs (dataclasses), not Gradio components.
    """
    
    def __init__(self, mnt_folder: str):
        """
        Initialize QuizService.
        
        Args:
            mnt_folder: Path to the mnt folder for user data storage
        """
        self.mnt_folder = mnt_folder
        self._quiz_data: List[dict] = []
        self._current_index: int = 0
        self._user_answers: List[Optional[str]] = []
    
    def _load_quiz_data(self, username: str) -> List[dict]:
        """
        Load quiz data for a user from their saved state.
        
        Args:
            username: The username to load quiz data for
            
        Returns:
            List of quiz question dictionaries
        """
        store_path, user_store_dir = init_user_storage(self.mnt_folder, username)
        user_state = load_user_state(username)
        
        if not user_state or "curriculum" not in user_state or len(user_state["curriculum"]) == 0:
            return self._get_fallback_quiz()
        
        active_chapter = user_state["curriculum"][0]["active_chapter"]
        
        # Handle both dict and object formats
        if isinstance(active_chapter, dict):
            sub_topics = active_chapter.get("sub_topics", [])
        else:
            sub_topics = active_chapter.sub_topics if hasattr(active_chapter, 'sub_topics') else []
        
        if not sub_topics:
            return self._get_fallback_quiz()
        
        first_subtopic = sub_topics[0]
        
        # Get existing quizzes or generate new ones
        if isinstance(first_subtopic, dict):
            quizzes_d_ls = first_subtopic.get("quizzes", [])
        else:
            quizzes_d_ls = getattr(first_subtopic, 'quizzes', [])
        
        if not quizzes_d_ls:
            # Generate quizzes if none exist
            if isinstance(active_chapter, dict):
                title = active_chapter.get("name", "")
            else:
                title = active_chapter.name
            
            if isinstance(first_subtopic, dict):
                summary = first_subtopic.get("sub_topic", "")
                text_chunk = first_subtopic.get("study_material", "")
            else:
                summary = first_subtopic.sub_topic
                text_chunk = first_subtopic.study_material
            
            quizes_ls = get_quiz(title, summary, text_chunk, "")
            quizzes_d_ls = quiz_output_parser(quizes_ls)
        
        # Convert to standard format
        quiz_data = []
        try:
            for quiz_d in quizzes_d_ls:
                item = {
                    "question": get_question(quiz_d),
                    "choices": get_choices(quiz_d),
                    "answer": get_answer(quiz_d),
                    "explanation": get_citation_as_explain(quiz_d)
                }
                quiz_data.append(item)
        except Exception as e:
            print(Fore.RED + f"Error loading quiz data: {e}" + Fore.RESET)
            return self._get_fallback_quiz()
        
        return quiz_data if quiz_data else self._get_fallback_quiz()
    
    def _get_fallback_quiz(self) -> List[dict]:
        """Return a fallback quiz when no data is available."""
        return [{
            "question": "Sample Question: What is the capital of France?",
            "choices": ["(A) Berlin", "(B) Madrid", "(C) Paris", "(D) Rome"],
            "answer": "(C)",
            "explanation": "The capital of France is Paris."
        }]
    
    def init_quiz(self, username: str) -> QuizState:
        """
        Initialize a quiz session for a user.
        
        Args:
            username: The username to initialize quiz for
            
        Returns:
            QuizState dataclass with initial quiz state
        """
        self._quiz_data = self._load_quiz_data(username)
        self._current_index = 0
        self._user_answers = [None] * len(self._quiz_data)
        
        return self.get_current_state()
    
    def get_current_state(self) -> QuizState:
        """
        Get the current quiz state.
        
        Returns:
            QuizState dataclass with current state
        """
        return QuizState.from_quiz_data(
            quiz_data=self._quiz_data,
            current_index=self._current_index,
            user_answers=self._user_answers
        )
    
    def record_answer(self, answer: str) -> None:
        """
        Record the user's answer for the current question.
        
        Args:
            answer: The user's selected answer
        """
        print(Fore.BLUE + f"recorded user answer = {answer}" + Fore.RESET)
        if 0 <= self._current_index < len(self._user_answers):
            self._user_answers[self._current_index] = answer
    
    def next_question(self) -> QuizState:
        """
        Move to the next question.
        
        Returns:
            QuizState dataclass with updated state
        """
        if self._current_index < len(self._quiz_data) - 1:
            self._current_index += 1
        return self.get_current_state()
    
    def previous_question(self) -> QuizState:
        """
        Move to the previous question.
        
        Returns:
            QuizState dataclass with updated state
        """
        if self._current_index > 0:
            self._current_index -= 1
        return self.get_current_state()
    
    def submit_quiz(self) -> QuizResult:
        """
        Submit the quiz and calculate results.
        
        Returns:
            QuizResult dataclass with score and detailed results
        """
        correct_count = 0
        question_results = []
        results_text_parts = []
        
        for i, (question_data, user_answer) in enumerate(zip(self._quiz_data, self._user_answers)):
            correct_answer = question_data["answer"]
            
            # Check if answer is correct
            is_correct = False
            if user_answer is not None:
                is_correct = correct_answer in user_answer
            
            if is_correct:
                correct_count += 1
            
            # Build result text for this question
            result_text = f"Question {i+1}: {'✅ Correct' if is_correct else '❌ Incorrect'}\n"
            result_text += f"Q: {question_data['question']}\n"
            result_text += f"Your answer: {user_answer if user_answer is not None else 'No answer'}\n"
            
            if not is_correct:
                # Find the correct choice text
                correct_choice_text = ""
                for choice in question_data['choices']:
                    if question_data['answer'] in choice:
                        correct_choice_text = choice
                        break
                result_text += f"Correct answer: {correct_choice_text}\n"
                result_text += f"Explanation: {question_data['explanation']}\n"
            
            result_text += "---\n"
            results_text_parts.append(result_text)
            
            # Store structured result
            question_results.append({
                "question_num": i + 1,
                "question": question_data["question"],
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct,
                "explanation": question_data["explanation"] if not is_correct else None
            })
        
        total = len(self._quiz_data)
        percentage = int((correct_count / total) * 100) if total > 0 else 0
        
        score_text = f"Your score: {correct_count}/{total} ({percentage}%)\n\n"
        full_result = score_text + "".join(results_text_parts)
        
        return QuizResult(
            score=correct_count,
            total=total,
            percentage=percentage,
            results_text=full_result,
            question_results=question_results
        )
    
    @property
    def quiz_data(self) -> List[dict]:
        """Get the current quiz data."""
        return self._quiz_data
    
    @property
    def current_index(self) -> int:
        """Get the current question index."""
        return self._current_index
    
    @property
    def user_answers(self) -> List[Optional[str]]:
        """Get the user's answers."""
        return self._user_answers


