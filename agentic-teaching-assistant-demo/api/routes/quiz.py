"""
Quiz Routes

Handles quiz generation and submission.
"""

import os
import sys
import random
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from common.debug import get_debug_logger
from api.schemas.quiz import (
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizQuestion,
    QuizSubmitRequest,
    QuizSubmitResponse,
)

router = APIRouter()
logger = get_debug_logger(__name__)

# Default paths - use /workspace/mnt/ for NVIDIA VPN environment
SAVE_TO = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")

# Mock quiz store
_mock_quizzes = {}


def _get_backend():
    """Lazy load backend functions."""
    try:
        from nodes import init_user_storage, load_user_state, add_quiz_to_subtopic, update_subtopic_status
        from states import Status, convert_to_json_safe
        return {
            "init_user_storage": init_user_storage,
            "load_user_state": load_user_state,
            "add_quiz_to_subtopic": add_quiz_to_subtopic,
            "update_subtopic_status": update_subtopic_status,
            "Status": Status,
            "convert_to_json_safe": convert_to_json_safe,
            "available": True,
        }
    except ImportError:
        return {"available": False}


LABELS = ["A", "B", "C", "D"]


def _convert_llm_quiz_to_frontend(quiz: dict) -> QuizQuestion:
    """
    Convert LLM quiz format to frontend format.
    LLM returns: answer="A", choices=["(A) ...", "(B) ...", ...]
    Frontend: choices are labelled "A) ...", answer stores the label letter ("A").
    Users submit by letter (A/B/C/D) or numeric index (0/1/2/3).
    """
    choices = quiz.get("choices", [])
    answer_letter = quiz.get("answer", "A").strip().upper()

    # Map letter to index
    letter_to_idx = {"A": 0, "B": 1, "C": 2, "D": 3}
    answer_idx = letter_to_idx.get(answer_letter, 0)

    # Strip any existing prefix then re-label as "A) text"
    labelled_choices = []
    for i, choice in enumerate(choices):
        cleaned = choice.strip()
        # Remove patterns like "(A) ", "A. ", "A) "
        if len(cleaned) > 3 and cleaned[0] == '(' and cleaned[2] == ')':
            cleaned = cleaned[4:].strip()
        elif len(cleaned) > 2 and cleaned[1] in '.):':
            cleaned = cleaned[2:].strip()
        label = LABELS[i] if i < len(LABELS) else str(i)
        labelled_choices.append(f"{label}) {cleaned}")

    # Store the answer as the letter ("A", "B", …) so submit accepts letters
    answer_label = LABELS[answer_idx] if answer_idx < len(LABELS) else "A"

    return QuizQuestion(
        question=quiz.get("question", ""),
        choices=labelled_choices if labelled_choices else ["A) Option A", "B) Option B", "C) Option C", "D) Option D"],
        answer=answer_label,
        explanation=quiz.get("thought_process", "") or quiz.get("explanation", ""),
    )


def _get_mock_questions(subtopic_number: int, subtopic_title: str = "") -> List[QuizQuestion]:
    """Get mock quiz questions dynamically based on the topic."""
    topic = subtopic_title or f"Topic {subtopic_number + 1}"
    return [
        QuizQuestion(
            question=f"What is the main concept covered in '{topic}'?",
            choices=[
                "A historical overview only",
                "The core principles and key ideas",
                "Only technical implementation details",
                "Unrelated background information"
            ],
            answer="The core principles and key ideas",
            explanation=f"This section focuses on understanding the fundamental concepts of {topic}.",
        ),
        QuizQuestion(
            question=f"Why is understanding '{topic}' important?",
            choices=[
                "It's not particularly important",
                "It provides foundational knowledge for further learning",
                "It's only useful for exams",
                "It's outdated information"
            ],
            answer="It provides foundational knowledge for further learning",
            explanation="Understanding core concepts helps build a strong foundation for advanced topics.",
        ),
        QuizQuestion(
            question=f"What approach should you take when studying '{topic}'?",
            choices=[
                "Memorize everything without understanding",
                "Skip the difficult parts",
                "Focus on understanding key concepts and their applications",
                "Only read the summary"
            ],
            answer="Focus on understanding key concepts and their applications",
            explanation="Active learning and understanding concepts leads to better retention and application.",
        ),
    ]


@router.get("/subtopics/{user_id}")
async def list_subtopics(user_id: str):
    """
    List all subtopics with their indices so the caller can pick a subtopic_number
    for quiz generation or chat.

    Example response:
        {
          "chapter": "Skills for Claude",
          "subtopics": [
            {"index": 0, "name": "Introduction to Claude Skills", "status": "started"},
            {"index": 1, "name": "Modularity and Orchestration",  "status": "not_started"},
            ...
          ]
        }
    """
    try:
        from fast_store import get_store
        fs = get_store(SAVE_TO)
        chapter_name = fs.read_meta(user_id, "ACTIVE_CHAPTER_NAME")
        subtopic_list = fs.read_subtopic_list(user_id)
        if subtopic_list:
            return {
                "chapter": chapter_name,
                "subtopics": [
                    {"index": i, "name": st.get("name", ""), "status": st.get("status", "")}
                    for i, st in enumerate(subtopic_list)
                ],
            }
    except Exception as _fse:
        logger.warning("fast_store unavailable for subtopic list: %s", _fse)

    # JSON fallback
    backend = _get_backend()
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        user_state = backend["load_user_state"](user_id)
        if user_state:
            curriculum = (user_state.get("curriculum") or [{}])[0]
            active_chapter = curriculum.get("active_chapter") or {}
            chapter_name = active_chapter.get("name", "") if isinstance(active_chapter, dict) else getattr(active_chapter, "name", "")
            sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else getattr(active_chapter, "sub_topics", [])
            return {
                "chapter": chapter_name,
                "subtopics": [
                    {
                        "index": i,
                        "name": (st.get("sub_topic", "") if isinstance(st, dict) else getattr(st, "sub_topic", "")),
                        "status": str(st.get("status", "") if isinstance(st, dict) else getattr(st, "status", "")),
                    }
                    for i, st in enumerate(sub_topics)
                ],
            }

    raise HTTPException(status_code=404, detail=f"No curriculum found for user '{user_id}'. Generate a curriculum first.")


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(request: QuizGenerateRequest):
    """
    Generate quiz questions for a subtopic.
    Use GET /api/quiz/subtopics/{user_id} first to see available subtopic indices.
    """
    subtopic_idx = request.subtopic_number
    subtopic_title = ""

    # ── fast_store path ───────────────────────────────────────────────────────
    try:
        from fast_store import get_store
        fs = get_store(SAVE_TO)
        subtopic_list = fs.read_subtopic_list(request.user_id)
        if subtopic_list and subtopic_idx < len(subtopic_list):
            subtopic_title = subtopic_list[subtopic_idx].get("name", "")

        study_material_text = fs.read_material(request.user_id, subtopic_idx)
        existing_quizzes = fs.read_quizzes(request.user_id, subtopic_idx)

        if existing_quizzes:
            questions = [
                QuizQuestion(
                    question=q.get("question", ""),
                    choices=q.get("choices", []),
                    answer=q.get("answer", ""),
                    explanation=q.get("explanation", ""),
                )
                for q in existing_quizzes
            ]
            return QuizGenerateResponse(
                success=True,
                questions=questions,
                message=f"Existing quiz for subtopic {subtopic_idx}: '{subtopic_title}'",
            )

        try:
            from standalone_quizes_gen import get_quiz, quiz_output_parser
            raw_output = get_quiz(
                title=subtopic_title,
                document_summary=f"Study material for: {subtopic_title}",
                chunk_text=study_material_text[:2000] if study_material_text else "",
                additional_instruction="Generate 3 multiple-choice questions.",
            )
            parsed_questions = quiz_output_parser(raw_output)
            if parsed_questions:
                questions = [_convert_llm_quiz_to_frontend(q) for q in parsed_questions]
                return QuizGenerateResponse(
                    success=True,
                    questions=questions,
                    message=f"Generated {len(questions)} questions for subtopic {subtopic_idx}: '{subtopic_title}'",
                )
        except ImportError:
            pass
        except Exception as e:
            logger.exception("Quiz generation error")
            raise HTTPException(status_code=503, detail=f"Quiz generation failed: {str(e)}") from e

    except HTTPException:
        raise
    except Exception as _fse:
        logger.warning("fast_store unavailable for quiz generate, falling back to JSON: %s", _fse)

    # ── JSON fallback ─────────────────────────────────────────────────────────
    backend = _get_backend()
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, request.user_id)

        user_state = backend["load_user_state"](request.user_id)
        if not user_state:
            raise HTTPException(status_code=404, detail=f"User '{request.user_id}' not found")

        curriculum_list = user_state.get("curriculum", [])
        if not curriculum_list:
            raise HTTPException(status_code=404, detail="No curriculum found")

        curriculum = curriculum_list[0]
        active_chapter = curriculum.get("active_chapter")
        if not active_chapter:
            raise HTTPException(status_code=404, detail="No active chapter found")

        sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else getattr(active_chapter, "sub_topics", [])

        if not sub_topics or subtopic_idx >= len(sub_topics):
            raise HTTPException(status_code=404, detail=f"Subtopic {subtopic_idx} not found")

        subtopic = sub_topics[subtopic_idx]
        subtopic_title = subtopic.get("sub_topic", "") if isinstance(subtopic, dict) else getattr(subtopic, "sub_topic", "")
        existing_quizzes = subtopic.get("quizzes", []) if isinstance(subtopic, dict) else getattr(subtopic, "quizzes", [])
        
        if existing_quizzes:
            questions = [
                QuizQuestion(
                    question=q.get("question", ""),
                    choices=q.get("choices", []),
                    answer=q.get("answer", ""),
                    explanation=q.get("explanation", ""),
                )
                for q in existing_quizzes
            ]
            return QuizGenerateResponse(
                success=True,
                questions=questions,
                message="Returning existing quiz questions",
            )
        
        try:
            from standalone_quizes_gen import get_quiz, quiz_output_parser
            
            study_material = subtopic.get("study_material", "") if isinstance(subtopic, dict) else getattr(subtopic, "study_material", "")
            
            raw_output = get_quiz(
                title=subtopic_title,
                document_summary=f"Study material for: {subtopic_title}",
                chunk_text=study_material[:2000] if study_material else "",
                additional_instruction="Generate 3 multiple-choice questions.",
            )
            
            parsed_questions = quiz_output_parser(raw_output)
            
            if not parsed_questions:
                raise ValueError("Failed to parse quiz output")
            
            # Convert LLM format (answer="A") to frontend format (answer="Full text")
            questions = [_convert_llm_quiz_to_frontend(q) for q in parsed_questions]
            
            # Save the CONVERTED questions (with full text answers) to match submission format
            for converted_q in questions:
                await backend["add_quiz_to_subtopic"](
                    user_id=request.user_id,
                    save_to=SAVE_TO,
                    subtopic_number=request.subtopic_number,
                    quiz=converted_q.model_dump(),  # Convert Pydantic model to dict
                )
            
            return QuizGenerateResponse(
                success=True,
                questions=questions,
                message=f"Generated {len(questions)} quiz questions",
            )
            
        except ImportError:
            pass
        except Exception as e:
            logger.exception("Quiz generation error")
            raise HTTPException(
                status_code=503,
                detail=f"Quiz generation failed: {str(e)}",
            ) from e
    
    # Return mock questions with topic context
    mock_questions = _get_mock_questions(request.subtopic_number, subtopic_title)
    
    # Store for later verification
    key = f"{request.user_id}:{request.subtopic_number}"
    _mock_quizzes[key] = mock_questions
    
    return QuizGenerateResponse(
        success=True,
        questions=mock_questions,
        message="Generated mock quiz questions",
    )


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_quiz(request: QuizSubmitRequest):
    """
    Submit quiz answers and check results.
    """
    backend = _get_backend()
    key = f"{request.user_id}:{request.subtopic_number}"
    
    # Get quizzes
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, request.user_id)
        
        user_state = backend["load_user_state"](request.user_id)
        if not user_state:
            raise HTTPException(status_code=404, detail=f"User '{request.user_id}' not found")
        
        curriculum_list = user_state.get("curriculum", [])
        if not curriculum_list:
            raise HTTPException(status_code=404, detail="No curriculum found")
        
        curriculum = curriculum_list[0]
        active_chapter = curriculum.get("active_chapter")
        
        if not active_chapter:
            raise HTTPException(status_code=404, detail="No active chapter found")
        
        sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else getattr(active_chapter, "sub_topics", [])
        
        if not sub_topics or request.subtopic_number >= len(sub_topics):
            raise HTTPException(status_code=404, detail=f"Subtopic {request.subtopic_number} not found")
        
        subtopic = sub_topics[request.subtopic_number]
        quizzes = subtopic.get("quizzes", []) if isinstance(subtopic, dict) else getattr(subtopic, "quizzes", [])
    else:
        quizzes = _mock_quizzes.get(key, [])
        if not quizzes:
            quizzes = _get_mock_questions(request.subtopic_number)
    
    if not quizzes:
        raise HTTPException(status_code=400, detail="No quizzes found. Generate quizzes first.")
    
    # Convert QuizQuestion objects to dicts if needed
    quiz_list = []
    for q in quizzes:
        if isinstance(q, QuizQuestion):
            quiz_list.append({"answer": q.answer, "choices": q.choices})
        elif isinstance(q, dict):
            quiz_list.append(q)
        else:
            quiz_list.append({"answer": getattr(q, "answer", ""), "choices": getattr(q, "choices", [])})

    def _resolve_answer(user_ans: str, choices: list) -> str:
        """Normalise user answer to letter (A/B/C/D).
        Accepts: 'A', 'b', '0', '1', '2', '3', or full choice text."""
        ua = user_ans.strip()
        # Numeric index → letter
        if ua.isdigit():
            idx = int(ua)
            return LABELS[idx] if idx < len(LABELS) else ua.upper()
        # Single letter
        if len(ua) == 1 and ua.upper() in LABELS:
            return ua.upper()
        # Full text match against labelled choices (e.g. "A) Workflow")
        for i, ch in enumerate(choices):
            if ua.lower() == ch.lower() or ua.lower() == ch[3:].lower():
                return LABELS[i] if i < len(LABELS) else ua.upper()
        return ua.upper()

    # Check answers
    correct_count = 0
    total = min(len(quiz_list), len(request.answers))
    feedback_list = []

    for i in range(total):
        correct_answer = quiz_list[i].get("answer", "").strip().upper()
        choices = quiz_list[i].get("choices", [])
        user_answer = _resolve_answer(request.answers[i], choices)
        is_correct = user_answer == correct_answer

        # Find the full text of the correct choice for feedback
        correct_idx = LABELS.index(correct_answer) if correct_answer in LABELS else -1
        correct_text = choices[correct_idx] if correct_idx >= 0 and correct_idx < len(choices) else correct_answer

        if is_correct:
            correct_count += 1
            feedback_list.append(f"Question {i+1}: Correct!")
        else:
            feedback_list.append(f"Question {i+1}: Incorrect. The correct answer was {correct_text}.")
    
    passed = correct_count == total
    
    # Update status if passed
    if passed and backend["available"]:
        try:
            await backend["update_subtopic_status"](
                user_id=request.user_id,
                save_to=SAVE_TO,
                subtopic_number=request.subtopic_number,
                new_status=backend["Status"].COMPLETED,
                feedback=feedback_list,
            )
        except Exception as e:
            logger.warning("Failed to update subtopic status: %s", e)
    
    return QuizSubmitResponse(
        success=True,
        correct=correct_count,
        total=total,
        passed=passed,
        feedback=feedback_list,
        message="All correct! Subtopic completed." if passed else f"You got {correct_count}/{total} correct. Try again!",
    )


@router.get("/{user_id}/subtopic/{subtopic_number}", response_model=QuizGenerateResponse)
async def get_subtopic_quiz(user_id: str, subtopic_number: int):
    """
    Get existing quiz questions for a subtopic.
    """
    backend = _get_backend()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        user_state = backend["load_user_state"](user_id)
        if not user_state:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        curriculum_list = user_state.get("curriculum", [])
        if not curriculum_list:
            raise HTTPException(status_code=404, detail="No curriculum found")
        
        curriculum = curriculum_list[0]
        active_chapter = curriculum.get("active_chapter")
        
        if not active_chapter:
            raise HTTPException(status_code=404, detail="No active chapter found")
        
        sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else getattr(active_chapter, "sub_topics", [])
        
        if not sub_topics or subtopic_number >= len(sub_topics):
            raise HTTPException(status_code=404, detail=f"Subtopic {subtopic_number} not found")
        
        subtopic = sub_topics[subtopic_number]
        quizzes = subtopic.get("quizzes", []) if isinstance(subtopic, dict) else getattr(subtopic, "quizzes", [])
        
        if quizzes:
            questions = [
                QuizQuestion(
                    question=q.get("question", ""),
                    choices=q.get("choices", []),
                    answer=q.get("answer", ""),
                    explanation=q.get("explanation", ""),
                )
                for q in quizzes
            ]
            return QuizGenerateResponse(
                success=True,
                questions=questions,
                message=f"Found {len(questions)} existing quiz questions",
            )
    
    # Check mock store
    key = f"{user_id}:{subtopic_number}"
    mock_quizzes = _mock_quizzes.get(key, [])
    
    if mock_quizzes:
        return QuizGenerateResponse(
            success=True,
            questions=mock_quizzes,
            message="Found mock quiz questions",
        )
    
    return QuizGenerateResponse(
        success=True,
        questions=[],
        message="No quizzes found. Generate new ones.",
    )


@router.get("/{user_id}/final", response_model=QuizGenerateResponse)
async def get_final_quiz(user_id: str, max_questions: int = 5):
    """
    Generate final quiz based on ALL completed study materials.
    Creates NEW comprehensive questions from all chapters and subtopics.
    Default: 5 questions for final assessment.
    """
    backend = _get_backend()
    all_questions = []
    
    # Try to generate questions from all completed study materials
    if backend["available"]:
        try:
            user_state = backend["load_user_state"](user_id)
            if user_state and "curriculum" in user_state:
                curriculum_list = user_state.get("curriculum", [])
                if curriculum_list and len(curriculum_list) > 0:
                    curriculum = curriculum_list[0]
                    study_plan = curriculum.get("study_plan", {})
                    chapters = study_plan.get("study_plan", []) if isinstance(study_plan, dict) else getattr(study_plan, "study_plan", [])
                    
                    # Collect all study materials from ALL chapters (including completed and started)
                    all_study_materials = []
                    logger.debug("Scanning %d chapters for study materials", len(chapters))
                    
                    for idx, chapter in enumerate(chapters):
                        chapter_dict = chapter if isinstance(chapter, dict) else chapter.__dict__
                        chapter_name = chapter_dict.get("name", f"Chapter {idx}")
                        sub_topics = chapter_dict.get("sub_topics", [])
                        
                        logger.debug("Chapter %d '%s' - %d subtopics", idx, chapter_name, len(sub_topics))
                        
                        # Include materials from chapters that have been processed (have sub_topics)
                        if sub_topics and len(sub_topics) > 0:
                            for st_idx, subtopic in enumerate(sub_topics):
                                st_dict = subtopic if isinstance(subtopic, dict) else subtopic.__dict__
                                study_material = st_dict.get("study_material", "")
                                subtopic_title = st_dict.get("sub_topic", "Unknown")
                                subtopic_status = st_dict.get("status", "NA")
                                
                                # Include ALL subtopics with study materials (not just completed)
                                if study_material:
                                    all_study_materials.append({
                                        "title": subtopic_title,
                                        "content": study_material[:3000],  # Increased to 3000 chars
                                        "chapter": chapter_name,
                                    })
                                    logger.debug(
                                        "Subtopic %d '%s' (%s) - %d chars",
                                        st_idx,
                                        subtopic_title,
                                        subtopic_status,
                                        len(study_material),
                                    )
                                else:
                                    logger.debug(
                                        "Subtopic %d '%s' (%s) - NO MATERIAL",
                                        st_idx,
                                        subtopic_title,
                                        subtopic_status,
                                    )
                    
                    # Generate comprehensive final quiz questions
                    logger.debug("Collected %d study materials for final quiz", len(all_study_materials))
                    
                    if all_study_materials and len(all_study_materials) > 0:
                        from standalone_quizes_gen import get_quiz, quiz_output_parser
                        
                        # Combine all study materials for context
                        # Use ALL materials, not just first 5
                        combined_context = "\n\n".join([
                            f"Chapter: {mat['chapter']}\nTopic: {mat['title']}\n{mat['content']}" 
                            for mat in all_study_materials
                        ])
                        
                        logger.debug(
                            "Generating %d final quiz questions from combined materials",
                            max_questions,
                        )
                        logger.debug("Combined context length: %d characters", len(combined_context))
                        logger.debug("Using materials from %d subtopics", len(all_study_materials))
                        
                        try:
                            raw_output = get_quiz(
                                title="Final Assessment - Comprehensive Evaluation",
                                document_summary=f"Final assessment covering all {len(all_study_materials)} topics across {len(chapters)} chapters",
                                chunk_text=combined_context,
                                additional_instruction=f"Generate EXACTLY {max_questions} challenging multiple-choice questions that test comprehensive understanding across ALL topics covered in the study materials. Draw questions from different topics to ensure breadth. Each question MUST have 4 answer choices with clear explanations.",
                            )
                        except Exception:
                            logger.exception("LLM call failed for final quiz")
                            raw_output = None
                        
                        logger.debug(
                            "LLM raw output length: %d characters",
                            len(raw_output) if raw_output else 0,
                        )
                        
                        if raw_output and len(raw_output) > 10:
                            try:
                                parsed_questions = quiz_output_parser(raw_output)
                                logger.debug(
                                    "Parsed %d questions from LLM output",
                                    len(parsed_questions) if parsed_questions else 0,
                                )
                            except Exception as parse_error:
                                logger.warning("Quiz parsing failed: %s", parse_error)
                                logger.debug("Raw output sample: %s", raw_output[:500])
                                parsed_questions = None
                            
                            if parsed_questions and len(parsed_questions) > 0:
                                # Convert to frontend format
                                all_questions = [_convert_llm_quiz_to_frontend(q) for q in parsed_questions]
                                logger.debug(
                                    "Final quiz generated successfully: %d questions",
                                    len(all_questions),
                                )
                                # Return immediately to prevent fallback to generic questions
                                return QuizGenerateResponse(
                                    success=True,
                                    questions=all_questions if len(all_questions) <= max_questions else random.sample(all_questions, max_questions),
                                    message=f"Final quiz with {len(all_questions)} questions from your study materials",
                                )
                            else:
                                logger.warning("Quiz parsing returned empty list - raw output may be malformed")
                                logger.debug(
                                    "Raw output preview: %s",
                                    raw_output[:500] if raw_output else "None",
                                )
                        else:
                            logger.warning("LLM returned empty output - check LLM configuration and API keys")
                    else:
                        logger.warning("No study materials found in any chapter - check processing state")
        except Exception:
            logger.exception("Error generating final quiz from backend")
    
    # Also check mock quizzes
    for key, questions in _mock_quizzes.items():
        if key.startswith(f"{user_id}_"):
            all_questions.extend(questions)
    
    if not all_questions:
        # Generate mock final quiz questions
        all_questions = [
            QuizQuestion(
                question="What is the primary purpose of this course material?",
                choices=[
                    "Entertainment only",
                    "To provide comprehensive understanding of the subject",
                    "To memorize facts without context",
                    "None of the above"
                ],
                answer="To provide comprehensive understanding of the subject",
                explanation="Course materials are designed to provide comprehensive understanding, not just entertainment or memorization.",
            ),
            QuizQuestion(
                question="Which learning approach is most emphasized in this curriculum?",
                choices=[
                    "Passive reading",
                    "Active engagement and practice",
                    "Watching videos only",
                    "Skipping to quizzes"
                ],
                answer="Active engagement and practice",
                explanation="Active engagement leads to better retention and understanding compared to passive learning methods.",
            ),
            QuizQuestion(
                question="What should you do after completing all subtopics?",
                choices=[
                    "Immediately forget everything",
                    "Review and take the final assessment",
                    "Skip the final quiz",
                    "Start a completely new topic"
                ],
                answer="Review and take the final assessment",
                explanation="Taking a final assessment helps consolidate your learning and identify any gaps in understanding.",
            ),
        ]
    
    # If we get here, no real questions were generated - use fallback generic questions
    logger.warning("Falling back to generic final quiz questions (no study materials found or LLM failed)")
    
    # Limit to max_questions, randomly sample if needed
    if len(all_questions) > max_questions:
        all_questions = random.sample(all_questions, max_questions)
    
    return QuizGenerateResponse(
        success=True,
        questions=all_questions,
        message=f"Final quiz with {len(all_questions)} generic questions (study materials not available)",
    )
