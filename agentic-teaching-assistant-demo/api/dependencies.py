"""
API Dependencies

Provides lazy loading of backend modules and shared utilities.
This allows the API to start even if some backend modules are unavailable.
"""

import os
from typing import Optional, Any
from functools import lru_cache
from common.debug import get_debug_logger

# Default paths
SAVE_TO = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")
PDF_LOC = os.environ.get("AGENTICTA_PDF_LOC", "/workspace/mnt/pdfs/")
logger = get_debug_logger(__name__)


class BackendModules:
    """Lazy loader for backend modules."""
    
    _nodes = None
    _states = None
    _streaming = None
    _quiz_gen = None
    _youtube = None
    _calendar = None
    _study_buddy_tools = None
    
    @property
    def nodes(self):
        """Lazy load nodes module."""
        if self._nodes is None:
            try:
                from nodes import (
                    init_user_storage,
                    user_exists,
                    create_user_minimal,
                    load_user_state,
                    save_user_state,
                    run_for_first_time_user,
                    move_to_next_chapter,
                    update_subtopic_status,
                    add_quiz_to_subtopic,
                )
                self._nodes = {
                    "init_user_storage": init_user_storage,
                    "user_exists": user_exists,
                    "create_user_minimal": create_user_minimal,
                    "load_user_state": load_user_state,
                    "save_user_state": save_user_state,
                    "run_for_first_time_user": run_for_first_time_user,
                    "move_to_next_chapter": move_to_next_chapter,
                    "update_subtopic_status": update_subtopic_status,
                    "add_quiz_to_subtopic": add_quiz_to_subtopic,
                }
            except ImportError as e:
                logger.warning("nodes module not available: %s", e)
                self._nodes = {}
        return self._nodes
    
    @property
    def states(self):
        """Lazy load states module."""
        if self._states is None:
            try:
                from states import (
                    Status,
                    SubTopic,
                    Chapter,
                    StudyPlan,
                    Curriculum,
                    User,
                    GlobalState,
                    convert_to_json_safe,
                )
                self._states = {
                    "Status": Status,
                    "SubTopic": SubTopic,
                    "Chapter": Chapter,
                    "StudyPlan": StudyPlan,
                    "Curriculum": Curriculum,
                    "User": User,
                    "GlobalState": GlobalState,
                    "convert_to_json_safe": convert_to_json_safe,
                }
            except ImportError as e:
                logger.warning("states module not available: %s", e)
                self._states = {}
        return self._states
    
    def is_available(self, module_name: str) -> bool:
        """Check if a module is available."""
        module = getattr(self, module_name, None)
        return bool(module)


# Singleton instance
backend = BackendModules()


@lru_cache()
def get_backend():
    """Get the backend modules singleton."""
    return backend

