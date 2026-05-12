"""A lightweight orchestrator that builds LangGraph-like nodes to populate
the application's state objects defined in `states.py` using helper clients.

This file provides a minimal runtime-friendly shim for composing nodes (steps)
that can be wired together. It uses `helper.run_together` to call the MCP
clients (quiz generation, study buddy, agentic memory) and then constructs
`Chapter`, `StudyPlan`, `Curriculum`, `User`, and `GlobalState` objects.

The orchestrator exposes a `run_for_first_time_user(user, uploaded_pdf_loc, save_to, study_buddy_preference)` 
function that will initialize per-user storage paths, check for an existing user 
(in a local JSON store), create/populate state objects for first-time users, 
and return the final GlobalState instance.

Per-User Storage Structure:
    save_to/
    └── user_id/
        ├── global_state.json      # GlobalState for this user
        └── user_store/             # Per-user storage files
            └── user_id.json        # User profile with Curriculum > StudyPlan > Chapter > SubTopic

Example:
    /workspace/mnt/
    └── babe/
        ├── global_state.json
        └── user_store/
            └── babe.json

User State Update Functions:
    This module provides several functions to load, update, and save user states:
    
    1. update_and_save_user_state(user_id, save_to, update_fn)
       - Generic function that accepts a callback for custom updates
       - Loads user state, applies updates, saves back to disk
       
    2. move_to_next_chapter(user_id, save_to)
       - Marks current chapter as COMPLETED
       - Moves to next chapter and sets it as STARTED
       - Updates study plan accordingly
       
    3. update_subtopic_status(user_id, save_to, subtopic_number, new_status, feedback)
       - Updates a specific subtopic's status
       - Optionally adds feedback
       
    4. add_quiz_to_subtopic(user_id, save_to, subtopic_number, quiz)
       - Adds a quiz to a specific subtopic

Troubleshooting:
    If you encounter JSON parsing errors when loading user state:
    1. The saved state file may be corrupted or from an older version
    2. Delete the user directory: rm -rf {save_to}/{user_id}/
    3. Re-run run_for_first_time_user to recreate the state
    
    Example:
        # If getting JSON errors for user 'babe'
        rm -rf /workspace/mnt/babe/
        # Then re-run the initialization
       
Usage Examples:
    # Move to next chapter (async)
    updated_state = await move_to_next_chapter("babe", "/workspace/mnt/")
    # Or from synchronous context:
    updated_state = asyncio.run(move_to_next_chapter("babe", "/workspace/mnt/"))
    
    # Update subtopic status with feedback (async)
    updated_state = await update_subtopic_status(
        "babe", "/workspace/mnt/", 
        subtopic_number=0,
        new_status=Status.COMPLETED,
        feedback=["Great work!", "All tests passed"]
    )
    
    # Add a quiz (async)
    quiz = {
        "question": "What is X?",
        "choices": ["A", "B", "C"],
        "answer": "A",
        "explanation": "Because..."
    }
    updated_state = await add_quiz_to_subtopic("babe", "/workspace/mnt/", 0, quiz)
    
    # Custom update (async)
    async def my_update(user_state):
        curriculum_list = user_state.get("curriculum")  # curriculum is List[Curriculum]
        if curriculum_list and isinstance(curriculum_list, list) and len(curriculum_list) > 0:
            curriculum = curriculum_list[0]  # Get first curriculum
            active_ch = curriculum.get("active_chapter")
            # ... custom logic ...
        return user_state
    
    updated_state = await update_and_save_user_state("babe", "/workspace/mnt/", my_update)
"""
from __future__ import annotations
import json
import os
import typing
from pathlib import Path
import pandas as pd
from dataclasses import asdict, dataclass
from colorama import Fore
from states import Chapter, StudyPlan, Curriculum, User, GlobalState, Status, SubTopic
from states import save_user_to_file, load_user_from_file
from states import convert_to_json_safe
from chapter_gen_from_file_names import chapter_gen_from_pdfs, parse_output_from_chapters
from extract_sub_chapters import (
    parallel_extract_pdf_page_and_text,
    post_process_extract_sub_chapters,
    async_segmented_extract_subtopics,
)
from study_material_gen_agent import study_material_gen
import asyncio
import concurrent

# Import canonical sanitizer from shared module
# This ensures consistent username handling across all layers
from common.sanitize import sanitize_username, InvalidUsernameError
from common.debug import debug_print

# Local simple storage for users (JSON file) - will be initialized per user
STORE_PATH = None
USER_STORE_DIR = None

def init_user_storage(save_to: str, user_id: str):
    """Initialize per-user storage paths based on save_to and user_id.
    
    Args:
        save_to: Base directory for storing user data
        user_id: Unique user identifier
        
    This creates a directory structure like:
        save_to/user_id/global_state.json
        save_to/user_id/user_store/
    """
    global STORE_PATH, USER_STORE_DIR
    
    user_id = sanitize_username(user_id)
    
    # Create per-user base directory
    user_base_dir = Path(save_to) / user_id
    user_base_dir.mkdir(parents=True, exist_ok=True)
    
    # Store path for global state JSON
    STORE_PATH = user_base_dir / "global_state.json"
    
    # Directory for per-user storage files
    USER_STORE_DIR = user_base_dir / "user_store"
    USER_STORE_DIR.mkdir(parents=True, exist_ok=True)
    
    return STORE_PATH, USER_STORE_DIR

# global placeholders populated by `call_helper_clients_for_user`
# ensure these exist at module import time so other async functions can reference them
quiz_gen_output_files_loc: list[str] = []
quiz_gen_tasks_ls: list[str] = []
pdf_files: list[str] = []
quiz_csv_locations: list[str] = []

def _store_file_path() -> Path:
    """Return a safe file path for the central store.

    If `STORE_PATH` is a directory (e.g., mistakenly created as one), use
    a file named `store.json` inside it. Ensure parent directories exist.
    """
    p = STORE_PATH
    if p.exists() and p.is_dir():
        filep = p / "store.json"
        filep.parent.mkdir(parents=True, exist_ok=True)
        return filep
    # ensure parent directory exists for the file
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_store() -> dict:
    filep = _store_file_path()
    if filep.exists():
        try:
            return json.loads(filep.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_store(data: dict):
    filep = _store_file_path()
    # ensure the stored data is JSON-serializable (convert Pydantic models, Enums, etc.)
    try:
        safe_data = convert_to_json_safe(data)
    except Exception:
        # fallback: attempt to write raw data (this will raise if not serializable)
        safe_data = data
    filep.write_text(json.dumps(safe_data, indent=2, ensure_ascii=False), encoding="utf-8")


def user_exists(user_id: str) -> bool:
    user_id = sanitize_username(user_id)

    # First check per-user file store (created via save_user_to_file)
    user_file = USER_STORE_DIR / f"{user_id}.json"
    if user_file.exists():
        return True
    store = _load_store()
    return user_id in store.get("users", {})


def create_user_minimal(user: User) -> User:
    # Accept either a mapping-like User or a Pydantic/Typed object
    if isinstance(user, dict):
        uid = user.get("user_id")
        pref = user.get("study_buddy_preference")
        persona = user.get("study_buddy_persona")
        name = user.get("study_buddy_name")
    else:
        uid = getattr(user, "user_id", None)
        pref = getattr(user, "study_buddy_preference", None)
        persona = getattr(user, "study_buddy_persona", None)
        name = getattr(user, "study_buddy_name", None)

    uid = sanitize_username(uid)

    minimal = {
        "user_id": uid,
        "study_buddy_preference": pref,
        "study_buddy_persona": persona,
        "study_buddy_name": name,
        "curriculum": None,
    }

    # Save per-user file
    save_user_to_file(minimal, str(USER_STORE_DIR / f"{uid}.json"))

    # Also register in central store for quick lookups
    store = _load_store()
    users = store.setdefault("users", {})
    users[uid] = minimal
    _save_store(store)
    return minimal


def save_user_state(user_id: str, user_obj: User):
    """Save user state to disk with proper serialization of Pydantic models.
    
    This function mirrors save_user_to_file from states.py by:
    - Converting Pydantic BaseModel instances (Chapter, SubTopic, StudyPlan) to JSON-safe dicts
    - Converting Status Enum values to their string representations
    - Preserving the structure for later reconstruction
    
    Args:
        user_id: The user identifier
        user_obj: User TypedDict that may contain Pydantic models (Chapter, StudyPlan, etc.)
    
    Storage locations:
        - Per-user file: {USER_STORE_DIR}/{user_id}.json (primary storage)
        - Central store: {STORE_PATH} (convenience index)
    """
    user_id = sanitize_username(user_id)
    # Debug: Print subtopic statuses before saving
    try:
        curriculum_list = user_obj.get("curriculum", [])
        if curriculum_list and len(curriculum_list) > 0:
            curr = curriculum_list[0]
            active_ch = curr.get("active_chapter")
            study_plan = curr.get("study_plan")
            
            # Print active chapter subtopic statuses
            if active_ch:
                sub_topics = active_ch.get("sub_topics", []) if isinstance(active_ch, dict) else getattr(active_ch, "sub_topics", [])
                if sub_topics:
                    debug_print("[SAVE DEBUG] Active chapter subtopic statuses:")
                    for i, st in enumerate(sub_topics[:3]):  # First 3
                        status = st.get("status") if isinstance(st, dict) else getattr(st, "status", None)
                        name = st.get("sub_topic", "?")[:30] if isinstance(st, dict) else getattr(st, "sub_topic", "?")[:30]
                        debug_print(f"  [{i}] {name}: {status}")
            
            # Print study_plan subtopic statuses
            if study_plan:
                if hasattr(study_plan, "study_plan"):
                    chapters = study_plan.study_plan
                elif isinstance(study_plan, dict):
                    chapters = study_plan.get("study_plan", [])
                else:
                    chapters = []
                
                if chapters and len(chapters) > 0:
                    ch = chapters[0]
                    ch_subtopics = ch.get("sub_topics", []) if isinstance(ch, dict) else getattr(ch, "sub_topics", [])
                    debug_print("[SAVE DEBUG] Study plan chapter 0 subtopic statuses:")
                    for i, st in enumerate(ch_subtopics[:3]):
                        status = st.get("status") if isinstance(st, dict) else getattr(st, "status", None)
                        name = st.get("sub_topic", "?")[:30] if isinstance(st, dict) else getattr(st, "sub_topic", "?")[:30]
                        debug_print(f"  [{i}] {name}: {status}")
    except Exception as e:
        debug_print(f"[SAVE DEBUG] Error printing debug info: {e}")
    
    # Persist per-user JSON using states.save_user_to_file for Pydantic-aware serialization
    user_file_path = str(USER_STORE_DIR / f"{user_id}.json")
    save_user_to_file(user_obj, user_file_path)
    print(f"Saved user state to {user_file_path}")

    # Also write to fast_store (text-file format) for fast chat-path reads.
    # Run synchronously here since save_user_state itself is sync.
    try:
        from fast_store import get_store
        get_store(str(USER_STORE_DIR.parent.parent)).write_state_sync(
            user_id, convert_to_json_safe(user_obj)
        )
        print(f"[fast_store] state.txt written for {user_id}")
    except Exception as _fs_err:
        print(f"[fast_store] WARNING: could not write state.txt: {_fs_err}")

    # Keep central store in sync as a convenience index
    # Convert to JSON-safe format for central storage
    store = _load_store()
    users = store.setdefault("users", {})
    users[user_id] = convert_to_json_safe(user_obj)
    _save_store(store)
    print(f"Updated central store index for user {user_id}")


def load_user_state(user_id: str) -> User:
    """Load user state from disk and reconstruct Python classes.
    
    This function mirrors load_user_from_file from states.py by:
    - Loading JSON data from disk
    - Reconstructing SubTopic as BaseModel with Status enum
    - Reconstructing Chapter as BaseModel with Status enum and SubTopic list
    - Reconstructing StudyPlan as BaseModel containing Chapter list
    - Reconstructing Curriculum as TypedDict containing properly typed objects
    - Reconstructing User with curriculum as List[Curriculum]
    
    Args:
        user_id: The user identifier
        
    Returns:
        User TypedDict with properly reconstructed Pydantic models and Enums
        
    Raises:
        json.JSONDecodeError: If the user state file is corrupted
        
    Note:
        If the per-user file doesn't exist, falls back to central store.
        The fallback also properly reconstructs objects using load_user_from_file
        to ensure type consistency.
    """
    # Guard: USER_STORE_DIR not initialized (user hasn't generated curriculum yet)
    if USER_STORE_DIR is None:
        print(f"USER_STORE_DIR not initialized for user {user_id} - no curriculum generated yet")
        return None
    
    user_file = USER_STORE_DIR / f"{user_id}.json"
    
    # Primary path: Load from per-user file with proper reconstruction
    if user_file.exists():
        try:
            print(f"Loading user state from {user_file}")
            user_state = load_user_from_file(str(user_file))
            print(f"Successfully loaded and reconstructed user state for {user_id}")
            
            # Debug: Print subtopic statuses after loading
            try:
                curriculum_list = user_state.get("curriculum", [])
                if curriculum_list and len(curriculum_list) > 0:
                    curr = curriculum_list[0]
                    active_ch = curr.get("active_chapter")
                    study_plan = curr.get("study_plan")
                    
                    if active_ch:
                        sub_topics = active_ch.get("sub_topics", []) if isinstance(active_ch, dict) else getattr(active_ch, "sub_topics", [])
                        if sub_topics:
                            debug_print("[LOAD DEBUG] Active chapter subtopic statuses:")
                            for i, st in enumerate(sub_topics[:3]):
                                status = st.get("status") if isinstance(st, dict) else getattr(st, "status", None)
                                name = st.get("sub_topic", "?")[:30] if isinstance(st, dict) else getattr(st, "sub_topic", "?")[:30]
                                debug_print(f"  [{i}] {name}: {status}")
                    
                    if study_plan:
                        if hasattr(study_plan, "study_plan"):
                            chapters = study_plan.study_plan
                        elif isinstance(study_plan, dict):
                            chapters = study_plan.get("study_plan", [])
                        else:
                            chapters = []
                        
                        if chapters and len(chapters) > 0:
                            ch = chapters[0]
                            ch_subtopics = ch.get("sub_topics", []) if isinstance(ch, dict) else getattr(ch, "sub_topics", [])
                            debug_print("[LOAD DEBUG] Study plan chapter 0 subtopic statuses:")
                            for i, st in enumerate(ch_subtopics[:3]):
                                status = st.get("status") if isinstance(st, dict) else getattr(st, "status", None)
                                name = st.get("sub_topic", "?")[:30] if isinstance(st, dict) else getattr(st, "sub_topic", "?")[:30]
                                debug_print(f"  [{i}] {name}: {status}")
            except Exception as e:
                debug_print(f"[LOAD DEBUG] Error printing debug info: {e}")
            
            _verify_reconstruction(user_state, user_id)
            return user_state
        except json.JSONDecodeError as e:
            print(f"ERROR: JSON decode error loading user state from {user_file}: {e}")
            print(f"The file may be corrupted. Consider deleting the user directory:")
            print(f"  rm -rf {USER_STORE_DIR.parent}")
            print(f"Then re-run initialization for user '{user_id}'")
            raise
        except Exception as e:
            print(f"ERROR: Unexpected error loading user state: {e}")
            raise
    
    # Fallback path: Load from central store and reconstruct
    print(f"Per-user file not found for {user_id}, checking central store...")
    central_data = _load_store().get("users", {}).get(user_id)
    
    if central_data:
        # Save to per-user file for next time, then reload with proper reconstruction
        print(f"Found user {user_id} in central store, migrating to per-user file...")
        temp_file = USER_STORE_DIR / f"{user_id}_temp.json"
        save_user_to_file(central_data, str(temp_file))
        
        # Now load back with proper reconstruction
        reconstructed = load_user_from_file(str(temp_file))
        
        # Replace temp file with permanent file
        temp_file.replace(user_file)
        print(f"Migrated and reconstructed user state for {user_id}")
        _verify_reconstruction(reconstructed, user_id)
        return reconstructed
    
    print(f"WARNING: User {user_id} not found in any storage location")
    return None


def _verify_reconstruction(user_state: User, user_id: str):
    """Verify that loaded user state has properly reconstructed Python classes.
    
    This is a helper function to ensure that:
    - StudyPlan is a BaseModel instance (not a dict)
    - Chapter objects are BaseModel instances (not dicts)
    - SubTopic objects are BaseModel instances (not dicts)
    - Status values are Enum instances (not strings)
    """
    if not user_state:
        return
    
    try:
        curriculum_list = user_state.get("curriculum")
        if curriculum_list and isinstance(curriculum_list, list) and len(curriculum_list) > 0:
            curr = curriculum_list[0]
            
            # Verify StudyPlan reconstruction
            study_plan = curr.get("study_plan")
            if study_plan:
                from states import StudyPlan, Chapter, SubTopic
                is_study_plan = isinstance(study_plan, StudyPlan)
                print(f"  ✓ StudyPlan reconstructed: {is_study_plan} (type: {type(study_plan).__name__})")
                
                # Verify Chapter reconstruction
                if hasattr(study_plan, 'study_plan') and study_plan.study_plan:
                    first_chapter = study_plan.study_plan[0]
                    is_chapter = isinstance(first_chapter, Chapter)
                    print(f"  ✓ Chapter reconstructed: {is_chapter} (type: {type(first_chapter).__name__})")
                    
                    # Verify SubTopic reconstruction
                    if hasattr(first_chapter, 'sub_topics') and first_chapter.sub_topics:
                        first_subtopic = first_chapter.sub_topics[0]
                        is_subtopic = isinstance(first_subtopic, SubTopic)
                        print(f"  ✓ SubTopic reconstructed: {is_subtopic} (type: {type(first_subtopic).__name__})")
            
            # Verify active_chapter reconstruction
            active_ch = curr.get("active_chapter")
            if active_ch:
                is_active_chapter = isinstance(active_ch, Chapter)
                print(f"  ✓ Active Chapter reconstructed: {is_active_chapter}")
                
    except Exception as e:
        print(f"  Note: Verification check encountered: {e}")


async def update_and_save_user_state(user_id: str, save_to: str, update_fn: typing.Callable[[User], User]) -> User:
    """Load user state, apply updates via callback, and save back to disk.
    
    Args:
        user_id: The user identifier
        save_to: Base directory where user data is stored
        update_fn: A callback function (can be sync or async) that takes the loaded User and returns the updated User
        
    Returns:
        The updated User state
        
    Example:
        async def my_updates(user_state):
            # Access curriculum (stored as List[Curriculum] per User TypedDict)
            curriculum_list = user_state.get("curriculum")
            if curriculum_list and isinstance(curriculum_list, list) and len(curriculum_list) > 0:
                curr = curriculum_list[0]  # Get first curriculum
                active_ch = curr.get("active_chapter")
                
                # Update active chapter status
                if active_ch and isinstance(active_ch, dict):
                    active_ch["status"] = Status.COMPLETED.value
                    
                    # Update subtopic
                    sub_topics = active_ch.get("sub_topics", [])
                    if sub_topics and len(sub_topics) > 0:
                        sub_topics[0]["status"] = Status.COMPLETED.value
                        sub_topics[0]["feedback"] = ["Great work!"]
            
            return user_state
        
        updated = await update_and_save_user_state("babe", "/workspace/mnt/", my_updates)
    """
    user_id = sanitize_username(user_id)
    # Initialize storage paths for this user
    init_user_storage(save_to, user_id)
    
    # Load existing user state
    user_state = load_user_state(user_id)
    
    if not user_state:
        raise ValueError(f"User {user_id} not found in storage at {save_to}/{user_id}")
    
    print(f"Loaded user state for {user_id}")
    
    # Apply updates via callback (handle both sync and async callbacks)
    import inspect
    if inspect.iscoroutinefunction(update_fn):
        updated_state = await update_fn(user_state)
    else:
        updated_state = update_fn(user_state)
    
    # Save back to disk
    save_user_state(user_id, updated_state)
    print(f"Saved updated state for {user_id} to {USER_STORE_DIR / f'{user_id}.json'}")
    
    return updated_state


async def move_to_next_chapter(user_id: str, save_to: str, progress_callback=None) -> User:
    """Convenience function to move user to the next chapter in their curriculum.
    
    Args:
        user_id: The user identifier
        save_to: Base directory where user data is stored
        progress_callback: Optional async callback(phase, message) for progress updates
        
    Returns:
        The updated User state
        
    This function:
    - Marks current active chapter as COMPLETED
    - Moves to next chapter (sets it as active with status STARTED)
    - Updates the study plan accordingly
    """
    
    async def _move_to_next(user_state: User) -> User:
        curriculum_list = user_state.get("curriculum")
        user_id = user_state.get("user_id")
        # curriculum is stored as List[Curriculum] per User TypedDict definition
        if not curriculum_list or not isinstance(curriculum_list, list):
            print("Warning: No curriculum found for user")
            return user_state
        
        if len(curriculum_list) == 0:
            print("Warning: Curriculum list is empty")
            return user_state
        
        # Get the first (and typically only) curriculum
        curriculum = curriculum_list[0]
        
        if not curriculum:
            print("Warning: Invalid curriculum format")
            return user_state
        
        # If curriculum is a Pydantic BaseModel, convert to dict so build_next_chapter works
        if not isinstance(curriculum, dict):
            curriculum = convert_to_json_safe(curriculum)
        
        new_curr = await build_next_chapter(user_id, curriculum, progress_callback=progress_callback)
        user_state["curriculum"] = [convert_to_json_safe(new_curr)]
        return user_state
    
    return await update_and_save_user_state(user_id, save_to, _move_to_next)


async def update_subtopic_status(user_id: str, save_to: str, subtopic_number: int, 
                           new_status: Status, feedback: typing.Optional[typing.List[str]] = None) -> User:
    """Update a subtopic's status and optionally add feedback in the active chapter.
    
    Args:
        user_id: The user identifier
        save_to: Base directory where user data is stored
        subtopic_number: The subtopic number to update (0-indexed)
        new_status: New status for the subtopic
        feedback: Optional list of feedback strings to add
        
    Returns:
        The updated User state
    """
    def _update_subtopic(user_state: User) -> User:
        curriculum_list = user_state.get("curriculum")
        
        # curriculum is stored as List[Curriculum] per User TypedDict definition
        if not curriculum_list or not isinstance(curriculum_list, list):
            print("Warning: No curriculum found")
            return user_state
        
        if len(curriculum_list) == 0:
            print("Warning: Curriculum list is empty")
            return user_state
        
        # Get the first (and typically only) curriculum
        curriculum = curriculum_list[0]
        
        if not curriculum:
            print("Warning: Invalid curriculum format")
            return user_state
        
        # Handle both dict and Pydantic BaseModel for curriculum
        if isinstance(curriculum, dict):
            active_ch = curriculum.get("active_chapter")
        else:
            active_ch = getattr(curriculum, "active_chapter", None)
        
        if not active_ch:
            print("Warning: No active chapter found")
            return user_state
        
        # Handle both dict and Pydantic BaseModel for active_chapter
        if isinstance(active_ch, dict):
            sub_topics = active_ch.get("sub_topics", [])
        else:
            sub_topics = getattr(active_ch, "sub_topics", []) or []
        
        if not sub_topics or subtopic_number >= len(sub_topics):
            print(f"Warning: Subtopic {subtopic_number} not found (have {len(sub_topics) if sub_topics else 0} subtopics)")
            return user_state
        
        subtopic = sub_topics[subtopic_number]
        
        # Convert status to string value for storage
        status_value = new_status.value if isinstance(new_status, Status) else new_status
        
        # Update the subtopic status — handle both dict and Pydantic BaseModel
        if isinstance(subtopic, dict):
            subtopic["status"] = status_value
            st_name = subtopic.get('sub_topic', 'unknown')
            print(f"✓ Updated subtopic '{st_name}' status to {new_status} (dict mode)")
            
            if feedback:
                if "feedback" not in subtopic or not subtopic["feedback"]:
                    subtopic["feedback"] = []
                subtopic["feedback"].extend(feedback)
                print(f"✓ Added {len(feedback)} feedback item(s)")
        elif hasattr(subtopic, "status"):
            subtopic.status = new_status if isinstance(new_status, Status) else Status(status_value)
            st_name = getattr(subtopic, 'sub_topic', 'unknown')
            print(f"✓ Updated subtopic '{st_name}' status to {new_status} (model mode)")
            
            if feedback and hasattr(subtopic, "feedback"):
                if not subtopic.feedback:
                    subtopic.feedback = []
                subtopic.feedback.extend(feedback)
                print(f"✓ Added {len(feedback)} feedback item(s)")
        else:
            print(f"Warning: Cannot update subtopic of type {type(subtopic).__name__}")
        
        # CRITICAL FIX: Also update the corresponding subtopic in study_plan
        # When loaded from JSON, active_chapter and study_plan.study_plan[N] are separate copies
        # We must keep them in sync to ensure progress persists across sessions
        if isinstance(curriculum, dict):
            study_plan = curriculum.get("study_plan")
        else:
            study_plan = getattr(curriculum, "study_plan", None)
        debug_print(f"[DEBUG] study_plan type: {type(study_plan).__name__}, value exists: {study_plan is not None}")
        
        if study_plan:
            # Get the chapter number from active_chapter
            active_ch_number = active_ch.get("number", 0) if isinstance(active_ch, dict) else getattr(active_ch, "number", 0)
            debug_print(f"[DEBUG] Looking for chapter {active_ch_number} in study_plan")
            
            # Get the study_plan list (could be a BaseModel or dict)
            if hasattr(study_plan, "study_plan"):
                chapters_list = study_plan.study_plan
                debug_print(f"[DEBUG] study_plan is BaseModel, chapters_list len: {len(chapters_list) if chapters_list else 0}")
            elif isinstance(study_plan, dict):
                chapters_list = study_plan.get("study_plan", [])
                debug_print(f"[DEBUG] study_plan is dict, chapters_list len: {len(chapters_list) if chapters_list else 0}")
            else:
                chapters_list = []
                debug_print("[DEBUG] study_plan is unknown type, using empty list")
            
            # Find and update the matching chapter in study_plan
            found_chapter = False
            for chapter in chapters_list:
                ch_number = chapter.get("number", -1) if isinstance(chapter, dict) else getattr(chapter, "number", -1)
                if ch_number == active_ch_number:
                    found_chapter = True
                    # Get subtopics from this chapter
                    if isinstance(chapter, dict):
                        ch_subtopics = chapter.get("sub_topics", [])
                    else:
                        ch_subtopics = getattr(chapter, "sub_topics", [])
                    
                    debug_print(f"[DEBUG] Found chapter {ch_number}, subtopics count: {len(ch_subtopics) if ch_subtopics else 0}")
                    
                    # Update the matching subtopic
                    if ch_subtopics and subtopic_number < len(ch_subtopics):
                        sp_subtopic = ch_subtopics[subtopic_number]
                        debug_print(f"[DEBUG] sp_subtopic type: {type(sp_subtopic).__name__}")
                        
                        if isinstance(sp_subtopic, dict):
                            sp_subtopic["status"] = status_value
                            if feedback:
                                if "feedback" not in sp_subtopic or not sp_subtopic["feedback"]:
                                    sp_subtopic["feedback"] = []
                                sp_subtopic["feedback"].extend(feedback)
                            print(f"✓ Synced subtopic status to study_plan (chapter {ch_number}) - dict mode")
                        elif hasattr(sp_subtopic, "status"):
                            sp_subtopic.status = new_status if isinstance(new_status, Status) else Status(status_value)
                            if feedback and hasattr(sp_subtopic, "feedback"):
                                if not sp_subtopic.feedback:
                                    sp_subtopic.feedback = []
                                sp_subtopic.feedback.extend(feedback)
                            print(f"✓ Synced subtopic status to study_plan (chapter {ch_number}) - model mode")
                    else:
                        debug_print(f"[DEBUG] Subtopic {subtopic_number} not found in chapter {ch_number}")
                    break
            
            if not found_chapter:
                debug_print(f"[DEBUG] Chapter {active_ch_number} not found in study_plan chapters")
        
        return user_state
    
    return await update_and_save_user_state(user_id, save_to, _update_subtopic)


async def add_quiz_to_subtopic(user_id: str, save_to: str, subtopic_number: int, quiz: dict) -> User:
    """Add a quiz to a specific subtopic in the active chapter.
    
    Args:
        user_id: The user identifier
        save_to: Base directory where user data is stored
        subtopic_number: The subtopic number to add quiz to (0-indexed)
        quiz: Quiz dictionary with keys: question, choices, answer, explanation
        
    Returns:
        The updated User state
    """
    def _add_quiz(user_state: User) -> User:
        curriculum_list = user_state.get("curriculum")
        
        # curriculum is stored as List[Curriculum] per User TypedDict definition
        if not curriculum_list or not isinstance(curriculum_list, list):
            print("Warning: No curriculum found")
            return user_state
        
        if len(curriculum_list) == 0:
            print("Warning: Curriculum list is empty")
            return user_state
        
        # Get the first (and typically only) curriculum
        curriculum = curriculum_list[0]
        
        if not curriculum:
            print("Warning: Invalid curriculum format")
            return user_state
        
        # Handle both dict and Pydantic BaseModel for curriculum/active_chapter
        if isinstance(curriculum, dict):
            active_ch = curriculum.get("active_chapter")
        else:
            active_ch = getattr(curriculum, "active_chapter", None)
        
        if not active_ch:
            print("Warning: No active chapter found")
            return user_state
        
        if isinstance(active_ch, dict):
            sub_topics = active_ch.get("sub_topics", [])
        else:
            sub_topics = getattr(active_ch, "sub_topics", []) or []
        
        if not sub_topics or subtopic_number >= len(sub_topics):
            print(f"Warning: Subtopic {subtopic_number} not found")
            return user_state
        
        subtopic = sub_topics[subtopic_number]
        
        if isinstance(subtopic, dict):
            if "quizzes" not in subtopic or not subtopic["quizzes"]:
                subtopic["quizzes"] = []
            subtopic["quizzes"].append(quiz)
            print(f"✓ Added quiz to subtopic '{subtopic.get('sub_topic', 'unknown')}' (dict mode)")
        elif hasattr(subtopic, "quizzes"):
            if not subtopic.quizzes:
                subtopic.quizzes = []
            subtopic.quizzes.append(quiz)
            print(f"✓ Added quiz to subtopic '{getattr(subtopic, 'sub_topic', 'unknown')}' (model mode)")
        
        # CRITICAL FIX: Also add quiz to the corresponding subtopic in study_plan
        # When loaded from JSON, active_chapter and study_plan.study_plan[N] are separate copies
        if isinstance(curriculum, dict):
            study_plan = curriculum.get("study_plan")
        else:
            study_plan = getattr(curriculum, "study_plan", None)
        if study_plan:
            active_ch_number = active_ch.get("number", 0) if isinstance(active_ch, dict) else getattr(active_ch, "number", 0)
            
            if hasattr(study_plan, "study_plan"):
                chapters_list = study_plan.study_plan
            elif isinstance(study_plan, dict):
                chapters_list = study_plan.get("study_plan", [])
            else:
                chapters_list = []
            
            for chapter in chapters_list:
                ch_number = chapter.get("number", -1) if isinstance(chapter, dict) else getattr(chapter, "number", -1)
                if ch_number == active_ch_number:
                    if isinstance(chapter, dict):
                        ch_subtopics = chapter.get("sub_topics", [])
                    else:
                        ch_subtopics = getattr(chapter, "sub_topics", [])
                    
                    if ch_subtopics and subtopic_number < len(ch_subtopics):
                        sp_subtopic = ch_subtopics[subtopic_number]
                        if isinstance(sp_subtopic, dict):
                            if "quizzes" not in sp_subtopic or not sp_subtopic["quizzes"]:
                                sp_subtopic["quizzes"] = []
                            sp_subtopic["quizzes"].append(quiz)
                        elif hasattr(sp_subtopic, "quizzes"):
                            if not sp_subtopic.quizzes:
                                sp_subtopic.quizzes = []
                            sp_subtopic.quizzes.append(quiz)
                        print(f"✓ Synced quiz to study_plan (chapter {ch_number})")
                    break
        
        return user_state
    
    return await update_and_save_user_state(user_id, save_to, _add_quiz)


def parallel_extract_study_materials(username, subject, sub_topics, pdf_file, num_docs):   
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # study_material_gen is an async coroutine. Create a small
        # synchronous wrapper that executes it via `asyncio.run` so the
        # ThreadPoolExecutor receives a regular callable that returns the
        # coroutine result (and avoids un-awaited coroutine warnings).
        def _sync_run(sub_topic):
            return asyncio.run(study_material_gen(username,subject, sub_topic, pdf_file, num_docs))

        future_to_study_material = {executor.submit(_sync_run, sub_topic): sub_topic for sub_topic in sub_topics}
        outputs = []
        for future in concurrent.futures.as_completed(future_to_study_material):
            temp = future_to_study_material[future]
            try:
                data = future.result()
                outputs.append(data)
            except Exception as exc:
                debug_print('generated an exception: %s' % (exc))
                outputs.append('')
            else:
                try:
                    print('page is %d bytes' % (len(data)))
                except Exception:
                    print('page result length unknown')
                #outputs.append
    print(Fore.BLUE +"#### extracted future_to_page_text >>>> ", len(outputs), type(outputs),outputs[-1], Fore.RESET)
    return outputs
async def sub_topic_builder(username, pdf_loc, subject, pdf_f_name,
                            progress_callback=None):
    """Build SubTopic objects for a PDF using TF-IDF segmentation + concurrent
    study material generation.

    Optimisation over the original sequential approach:
    1. Uses TF-IDF to group similar pages → fewer LLM title calls
    2. Deduplicates near-identical subtopic titles
    3. Generates study materials concurrently via asyncio.gather + semaphore
    4. Retries on rate-limit (429) errors with exponential backoff

    Falls back to the legacy per-page extraction if TF-IDF segmentation
    is unavailable or fails.
    """
    import time as _time
    t0 = _time.time()

    # ── Step 1: Extract subtopics (TF-IDF segmented or legacy) ────────
    use_segmented = os.environ.get("USE_SEGMENTED_EXTRACTION", "true").lower() in ("1", "true", "yes")

    if progress_callback:
        await progress_callback("extracting", f"Extracting subtopics from {pdf_f_name}...")

    if use_segmented:
        try:
            sub_topics_ordered = await async_segmented_extract_subtopics(pdf_loc)
            print(Fore.LIGHTGREEN_EX + f"[sub_topic_builder] TF-IDF segmentation "
                  f"produced {len(sub_topics_ordered)} subtopics" + Fore.RESET)
        except Exception as e:
            print(Fore.YELLOW + f"[sub_topic_builder] TF-IDF failed ({e}), "
                  "falling back to per-page extraction" + Fore.RESET)
            sub_topics_raw = parallel_extract_pdf_page_and_text(pdf_loc)
            sub_topics_ordered = post_process_extract_sub_chapters(sub_topics_raw)
    else:
        sub_topics_raw = parallel_extract_pdf_page_and_text(pdf_loc)
        sub_topics_ordered = post_process_extract_sub_chapters(sub_topics_raw)

    if not sub_topics_ordered:
        print(Fore.YELLOW + "[sub_topic_builder] No subtopics extracted" + Fore.RESET)
        return []

    # ── Step 2: Deduplicate near-identical subtopics ──────────────────
    try:
        dedup_threshold = float(os.environ.get("SUBTOPIC_DEDUP_THRESHOLD", "0.85"))
    except (ValueError, TypeError):
        dedup_threshold = 0.85
    if dedup_threshold < 1.0 and len(sub_topics_ordered) > 1:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as _cos_sim

            cleaned = [
                t.split(":")[-1].strip() if ":" in t else t.strip()
                for t in sub_topics_ordered
            ]
            non_empty = [(i, c) for i, c in enumerate(cleaned) if len(c) > 3]
            if len(non_empty) > 1:
                texts = [c for _, c in non_empty]
                vec = TfidfVectorizer(stop_words="english", max_features=200)
                tfidf = vec.fit_transform(texts)
                sim = _cos_sim(tfidf)
                duplicates = set()
                for a in range(len(non_empty)):
                    for b in range(a + 1, len(non_empty)):
                        if sim[a][b] > dedup_threshold:
                            duplicates.add(non_empty[b][0])
                if duplicates:
                    before = len(sub_topics_ordered)
                    sub_topics_ordered = [
                        t for idx, t in enumerate(sub_topics_ordered)
                        if idx not in duplicates
                    ]
                    print(Fore.CYAN + f"[sub_topic_builder] Dedup: "
                          f"{before} → {len(sub_topics_ordered)} subtopics" + Fore.RESET)
        except (ImportError, ValueError):
            pass  # sklearn unavailable or vectorizer error – skip dedup

    if progress_callback:
        await progress_callback(
            "segmenting",
            f"Found {len(sub_topics_ordered)} unique subtopics, generating study materials...",
        )

    print(Fore.LIGHTGREEN_EX + " creating study materials for chapter :", Fore.RESET)
    print("subject =", subject, "\n sub_topics=\n", sub_topics_ordered,
          "\npdf_f_name=\n", pdf_f_name)

    # ── Step 3: Concurrent study material generation ──────────────────
    num_docs = 3
    concurrency = int(os.environ.get("STUDY_MATERIAL_CONCURRENCY", "8"))
    sem = asyncio.Semaphore(concurrency)
    max_retries = 3

    async def _gen_one(j: int, sub_topic: str):
        """Generate study material for a single subtopic with retry."""
        _title = sub_topic.split(":")[-1].strip() if ":" in sub_topic else sub_topic
        study_str, md_str = "", ""
        async with sem:
            for attempt in range(max_retries):
                try:
                    study_str, md_str = await study_material_gen(
                        username, subject, _title, pdf_f_name, num_docs, pdf_path=pdf_loc
                    )
                    if md_str and len(md_str) > 150:
                        break
                    elif attempt < max_retries - 1:
                        backoff = 2 ** attempt * 2
                        print(Fore.YELLOW + f"[sub_topic_builder] Short response "
                              f"for '{_title}', retrying in {backoff}s" + Fore.RESET)
                        await asyncio.sleep(backoff)
                except Exception as e:
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        backoff = 2 ** attempt * 3
                        print(Fore.YELLOW + f"[sub_topic_builder] Rate limited on "
                              f"'{_title}', backoff {backoff}s" + Fore.RESET)
                        await asyncio.sleep(backoff)
                    elif attempt == max_retries - 1:
                        print(Fore.RED + f"[sub_topic_builder] Failed for "
                              f"'{_title}': {e}" + Fore.RESET)
                        study_str, md_str = "", ""
                    else:
                        await asyncio.sleep(2)
        return j, sub_topic, study_str, md_str

    gen_results = await asyncio.gather(*[
        _gen_one(j, title) for j, title in enumerate(sub_topics_ordered)
    ])

    # ── Step 4: Assemble SubTopic objects (ordered) ───────────────────
    valid_sub_topics = []
    for j, sub_topic, study_str, md_str in sorted(gen_results, key=lambda r: r[0]):
        if not md_str:
            print(Fore.YELLOW + f"[sub_topic_builder] Skipping invalid "
                  f"subtopic: {sub_topic}" + Fore.RESET)
            continue
        valid_sub_topics.append(SubTopic(
            number=len(valid_sub_topics),
            sub_topic=sub_topic,
            status=Status.NA,
            study_material=study_str,
            display_markdown=md_str,
            reference=pdf_f_name,
            quizzes=[],
            feedback=[],
        ))
        if progress_callback:
            await progress_callback(
                "generating",
                f"Generated {len(valid_sub_topics)}/{len(sub_topics_ordered)} study materials",
            )

    elapsed = _time.time() - t0
    print(Fore.LIGHTGREEN_EX + f"[sub_topic_builder] Done: "
          f"{len(valid_sub_topics)} subtopics in {elapsed:.1f}s" + Fore.RESET)
    return valid_sub_topics           


async def build_next_chapter( username,curriculum : Curriculum, progress_callback=None ) -> Curriculum :
    """Try to reuse the heuristics in helper.extract_summaries_and_chapters
    to create Chapter objects. We'll implement a small local parser here so
    the orchestrator is self-contained.
    """
    study_plan = curriculum["study_plan"]
    next_chapter = curriculum["next_chapter"]
    active_chapter = curriculum["active_chapter"]
    
    # Check if there's actually a next chapter to move to
    if next_chapter is None:
        print(Fore.YELLOW + "Warning: No next chapter available. User has completed all chapters." + Fore.RESET)
        # Just mark the current chapter as completed and return
        if isinstance(active_chapter, dict):
            active_chapter["status"] = Status.COMPLETED.value
            active_ch_number = active_chapter.get("number", 0)
            sub_topics = active_chapter.get("sub_topics", [])
            if sub_topics:
                for i in range(len(sub_topics)):
                    if isinstance(sub_topics[i], dict):
                        sub_topics[i]["status"] = Status.COMPLETED.value
        else:
            active_chapter.status = Status.COMPLETED
            active_ch_number = active_chapter.number
            if active_chapter.sub_topics:
                for i in range(len(active_chapter.sub_topics)):
                    active_chapter.sub_topics[i].status = Status.COMPLETED
        
        # CRITICAL FIX: Sync completion status back to study_plan
        if hasattr(study_plan, "study_plan"):
            chapters_list = study_plan.study_plan
        elif isinstance(study_plan, dict):
            chapters_list = study_plan.get("study_plan", [])
        else:
            chapters_list = []
        
        for chapter in chapters_list:
            ch_number = chapter.get("number", -1) if isinstance(chapter, dict) else getattr(chapter, "number", -1)
            if ch_number == active_ch_number:
                if isinstance(chapter, dict):
                    chapter["status"] = Status.COMPLETED.value
                    ch_subtopics = chapter.get("sub_topics", [])
                    for i, st in enumerate(ch_subtopics):
                        if isinstance(st, dict):
                            st["status"] = Status.COMPLETED.value
                else:
                    chapter.status = Status.COMPLETED
                    if hasattr(chapter, "sub_topics") and chapter.sub_topics:
                        for st in chapter.sub_topics:
                            st.status = Status.COMPLETED
                print(f"✓ Synced final chapter completion to study_plan (chapter {ch_number})")
                break
        
        return curriculum
    
    # Update active chapter status - handle both dict and object access
    if isinstance(active_chapter, dict):
        active_chapter["status"] = Status.COMPLETED.value
        current_index = active_chapter["number"]
        sub_topics = active_chapter["sub_topics"]
        n=len(sub_topics) if sub_topics else 0
        if n > 0 and isinstance(sub_topics[0], dict):
            for i in range(len(sub_topics)):
                sub_topics[i]["status"]=Status.COMPLETED.value
        elif n > 0:
            for sub_t in active_chapter["sub_topics"] :
                sub_t.status = Status.COMPLETED

    else:
        active_chapter.status = Status.COMPLETED
        current_index = active_chapter.number
        n=len(active_chapter.sub_topics) if active_chapter.sub_topics else 0
        ## mark all sub_topics as completed if this chapter is completed
        if n > 0:
            for i in range(n):
                active_chapter.sub_topics[i].status= Status.COMPLETED
    
    # CRITICAL FIX: Sync the active chapter completion status back to study_plan
    # before moving to next chapter
    if hasattr(study_plan, "study_plan"):
        chapters_list = study_plan.study_plan
    elif isinstance(study_plan, dict):
        chapters_list = study_plan.get("study_plan", [])
    else:
        chapters_list = []
    
    for chapter in chapters_list:
        ch_number = chapter.get("number", -1) if isinstance(chapter, dict) else getattr(chapter, "number", -1)
        if ch_number == current_index:
            if isinstance(chapter, dict):
                chapter["status"] = Status.COMPLETED.value
                ch_subtopics = chapter.get("sub_topics", [])
                for i, st in enumerate(ch_subtopics):
                    if isinstance(st, dict):
                        st["status"] = Status.COMPLETED.value
            else:
                chapter.status = Status.COMPLETED
                if hasattr(chapter, "sub_topics") and chapter.sub_topics:
                    for st in chapter.sub_topics:
                        st.status = Status.COMPLETED
            print(f"✓ Synced chapter {ch_number} completion to study_plan before moving to next")
            break
    
    # Access next chapter properties - handle both dict and object access  
    if isinstance(next_chapter, dict):
        pdf_file_loc = next_chapter.get("pdf_loc")
        chapter_title = next_chapter.get("name")
    else:
        pdf_file_loc = getattr(next_chapter, "pdf_loc", None)
        chapter_title = getattr(next_chapter, "name", None)
    
    # Additional safety check
    if not pdf_file_loc or not chapter_title:
        raise ValueError(f"Next chapter missing required fields: pdf_loc={pdf_file_loc}, name={chapter_title}") 

    pdf_f_name=pdf_file_loc.split('/')[-1]
    subject=pdf_f_name.split('.pdf')[0]
    
    subtopics_and_study_material = await sub_topic_builder(username, pdf_file_loc, subject, pdf_f_name, progress_callback=progress_callback)
    chap=Chapter(
    number=current_index + 1,
    name=chapter_title,
    status=Status.STARTED, 
    sub_topics=subtopics_and_study_material,        
    reference=pdf_f_name,
    pdf_loc = pdf_file_loc,
    quizzes=[],
    feedback=[])
    
    # Convert Chapter to dict for consistency
    curriculum["active_chapter"] = convert_to_json_safe(chap)
    
    # Update the chapter in study_plan with the newly generated study materials
    study_plan_chapters = study_plan.get("study_plan", []) if isinstance(study_plan, dict) else study_plan.study_plan
    if current_index + 1 < len(study_plan_chapters):
        # Update the corresponding chapter in the study plan
        if isinstance(study_plan, dict):
            # If study_plan is a dict, update the list directly
            study_plan["study_plan"][current_index + 1] = convert_to_json_safe(chap)
        else:
            # If study_plan is a BaseModel, update the list
            study_plan.study_plan[current_index + 1] = chap
        print(Fore.LIGHTCYAN_EX + f" ✓ Updated study_plan chapter {current_index + 1} with study materials", Fore.RESET)
    
    # Update next_chapter - access study_plan properly
    if current_index + 2 < len(study_plan_chapters):
        next_chap = study_plan_chapters[current_index + 2]
        curriculum["next_chapter"] = convert_to_json_safe(next_chap) if not isinstance(next_chap, dict) else next_chap
    else:
        curriculum["next_chapter"] = None
    
    # Ensure the updated study_plan is saved back to curriculum
    curriculum["study_plan"] = convert_to_json_safe(study_plan) if not isinstance(study_plan, dict) else study_plan
    
    print(Fore.LIGHTGREEN_EX + " Moving to next chapter: ", chapter_title, Fore.RESET)
    return curriculum


async def build_chapters(username, pdf_files_loc: str, progress_callback=None) -> typing.List[Chapter]:
    """Try to reuse the heuristics in helper.extract_summaries_and_chapters
    to create Chapter objects. We'll implement a small local parser here so
    the orchestrator is self-contained.
    """
    
    # Get all PDFs in directory for validation
    all_pdfs = [f for f in os.listdir(pdf_files_loc) if f.endswith('.pdf')]
    print(Fore.CYAN + f"📄 Found {len(all_pdfs)} PDF files to process: {all_pdfs}" + Fore.RESET)
    
    chapter_titles_str = await chapter_gen_from_pdfs(pdf_files_loc)
    chapter_output=parse_output_from_chapters(chapter_titles_str)
    
    # Filter out invalid items (non-dicts or empty lists) and validate structure
    valid_chapter_output = [
        item for item in chapter_output 
        if isinstance(item, dict) and "file_loc" in item and "title" in item
    ]
    
    print(Fore.YELLOW + f"📊 LLM returned {len(chapter_output)} items, {len(valid_chapter_output)} are valid" + Fore.RESET)
    
    # Check if any PDFs were skipped
    returned_pdfs = [item["file_loc"] for item in valid_chapter_output]
    skipped_pdfs = [pdf for pdf in all_pdfs if pdf not in returned_pdfs]
    if skipped_pdfs:
        print(Fore.RED + f"⚠️  WARNING: {len(skipped_pdfs)} PDF(s) were NOT included by LLM:" + Fore.RESET)
        for pdf in skipped_pdfs:
            print(Fore.RED + f"   - {pdf}" + Fore.RESET)
    
    if not valid_chapter_output:
        print("Warning: No valid chapters found in chapter_output. Returning empty list.")
        print(f"Raw chapter_output: {chapter_output}")
        return []
    
    pdf_files_ls = [os.path.join(pdf_files_loc, item["file_loc"]) for item in valid_chapter_output]
    chapter_titles_cleaned_ls = [item["title"] for item in valid_chapter_output]

    # Build all chapters concurrently — each PDF's subtopics are generated in parallel
    async def _build_one(i, pdf_loc, chapter_title):
        pdf_f_name = pdf_loc.split('/')[-1]
        subject = pdf_f_name.split('.pdf')[0]
        print(Fore.CYAN + f"[build_chapters] Starting PDF {i+1}/{len(pdf_files_ls)}: {pdf_f_name}" + Fore.RESET)
        valid_sub_topics = await sub_topic_builder(
            username, pdf_loc, subject, pdf_f_name,
            progress_callback=progress_callback if i == 0 else None,
        )
        return Chapter(
            number=i,
            name=chapter_title,
            status=Status.STARTED if i == 0 else Status.NA,
            sub_topics=valid_sub_topics,
            reference=pdf_f_name,
            pdf_loc=pdf_loc,
            quizzes=[],
            feedback=[],
        )

    chapters = await asyncio.gather(*[
        _build_one(i, pdf_loc, chapter_title)
        for i, (pdf_loc, chapter_title) in enumerate(zip(pdf_files_ls, chapter_titles_cleaned_ls))
    ])
    chapters = list(chapters)
    print(Fore.LIGHTGREEN_EX + f"[build_chapters] Done: {len(chapters)} chapter(s)" + Fore.RESET)
    return chapters

async def populate_states_for_user(user: User, pdf_files_loc: str, study_buddy_preference: str, progress_callback=None) -> GlobalState:
    """Given results from MCP clients, construct Chapter, StudyPlan, Curriculum, User and GlobalState
    and persist them in the store.
    
    Args:
        user: User TypedDict with basic user information
        pdf_files_loc: Path to directory containing PDF files
        study_buddy_preference: User's preference for study buddy persona
        progress_callback: Optional async callback(phase, message) for progress updates
        
    Returns:
        GlobalState TypedDict with populated user, curriculum, and study plan
    """
    username = user["user_id"]
    chapters = await build_chapters(username, pdf_files_loc, progress_callback=progress_callback)
    print(Fore.LIGHTGREEN_EX + "len of chapter is = \n",len(chapters), chapters, '\n\n', Fore.RESET )
    
    # Handle case when no chapters are found
    if len(chapters) == 0:
        raise ValueError(
            "No valid chapters found. This typically means:\n"
            "1. The PDF files directory is empty or invalid\n"
            "2. The chapter generation failed to produce valid output\n"
            "3. The PDF files don't have proper structure/content\n"
            f"PDF location checked: {pdf_files_loc}"
        )
    
    study_plan = StudyPlan(study_plan=chapters)
    if len(chapters) == 1:
        curriculum = Curriculum(active_chapter=chapters[0], study_plan=study_plan, status=Status.PROGRESSING)
    else:
        # next_chapter should refer to the second chapter in the generated list
        curriculum = Curriculum(active_chapter=chapters[0], next_chapter=chapters[1], study_plan=study_plan, status=Status.PROGRESSING)
    
    
    # build User Pydantic-compatible dict
    # Generate a study buddy persona via the MCP server.
    # The import is lazy (inside this block) because study_buddy_client.py
    # has module-level side effects (vault secret lookup for INFERENCE_API_KEY)
    # that could crash nodes.py at import time if the key isn't configured.
    persona = None
    try:
        from study_buddy_client import study_buddy_client_requests
        persona = await study_buddy_client_requests(query=study_buddy_preference)
        print(Fore.LIGHTBLUE_EX + "persona extracted from study_buddy results =\n", persona, Fore.RESET)
    except ImportError as e:
        print(Fore.YELLOW + f"[populate_states] study_buddy_client not available (missing dependency or INFERENCE_API_KEY): {e}" + Fore.RESET)
    except Exception as e:
        print(Fore.YELLOW + f"[populate_states] study_buddy MCP call failed, using raw preference as persona: {e}" + Fore.RESET)
    
    if not persona:
        persona = user["study_buddy_preference"]
    
    #existing = _load_store().get("users", {}).get(user_id, {})
    
    # Convert Pydantic Curriculum to JSON-safe dict
    curriculum_dict = convert_to_json_safe(curriculum)
    
    # User TypedDict expects curriculum as List[Curriculum], so wrap in list
    user_dict = {
        "user_id": user["user_id"],
        "study_buddy_preference": user["study_buddy_preference"],
        "study_buddy_persona": persona,
        "study_buddy_name": user["study_buddy_name"],
        "curriculum": [curriculum_dict],  # Wrap in list to match User TypedDict definition
    }

    # Save into store
    save_user_state(user["user_id"], user_dict)
    processed_pdf_files=[os.path.join(pdf_files_loc, pdf_f) for pdf_f in os.listdir(pdf_files_loc) if pdf_f.endswith('.pdf')]
    # Build GlobalState TypedDict with all required fields
    gstate: GlobalState = {
        "input": "initializing",
        "existing_user": False,  # This is a first-time user
        "user": user_dict,
        "user_id": user["user_id"],
        "chat_history": [],
        "next_node_name": "",
        "pdf_loc": pdf_files_loc,        
        "processed_files": processed_pdf_files,
        "agent_final_output": None,
        "intermediate_steps": [],
    }
    # persist top-level
    store = _load_store()
    store.setdefault("global_states", {})[user["user_id"]] = gstate
    _save_store(store)

    return gstate


async def run_for_first_time_user(user: User, uploaded_pdf_loc: str, save_to: str, study_buddy_preference: str , store_path : str = None, user_store_dir :str = None, progress_callback=None) -> GlobalState:
    """Main entrypoint: ensure user exists, call helper clients if necessary,
    populate states, and return the GlobalState.
    
    This function initializes per-user storage paths based on save_to and user_id,
    creating a directory structure for storing GlobalState and user data.
    
    Args:
        user: User TypedDict with basic user information
        uploaded_pdf_loc: Path to directory containing uploaded PDF files
        save_to: Base directory for storing user data and states
        study_buddy_preference: User's preference for study buddy persona
        progress_callback: Optional async callback(phase, message) for progress updates
        
    Returns:
        GlobalState TypedDict with fully populated user state and curriculum
    """
    user_id = sanitize_username(user["user_id"])
    user["user_id"] = user_id
    
    # Initialize per-user storage paths
    print(f"Initializing storage for user {user_id} at {save_to}...")
    if store_path is None and user_store_dir is None:
        store_path, user_store_dir = init_user_storage(save_to, user_id)
    print(f"  - Global state path: {store_path}")
    print(f"  - User store directory: {user_store_dir}")
    
    if not user_exists(user_id):
        print(f"User {user_id} not found. Creating minimal user record...")
        create_user_minimal(user)

    # check if we already have a global state
    store = _load_store()
    if store.get("global_states", {}).get(user_id):
        print(f"Found existing GlobalState for user {user_id}; returning it.")
        return store["global_states"][user_id]

    # First-time population: call helper clients
    print("Populating application states ...")
    gstate = await populate_states_for_user(user, uploaded_pdf_loc, study_buddy_preference, progress_callback=progress_callback)
    
    # Update GlobalState with save_to path
    gstate["save_to"] = save_to
    
    # Re-save the updated GlobalState
    store = _load_store()
    store.setdefault("global_states", {})[user_id] = gstate
    _save_store(store)
    
    print("Done. GlobalState created and saved.")
    return gstate


async def add_documents_to_curriculum(
    user_id: str, 
    pdf_files_loc: str, 
    save_to: str,
    progress_callback=None
) -> dict:
    """Add new documents to an existing user's curriculum.
    
    This function is for RETURNING users who want to add more PDFs to their
    existing curriculum without regenerating from scratch.
    
    Args:
        user_id: User identifier
        pdf_files_loc: Path to directory containing PDF files (including new ones)
        save_to: Base directory for storing user data
        progress_callback: Optional async callback(pdf_name, status, index, total) for progress updates
        
    Returns:
        dict with:
            - success: bool
            - new_chapters: list of new chapter dicts added
            - total_chapters: total chapters after addition
            - message: status message
    """
    user_id = sanitize_username(user_id)
    
    # Initialize storage paths
    init_user_storage(save_to, user_id)
    
    # Load existing global state
    store = _load_store()
    gstate = store.get("global_states", {}).get(user_id)
    
    if not gstate:
        return {
            "success": False,
            "new_chapters": [],
            "total_chapters": 0,
            "message": f"No existing curriculum found for user '{user_id}'. Use run_for_first_time_user instead."
        }
    
    # Get list of already processed PDFs
    processed_files = gstate.get("processed_files", [])
    processed_filenames = set(os.path.basename(f) for f in processed_files)
    
    # Get all PDFs in the directory
    all_pdfs = [f for f in os.listdir(pdf_files_loc) if f.endswith('.pdf')]
    
    # Find NEW PDFs that haven't been processed yet
    new_pdfs = [f for f in all_pdfs if f not in processed_filenames]
    
    if not new_pdfs:
        return {
            "success": True,
            "new_chapters": [],
            "total_chapters": len(gstate.get("user", {}).get("curriculum", [{}])[0].get("study_plan", {}).get("study_plan", [])),
            "message": "No new documents to add. All PDFs have already been processed."
        }
    
    print(f"[ADD_DOCS] Found {len(new_pdfs)} new PDFs to process: {new_pdfs}")
    
    # Get existing curriculum data
    user_data = gstate.get("user", {})
    curriculum_list = user_data.get("curriculum", [])
    if not curriculum_list:
        return {
            "success": False,
            "new_chapters": [],
            "total_chapters": 0,
            "message": "Existing curriculum is empty or corrupted."
        }
    
    curriculum = curriculum_list[0]
    study_plan = curriculum.get("study_plan", {})
    existing_chapters = study_plan.get("study_plan", [])
    
    # Get the next chapter number
    next_chapter_number = len(existing_chapters)
    
    print(f"[ADD_DOCS] Existing chapters: {next_chapter_number}, adding {len(new_pdfs)} new chapters")
    
    # Generate chapter titles for new PDFs
    from chapter_gen_from_file_names import chapter_gen_from_pdfs, parse_output_from_chapters
    
    # Report progress: starting
    if progress_callback:
        for i, pdf in enumerate(new_pdfs):
            await progress_callback(pdf, "pending", i, len(new_pdfs))
    
    # Generate chapter info for ALL PDFs in directory (function expects directory path)
    # Then filter to only include new PDFs
    chapter_gen_output = await chapter_gen_from_pdfs(pdf_files_loc)
    all_chapter_output = parse_output_from_chapters(chapter_gen_output)
    
    # Filter to only include chapters for NEW PDFs
    new_pdfs_set = set(new_pdfs)
    valid_chapter_output = [
        ch for ch in all_chapter_output 
        if ch.get("file_loc") in new_pdfs_set
    ]
    
    print(f"[ADD_DOCS] Generated {len(all_chapter_output)} total chapters, filtered to {len(valid_chapter_output)} new")
    
    if not valid_chapter_output:
        return {
            "success": False,
            "new_chapters": [],
            "total_chapters": next_chapter_number,
            "message": "Failed to generate chapter information from new PDFs."
        }
    
    # Build new chapters (without study materials - lazy loading)
    new_chapters = []
    for i, item in enumerate(valid_chapter_output):
        pdf_filename = item["file_loc"]
        chapter_title = item["title"]
        pdf_full_path = os.path.join(pdf_files_loc, pdf_filename)
        
        chapter_number = next_chapter_number + i
        
        # Report progress
        if progress_callback:
            await progress_callback(pdf_filename, "processing", i, len(valid_chapter_output))
        
        # Create chapter without study materials (lazy loaded later)
        new_chapter = {
            "number": chapter_number,
            "name": chapter_title,
            "status": "NA",
            "sub_topics": [],  # Will be populated on-demand
            "reference": pdf_filename,
            "pdf_loc": pdf_full_path,
            "quizzes": [],
            "feedback": []
        }
        new_chapters.append(new_chapter)
        
        # Report progress: complete
        if progress_callback:
            await progress_callback(pdf_filename, "complete", i, len(valid_chapter_output))
    
    # Append new chapters to study plan
    existing_chapters.extend(new_chapters)
    
    # Update the study_plan
    study_plan["study_plan"] = existing_chapters
    curriculum["study_plan"] = study_plan
    
    # Update next_chapter if it was None (user had only 1 chapter before)
    if curriculum.get("next_chapter") is None and len(existing_chapters) > 1:
        # Find the first unstarted chapter
        for ch in existing_chapters:
            if ch.get("status") in ["NA", None]:
                curriculum["next_chapter"] = ch
                break
    
    # Update processed files list
    new_processed = [os.path.join(pdf_files_loc, f) for f in new_pdfs]
    gstate["processed_files"] = processed_files + new_processed
    
    # Update user curriculum
    user_data["curriculum"] = [curriculum]
    gstate["user"] = user_data
    
    # Save updated state
    store["global_states"][user_id] = gstate
    _save_store(store)
    
    # Also update the user state file
    save_user_state(user_id, user_data)
    
    print(f"[ADD_DOCS] Successfully added {len(new_chapters)} chapters. Total: {len(existing_chapters)}")
    
    return {
        "success": True,
        "new_chapters": new_chapters,
        "total_chapters": len(existing_chapters),
        "message": f"Successfully added {len(new_chapters)} new chapter(s) to curriculum."
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("user_id", nargs="?", default="babe")
    parser.add_argument("preference", nargs="?", default="someone who has patience, a good sense of humor, can make boring subject fun.")
    parser.add_argument("study_buddy_name", nargs="?", default="Ollie")
    parser.add_argument("pdf_loc", nargs="?", default="/workspace/mnt/pdfs/")
    parser.add_argument("save_to", nargs="?", default="/workspace/mnt/")
    args = parser.parse_args()
    
    # Create User TypedDict
    u: User = {
        "user_id": sanitize_username(args.user_id),
        "study_buddy_preference": args.preference,
        "study_buddy_name": args.study_buddy_name,
        "study_buddy_persona": None,
        "curriculum": None,
    }
    
    uploaded_pdf_loc = args.pdf_loc
    save_to = args.save_to
    
    print(". . . . . . . . . ."*25)
    print("[FIRST_TIME_USER] : populating curriculum for first time user")
    
    # Run for first time user - returns GlobalState
    global_state: GlobalState = asyncio.run(run_for_first_time_user(u, uploaded_pdf_loc, save_to, args.preference))
    
    # Print a JSON-serializable representation of the global state
    print(json.dumps(convert_to_json_safe(global_state), indent=2, ensure_ascii=False))
    
    # Example: Demonstrate updating user state
    print("\n" + "="*60)
    print("DEMONSTRATION: Update User State Functions")
    print("="*60)
    
    # Example 1: Update a subtopic's status and add feedback
    print(". . . . . . . . . ."*25)
    print("\n1. [RETURN USER] : Updating subtopic status with feedback...")
    try:
        updated_user: User = asyncio.run(update_subtopic_status(
            user_id=args.user_id,
            save_to=save_to,
            subtopic_number=0,
            new_status=Status.COMPLETED,
            feedback=["Excellent work!", "All concepts mastered"]
        ))
        print(f"   ✓ Success! Updated user: {updated_user['user_id']}")
    except Exception as e:
        print(f"   (Skipped - user state may not exist yet: {e})")
    
    # Example 2: Add a quiz to a subtopic
    print("\n2. [RETURN USER] : Adding quiz to subtopic...")
    try:
        quiz = {
            "question": "What is the main topic discussed?",
            "choices": ["Option A", "Option B", "Option C"],
            "answer": "Option A",
            "explanation": "This is the correct answer because..."
        }
        updated_user: User = asyncio.run(add_quiz_to_subtopic(
            user_id=args.user_id,
            save_to=save_to,
            subtopic_number=0,
            quiz=quiz
        ))
        print(f"   ✓ Success! Updated user: {updated_user['user_id']}")
    except Exception as e:
        print(f"   (Skipped - user state may not exist yet: {e})")
    
    # Example 3: Move to next chapter
    print("\n3. [RETURN USER] : Moving to next chapter...")
    try:
        updated_user: User = asyncio.run(move_to_next_chapter(
            user_id=args.user_id,
            save_to=save_to
        ))
        print(f"   ✓ Success! Updated user: {updated_user['user_id']}")
        
        # Verify the update worked
        if updated_user["curriculum"] and len(updated_user["curriculum"]) > 0:
            curr = updated_user["curriculum"][0]
            active_ch = curr.get("active_chapter")
            if active_ch and isinstance(active_ch, Chapter):
                print(f"   ✓ Now on chapter: {active_ch.name} (status: {active_ch.status})")
    except Exception as e:
        print(f"   (Skipped - user state may not exist yet: {e})")
    
    # Example 4: Custom update using update_and_save_user_state
    """
    print("\n4. [RETURN USER] : Custom update using callback function...")
    try:
        def custom_update(user_state: User) -> User:
            '''Custom update logic with proper User type annotations'''
            curriculum_list = user_state.get("curriculum")
            if curriculum_list and len(curriculum_list) > 0:
                curr = curriculum_list[0]
                active_ch = curr.get("active_chapter")
                if active_ch and isinstance(active_ch, Chapter):
                    # Add custom feedback to chapter
                    if not active_ch.feedback:
                        active_ch.feedback = []
                    active_ch.feedback.append("Custom feedback added via update function")
                    print("   ✓ Added custom feedback to active chapter")
            return user_state
        
        updated_user: User = asyncio.run(update_and_save_user_state(
            user_id=args.user_id,
            save_to=save_to,
            update_fn=custom_update
        ))
        print(f"   ✓ Success! Updated user: {updated_user['user_id']}")
    except Exception as e:
        print(f"   (Skipped - user state may not exist yet: {e})")
    
    print("\n" + "="*60)
    print("✓ Update demonstrations complete!")
    print("="*60)"""
