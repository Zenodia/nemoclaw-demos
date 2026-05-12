"""
Curriculum Service - Gradio-agnostic curriculum business logic.

This service handles curriculum loading, flattening, and study material retrieval.
It returns DTOs that can be converted to any UI framework format.

Phase 1: Core helper functions (no state mutation)
- get_curriculum_from_user_state()
- flatten_curriculum()
- get_study_material_for_subtopic()

Usage:
    from services.curriculum_service import CurriculumService
    
    svc = CurriculumService(mnt_folder="/path/to/mnt")
    curriculum = svc.get_curriculum_from_user_state("username")
    flat_topics = svc.flatten_curriculum(curriculum)
"""
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from colorama import Fore
from nodes import load_user_state, init_user_storage, save_user_state
from states import StudyPlan, Chapter, SubTopic, Status
from standalone_quizes_gen import get_quiz, quiz_output_parser


@dataclass
class StudyMaterialInfo:
    """Study material information for a subtopic."""
    chapter_number: int
    chapter_name: str
    subtopic_index: int
    subtopic_name: str
    study_material: str
    display_markdown: str
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class TopicCompletionResult:
    """Result of marking a topic as complete."""
    success: bool
    topic_name: str
    is_subtopic: bool
    completed_topics: Set[str]
    unlocked_topics: Set[str]
    study_material: Optional[StudyMaterialInfo] = None
    quiz_data: Optional[List[dict]] = None
    quiz_generated: bool = False
    next_unlocked_topic: Optional[str] = None
    error_message: Optional[str] = None


class CurriculumService:
    """
    Gradio-agnostic curriculum service.
    
    Provides methods for curriculum operations without UI dependencies.
    All methods return plain Python objects or DTOs, not Gradio components.
    """
    
    def __init__(self, mnt_folder: str):
        """
        Initialize CurriculumService.
        
        Args:
            mnt_folder: Path to the mnt folder for user data storage
        """
        self.mnt_folder = mnt_folder
    
    def get_curriculum_from_user_state(self, username: str) -> List[Any]:
        """
        Load and convert curriculum from user state JSON file.
        
        Returns a list in the format:
        - Simple topic: "1:Chapter Name"
        - Topic with subtopics: {"topic": "1:Chapter Name", "subtopics": ["Sub1", "Sub2"]}
        
        Args:
            username: The username to load curriculum for
            
        Returns:
            List of curriculum items (strings or dicts with subtopics)
        """
        try:
            user_state = load_user_state(username)
            if not user_state or "curriculum" not in user_state or len(user_state["curriculum"]) == 0:
                return []
            
            curriculum_data = user_state["curriculum"][0]
            if "study_plan" not in curriculum_data:
                return []
            
            study_plan = curriculum_data["study_plan"]
            active_chapter = curriculum_data.get("active_chapter")
            
            # Handle both dict and StudyPlan object
            if isinstance(study_plan, dict) and "study_plan" in study_plan:
                chapters = study_plan["study_plan"]
            elif isinstance(study_plan, StudyPlan):
                chapters = study_plan.study_plan
            else:
                return []
            
            # Get active chapter number and subtopics
            if active_chapter:
                if isinstance(active_chapter, dict):
                    active_chapter_num = active_chapter.get("number", -1)
                    active_chapter_subtopics = active_chapter.get("sub_topics", [])
                else:
                    active_chapter_num = active_chapter.number
                    active_chapter_subtopics = active_chapter.sub_topics
            else:
                active_chapter_num = -1
                active_chapter_subtopics = []
            
            # Convert to curriculum format
            result = []
            for chapter in chapters:
                # Handle both dict and Chapter object
                if isinstance(chapter, dict):
                    chapter_num = chapter.get("number", 0)
                    chapter_name = chapter.get("name", "")
                    sub_topics = chapter.get("sub_topics", [])
                else:
                    chapter_num = chapter.number
                    chapter_name = chapter.name
                    sub_topics = chapter.sub_topics
                
                # If this is the active chapter and study_plan has no subtopics, use active_chapter's subtopics
                if chapter_num == active_chapter_num and (not sub_topics or len(sub_topics) == 0):
                    sub_topics = active_chapter_subtopics
                
                # Build chapter label with number
                chapter_label = f"{chapter_num}:{chapter_name}"
                
                # If chapter has subtopics, create hierarchical structure
                if sub_topics and len(sub_topics) > 0:
                    subtopic_names = []
                    for st in sub_topics[:10]:  # Max 10 subtopics
                        if isinstance(st, dict):
                            subtopic_text = st.get("sub_topic", "").strip()
                        else:
                            subtopic_text = st.sub_topic.strip()
                        # Strip numbering
                        subtopic_text = re.sub(r'^\n?\d+:\s*', '', subtopic_text).strip()
                        subtopic_names.append(subtopic_text)
                    
                    result.append({
                        "topic": chapter_label,
                        "subtopics": subtopic_names
                    })
                else:
                    # Simple chapter without subtopics
                    result.append(chapter_label)
            
            return result
        except Exception as e:
            print(Fore.RED + f"Error loading curriculum from user state: {e}" + Fore.RESET)
            import traceback
            traceback.print_exc()
            return []
    
    def flatten_curriculum(self, curriculum: List[Any]) -> List[str]:
        """
        Flatten a hierarchical curriculum into a list of topic names.
        
        Subtopics are prefixed with "  ↳ " for display.
        
        Args:
            curriculum: List from get_curriculum_from_user_state()
            
        Returns:
            Flattened list of topic names
        """
        flat = []
        for item in curriculum:
            if isinstance(item, dict):
                flat.append(item["topic"])
                for subtopic in item.get("subtopics", []):
                    flat.append(f"  ↳ {subtopic}")
            else:
                flat.append(item)
        return flat
    
    def get_study_material_for_subtopic(
        self, 
        username: str, 
        topic_name: str
    ) -> StudyMaterialInfo:
        """
        Get study material for a specific subtopic.
        
        Args:
            username: The username
            topic_name: The topic name (may include "  ↳ " prefix for subtopics)
            
        Returns:
            StudyMaterialInfo with study material and metadata
        """
        # Default error response
        error_result = StudyMaterialInfo(
            chapter_number=0,
            chapter_name="Unknown",
            subtopic_index=-1,
            subtopic_name=topic_name,
            study_material="No study material available.",
            display_markdown="No study material available.",
            success=False,
            error_message="Could not find study material"
        )
        
        # Only process subtopics
        if not topic_name.startswith("  ↳ "):
            error_result.error_message = "Not a subtopic"
            return error_result
        
        try:
            user_state = load_user_state(username)
            
            if not user_state or "curriculum" not in user_state or len(user_state["curriculum"]) == 0:
                error_result.error_message = "No curriculum found"
                return error_result
            
            active_chapter = user_state["curriculum"][0].get("active_chapter")
            if not active_chapter:
                error_result.error_message = "No active chapter"
                return error_result
            
            # Strip prefix and numbering from topic name
            subtopic_name = topic_name.replace("  ↳ ", "").strip()
            subtopic_name = re.sub(r'^\d+:\s*', '', subtopic_name).strip()
            
            # Get chapter info
            if isinstance(active_chapter, dict):
                chapter_number = active_chapter.get("number", 0)
                chapter_name = active_chapter.get("name", "Unknown")
                sub_topics = active_chapter.get("sub_topics", [])
            else:
                chapter_number = active_chapter.number
                chapter_name = active_chapter.name
                sub_topics = active_chapter.sub_topics
            
            # Find the matching subtopic
            for idx, subtopic in enumerate(sub_topics):
                # Handle both dict and object formats
                if isinstance(subtopic, dict):
                    raw_subtopic = subtopic.get("sub_topic", "")
                    study_material = subtopic.get("display_markdown") or subtopic.get("study_material", "No study material available.")
                else:
                    raw_subtopic = subtopic.sub_topic
                    study_material = getattr(subtopic, 'display_markdown', None) or getattr(subtopic, 'study_material', "No study material available.")
                
                subtopic_text = re.sub(r'^\n?\d+:\s*', '', raw_subtopic.strip()).strip()
                
                if subtopic_name in subtopic_text or subtopic_text in subtopic_name:
                    # Format the study material markdown
                    display_markdown = f"""
### Chapter {chapter_number}: {chapter_name}

#### Study Topic #{idx + 1}: {subtopic_text}

**Study Material:**

{study_material}"""
                    
                    return StudyMaterialInfo(
                        chapter_number=chapter_number,
                        chapter_name=chapter_name,
                        subtopic_index=idx,
                        subtopic_name=subtopic_text,
                        study_material=study_material,
                        display_markdown=display_markdown,
                        success=True
                    )
            
            error_result.error_message = f"Subtopic '{subtopic_name}' not found in active chapter"
            return error_result
            
        except Exception as e:
            print(Fore.RED + f"Error getting study material: {e}" + Fore.RESET)
            import traceback
            traceback.print_exc()
            error_result.error_message = str(e)
            return error_result
    
    def get_topic_status(
        self,
        curriculum: List[Any],
        unlocked_topics: Set[str],
        completed_topics: Set[str]
    ) -> List[Dict[str, Any]]:
        """
        Get status information for all topics in the curriculum.
        
        Args:
            curriculum: List from get_curriculum_from_user_state()
            unlocked_topics: Set of unlocked topic names
            completed_topics: Set of completed topic names
            
        Returns:
            List of dicts with topic info: {name, is_subtopic, is_completed, is_unlocked, is_visible}
        """
        flat_topics = self.flatten_curriculum(curriculum)
        result = []
        
        for topic in flat_topics:
            is_subtopic = topic.startswith("  ↳ ")
            is_completed = topic in completed_topics
            is_unlocked = topic in unlocked_topics or len(unlocked_topics) == 0
            
            result.append({
                "name": topic,
                "is_subtopic": is_subtopic,
                "is_completed": is_completed,
                "is_unlocked": is_unlocked,
                "is_visible": True  # All topics visible for now
            })
        
        return result
    
    def find_next_incomplete_topic(
        self,
        curriculum: List[Any],
        completed_topics: Set[str]
    ) -> Optional[str]:
        """
        Find the next topic that hasn't been completed.
        
        Args:
            curriculum: List from get_curriculum_from_user_state()
            completed_topics: Set of completed topic names
            
        Returns:
            Name of next incomplete topic, or None if all complete
        """
        flat_topics = self.flatten_curriculum(curriculum)
        
        for topic in flat_topics:
            if topic not in completed_topics:
                return topic
        
        return None
    
    def calculate_progress(
        self,
        curriculum: List[Any],
        completed_topics: Set[str]
    ) -> Tuple[int, int, float]:
        """
        Calculate progress through the curriculum.
        
        Args:
            curriculum: List from get_curriculum_from_user_state()
            completed_topics: Set of completed topic names
            
        Returns:
            Tuple of (completed_count, total_count, percentage)
        """
        flat_topics = self.flatten_curriculum(curriculum)
        total = len(flat_topics)
        
        if total == 0:
            return (0, 0, 0.0)
        
        completed = sum(1 for topic in flat_topics if topic in completed_topics)
        percentage = (completed / total) * 100
        
        return (completed, total, percentage)
    
    # =========================================================================
    # Phase 2: Topic Completion Methods (state mutations)
    # =========================================================================
    
    def mark_topic_complete(
        self,
        username: str,
        topic_name: str,
        completed_topics: Set[str],
        unlocked_topics: Set[str],
        generate_quiz: bool = True
    ) -> TopicCompletionResult:
        """
        Mark a topic as complete and handle related operations.
        
        For subtopics:
        - Updates user state with COMPLETED status
        - Generates quiz if not already generated (and generate_quiz=True)
        - Returns study material
        - Unlocks next subtopic in same chapter
        
        Args:
            username: The username
            topic_name: The topic name (may include "  ↳ " prefix)
            completed_topics: Current set of completed topics
            unlocked_topics: Current set of unlocked topics
            generate_quiz: Whether to generate quiz for subtopics
            
        Returns:
            TopicCompletionResult with updated state and quiz data
        """
        new_completed = set(completed_topics)
        new_unlocked = set(unlocked_topics)
        
        # Add to completed
        new_completed.add(topic_name)
        
        is_subtopic = topic_name.startswith("  ↳ ")
        
        result = TopicCompletionResult(
            success=True,
            topic_name=topic_name,
            is_subtopic=is_subtopic,
            completed_topics=new_completed,
            unlocked_topics=new_unlocked
        )
        
        if not is_subtopic:
            # Simple topic, just return updated sets
            return result
        
        # Handle subtopic completion
        try:
            # Get study material
            study_info = self.get_study_material_for_subtopic(username, topic_name)
            if study_info.success:
                result.study_material = study_info
            
            # Load and update user state
            user_state = load_user_state(username)
            if not user_state or "curriculum" not in user_state or len(user_state["curriculum"]) == 0:
                result.error_message = "User state not found"
                return result
            
            active_chapter = user_state["curriculum"][0].get("active_chapter")
            if not active_chapter:
                result.error_message = "No active chapter"
                return result
            
            # Strip prefix from topic name
            subtopic_name = topic_name.replace("  ↳ ", "").strip()
            subtopic_name = re.sub(r'^\d+:\s*', '', subtopic_name).strip()
            
            # Get chapter info
            if isinstance(active_chapter, dict):
                sub_topics = active_chapter.get("sub_topics", [])
            else:
                sub_topics = active_chapter.sub_topics
            
            # Find matching subtopic and update
            for idx, subtopic in enumerate(sub_topics):
                if isinstance(subtopic, dict):
                    raw_subtopic = subtopic.get("sub_topic", "")
                else:
                    raw_subtopic = subtopic.sub_topic
                
                subtopic_text = re.sub(r'^\n?\d+:\s*', '', raw_subtopic.strip()).strip()
                
                if subtopic_name in subtopic_text or subtopic_text in subtopic_name:
                    # Check for existing quiz
                    existing_quizzes = subtopic.get("quizzes") if isinstance(subtopic, dict) else getattr(subtopic, 'quizzes', None)
                    
                    if existing_quizzes and isinstance(existing_quizzes, list) and len(existing_quizzes) > 0:
                        # Use existing quiz
                        result.quiz_data = existing_quizzes
                        result.quiz_generated = False
                    elif generate_quiz:
                        # Generate new quiz
                        quiz_data = self._generate_quiz_for_subtopic(active_chapter, subtopic)
                        if quiz_data:
                            result.quiz_data = quiz_data
                            result.quiz_generated = True
                            
                            # Store quiz in subtopic
                            if isinstance(subtopic, dict):
                                subtopic["quizzes"] = quiz_data
                            else:
                                subtopic.quizzes = quiz_data
                    
                    # Update status to COMPLETED
                    if isinstance(subtopic, dict):
                        subtopic["status"] = Status.COMPLETED.value
                    else:
                        subtopic.status = Status.COMPLETED
                    
                    # Also update in study_plan
                    self._sync_subtopic_to_study_plan(user_state, active_chapter, idx, subtopic)
                    
                    # Save updated state
                    save_user_state(username, user_state)
                    print(Fore.GREEN + f"✓ Topic '{subtopic_name}' marked complete" + Fore.RESET)
                    break
            
            # Find next subtopic to unlock
            curriculum = self.get_curriculum_from_user_state(username)
            flat_topics = self.flatten_curriculum(curriculum)
            
            try:
                current_idx = flat_topics.index(topic_name)
                if current_idx + 1 < len(flat_topics):
                    next_topic = flat_topics[current_idx + 1]
                    if next_topic.startswith("  ↳ "):
                        new_unlocked.add(next_topic)
                        result.next_unlocked_topic = next_topic
                        result.unlocked_topics = new_unlocked
            except ValueError:
                pass  # Topic not found in list
            
        except Exception as e:
            print(Fore.RED + f"Error marking topic complete: {e}" + Fore.RESET)
            import traceback
            traceback.print_exc()
            result.error_message = str(e)
        
        return result
    
    def mark_topic_incomplete(
        self,
        username: str,
        topic_name: str,
        completed_topics: Set[str]
    ) -> Tuple[Set[str], Optional[str]]:
        """
        Mark a topic as incomplete.
        
        Args:
            username: The username
            topic_name: The topic name
            completed_topics: Current set of completed topics
            
        Returns:
            Tuple of (updated_completed_topics, error_message)
        """
        new_completed = set(completed_topics)
        
        if topic_name in new_completed:
            new_completed.remove(topic_name)
        
        # If it's a subtopic, also update user state
        if topic_name.startswith("  ↳ "):
            try:
                user_state = load_user_state(username)
                if user_state and "curriculum" in user_state and len(user_state["curriculum"]) > 0:
                    active_chapter = user_state["curriculum"][0].get("active_chapter")
                    if active_chapter:
                        subtopic_name = topic_name.replace("  ↳ ", "").strip()
                        subtopic_name = re.sub(r'^\d+:\s*', '', subtopic_name).strip()
                        
                        sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else active_chapter.sub_topics
                        
                        for idx, subtopic in enumerate(sub_topics):
                            if isinstance(subtopic, dict):
                                raw_subtopic = subtopic.get("sub_topic", "")
                            else:
                                raw_subtopic = subtopic.sub_topic
                            
                            subtopic_text = re.sub(r'^\n?\d+:\s*', '', raw_subtopic.strip()).strip()
                            
                            if subtopic_name in subtopic_text or subtopic_text in subtopic_name:
                                # Update status to NA
                                if isinstance(subtopic, dict):
                                    subtopic["status"] = Status.NA.value
                                else:
                                    subtopic.status = Status.NA
                                
                                self._sync_subtopic_to_study_plan(user_state, active_chapter, idx, subtopic)
                                save_user_state(username, user_state)
                                print(Fore.YELLOW + f"✓ Topic '{subtopic_name}' marked incomplete" + Fore.RESET)
                                break
            except Exception as e:
                return new_completed, str(e)
        
        return new_completed, None
    
    def _generate_quiz_for_subtopic(
        self,
        active_chapter: Any,
        subtopic: Any
    ) -> Optional[List[dict]]:
        """
        Generate quiz questions for a subtopic.
        
        Args:
            active_chapter: The active chapter (dict or object)
            subtopic: The subtopic (dict or object)
            
        Returns:
            List of quiz dictionaries, or None on failure
        """
        try:
            # Get chapter title
            if isinstance(active_chapter, dict):
                title = active_chapter.get("name", "")
            else:
                title = active_chapter.name
            
            # Get subtopic properties
            if isinstance(subtopic, dict):
                summary = subtopic.get("sub_topic", "")
                text_chunk = subtopic.get("study_material", "")
            else:
                summary = subtopic.sub_topic
                text_chunk = subtopic.study_material
            
            print(Fore.YELLOW + f"Generating quiz for: {summary[:50]}..." + Fore.RESET)
            
            quizes_ls = get_quiz(title, summary, text_chunk, "")
            quizzes_d_ls = quiz_output_parser(quizes_ls)
            
            print(Fore.GREEN + f"Generated {len(quizzes_d_ls)} quiz questions" + Fore.RESET)
            return quizzes_d_ls
            
        except Exception as e:
            print(Fore.RED + f"Error generating quiz: {e}" + Fore.RESET)
            import traceback
            traceback.print_exc()
            return None
    
    def _sync_subtopic_to_study_plan(
        self,
        user_state: dict,
        active_chapter: Any,
        subtopic_idx: int,
        subtopic: Any
    ) -> None:
        """
        Sync subtopic changes to study_plan to keep both locations consistent.
        
        Args:
            user_state: The full user state dict
            active_chapter: The active chapter
            subtopic_idx: Index of the subtopic
            subtopic: The subtopic (with updated status/quizzes)
        """
        if "study_plan" not in user_state["curriculum"][0]:
            return
        
        study_plan = user_state["curriculum"][0]["study_plan"]
        
        # Get active chapter number
        if isinstance(active_chapter, dict):
            active_chapter_num = active_chapter.get("number", -1)
        else:
            active_chapter_num = active_chapter.number
        
        # Get status and quizzes from subtopic
        if isinstance(subtopic, dict):
            status = subtopic.get("status")
            quizzes = subtopic.get("quizzes")
        else:
            status = subtopic.status.value if hasattr(subtopic.status, 'value') else subtopic.status
            quizzes = getattr(subtopic, 'quizzes', None)
        
        # Update in study_plan
        if isinstance(study_plan, dict) and "study_plan" in study_plan:
            chapters = study_plan["study_plan"]
            for chapter in chapters:
                if isinstance(chapter, dict) and chapter.get("number") == active_chapter_num:
                    if "sub_topics" in chapter and subtopic_idx < len(chapter["sub_topics"]):
                        chapter["sub_topics"][subtopic_idx]["status"] = status
                        if quizzes:
                            chapter["sub_topics"][subtopic_idx]["quizzes"] = quizzes
                    break
        elif hasattr(study_plan, 'study_plan'):
            chapters = study_plan.study_plan
            for chapter in chapters:
                if hasattr(chapter, 'number') and chapter.number == active_chapter_num:
                    if hasattr(chapter, 'sub_topics') and subtopic_idx < len(chapter.sub_topics):
                        chapter.sub_topics[subtopic_idx].status = status
                        if quizzes:
                            chapter.sub_topics[subtopic_idx].quizzes = quizzes
                    break

