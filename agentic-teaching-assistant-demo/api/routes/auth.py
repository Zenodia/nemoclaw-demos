"""
Authentication Routes

Handles user login, registration, and existence checks with password support.
Uses nodes.py functions: user_exists, create_user_minimal, init_user_storage, load_user_state
Uses auth_manager.py for password authentication and token generation.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Header

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from common.debug import debug_print, get_debug_logger
from common.storage_mount import detect_storage_mount, env_flag, is_running_in_container
from api.schemas.user import (
    UserCreate,
    UserResponse,
    AuthCheckResponse,
    AuthLoginRequest,
    AuthLoginResponse,
)
from pydantic import BaseModel

router = APIRouter()
logger = get_debug_logger(__name__)

# Route verbose auth diagnostics through debug gate.
print = debug_print

# Default save location
SAVE_TO = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")

# Mock user store for when backend is unavailable
_mock_users = {}


def _get_backend_functions():
    """Lazy load backend functions."""
    try:
        from nodes import (
            init_user_storage,
            user_exists,
            create_user_minimal,
            load_user_state,
        )
        from states import convert_to_json_safe
        from auth_manager import (
            register_user,
            verify_password,
            user_has_credentials,
            generate_token,
            verify_token,
        )
        return {
            "init_user_storage": init_user_storage,
            "user_exists": user_exists,
            "create_user_minimal": create_user_minimal,
            "load_user_state": load_user_state,
            "convert_to_json_safe": convert_to_json_safe,
            "register_user": register_user,
            "verify_password": verify_password,
            "user_has_credentials": user_has_credentials,
            "generate_token": generate_token,
            "verify_token": verify_token,
            "available": True,
        }
    except ImportError as e:
        logger.warning("Backend import failed: %s", e)
        return {"available": False}


def _mock_init_storage(save_to: str, user_id: str):
    """Mock init_user_storage."""
    user_dir = Path(save_to) / user_id
    user_dir.mkdir(parents=True, exist_ok=True)


def _mock_user_exists(user_id: str) -> bool:
    """Mock user_exists."""
    return user_id in _mock_users


def _mock_create_user(user_dict: dict) -> dict:
    """Mock create_user_minimal."""
    user_id = user_dict.get("user_id")
    _mock_users[user_id] = user_dict
    return user_dict


def _mock_load_user(user_id: str) -> Optional[dict]:
    """Mock load_user_state."""
    return _mock_users.get(user_id)


# Import canonical sanitizer from shared module
# This ensures consistent username handling across all layers (API, backend, storage)
try:
    from common.sanitize import sanitize_username as _sanitize_username, InvalidUsernameError
except ImportError:
    # Fallback if common module not available (shouldn't happen in production)
    import re
    
    class InvalidUsernameError(ValueError):
        def __init__(self, original_username: str, message: str = None):
            self.original_username = original_username
            self.message = message or f"Invalid username: '{original_username}'"
            super().__init__(self.message)
    
    def _sanitize_username(username: str) -> str:
        if not username:
            raise InvalidUsernameError(username or "", "Username cannot be empty")
        sanitized = username.strip().lower().replace(" ", "_")
        sanitized = re.sub(r'[^a-z0-9_-]', '', sanitized)
        if not sanitized:
            raise InvalidUsernameError(username, f"Invalid username: '{username}'")
        return sanitized


def sanitize_username_or_422(username: str) -> str:
    """
    Sanitize username using the canonical sanitizer.
    
    Raises HTTP 422 if username is invalid.
    
    Args:
        username: Raw username input
        
    Returns:
        Sanitized username
        
    Raises:
        HTTPException: 422 if username is invalid
    """
    try:
        return _sanitize_username(username)
    except InvalidUsernameError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid username: '{username}'. Username must contain at least one alphanumeric character. Only letters, numbers, underscores, and hyphens are allowed."
        )


# Keep simple alias for backward compatibility in existing code
def sanitize_username(username: str) -> str:
    """
    Sanitize username using the canonical sanitizer.
    
    Note: For API endpoints, prefer sanitize_username_or_422() which
    raises proper HTTP errors.
    """
    return _sanitize_username(username)


@router.get("/check/{user_id}", response_model=AuthCheckResponse)
async def check_user_exists(user_id: str):
    """
    Check if a user already exists.
    
    Args:
        user_id: The username to check
        
    Returns:
        AuthCheckResponse with exists=True/False
        
    Raises:
        HTTPException 422: If username is invalid
    """
    # Sanitize username (raises 422 if invalid)
    user_id = sanitize_username_or_422(user_id)
    
    backend = _get_backend_functions()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        exists = backend["user_exists"](user_id)
    else:
        _mock_init_storage(SAVE_TO, user_id)
        exists = _mock_user_exists(user_id)
    
    return AuthCheckResponse(exists=exists)


@router.post("/register", response_model=UserResponse)
async def register_user(request: UserCreate):
    """
    Register a new user (creates minimal user record).
    
    This creates the user record but does NOT generate curriculum.
    Curriculum generation happens via /api/curriculum/generate endpoint.
    
    Args:
        request: UserCreate with user_id, study_buddy_preference, study_buddy_name, password
        
    Returns:
        UserResponse with the created user data
        
    Raises:
        HTTPException 422: If username is invalid
        HTTPException 400: If user already exists
    """
    # Sanitize username at the start (raises 422 if invalid)
    request.user_id = sanitize_username_or_422(request.user_id)
    
    backend = _get_backend_functions()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, request.user_id)
        
        # Check if user already exists
        if backend["user_exists"](request.user_id):
            raise HTTPException(
                status_code=400, 
                detail="Your account already exists. Please login instead."
            )
        
        # Check if credentials already exist (should not happen, but safety check)
        if backend["user_has_credentials"](request.user_id):
            raise HTTPException(
                status_code=400,
                detail="Your account already exists. Please login instead."
            )
        
        # Register with password if provided
        if request.password:
            if not backend["register_user"](request.user_id, request.password):
                raise HTTPException(status_code=400, detail="Failed to register user")
        
        user_dict = {
            "user_id": request.user_id,
            "study_buddy_preference": request.study_buddy_preference,
            "study_buddy_persona": None,
            "study_buddy_name": request.study_buddy_name,
            "curriculum": None,
        }
        
        created_user = backend["create_user_minimal"](user_dict)
    else:
        _mock_init_storage(SAVE_TO, request.user_id)
        
        if _mock_user_exists(request.user_id):
            raise HTTPException(
                status_code=400, 
                detail="Your account already exists. Please login instead."
            )
        
        user_dict = {
            "user_id": request.user_id,
            "study_buddy_preference": request.study_buddy_preference,
            "study_buddy_persona": None,
            "study_buddy_name": request.study_buddy_name,
            "curriculum": None,
        }
        
        created_user = _mock_create_user(user_dict)
    
    return UserResponse(
        user_id=created_user.get("user_id"),
        study_buddy_preference=created_user.get("study_buddy_preference"),
        study_buddy_persona=created_user.get("study_buddy_persona"),
        study_buddy_name=created_user.get("study_buddy_name", "Study Buddy"),
        curriculum=None,
        uploaded_files=None,
    )


@router.post("/login", response_model=AuthLoginResponse)
async def login_user(request: AuthLoginRequest):
    """
    Login an existing user with username and password.
    
    Authenticates the user's credentials and returns user data with a token.
    Does NOT auto-register new users - they must use /register first.
    
    Scenarios:
    1. Existing user with correct password - logs in, returns token
    2. Existing user with wrong password - 401 error
    3. User doesn't exist - 404 error (must register first)
    
    Args:
        request: AuthLoginRequest with user_id and password
        
    Returns:
        AuthLoginResponse with user data and authentication token
        
    Raises:
        HTTPException 422: If username is invalid
        HTTPException 401: If password is incorrect
        HTTPException 404: If user doesn't exist
    """
    # Sanitize username (raises 422 if invalid)
    request.user_id = sanitize_username_or_422(request.user_id)
    
    backend = _get_backend_functions()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, request.user_id)
        
        # Check if user has registered credentials
        has_credentials = backend["user_has_credentials"](request.user_id)
        user_exists_in_system = backend["user_exists"](request.user_id)
        token = None
        is_new_user = False  # Default to False, set to True only for new signups
        user_data = None
        
        print(f"🔐 Login request for '{request.user_id}': has_credentials={has_credentials}, user_exists={user_exists_in_system}, has_password={bool(request.password)}")
        
        # LOGIN endpoint should ONLY authenticate existing users
        # SIGNUP must happen via explicit CREATE ACCOUNT flow (not auto-register)
        
        # IMPORTANT: Check for orphaned credentials first (cleanup case)
        if has_credentials and not user_exists_in_system:
            print(f"⚠️  Orphaned credentials detected for '{request.user_id}'")
            raise HTTPException(
                status_code=500,
                detail="Account data corrupted. Please try a different username."
            )
        
        # Case 1: User exists with credentials - LOGIN
        if has_credentials and user_exists_in_system:
            print(f"📍 Case 1: Existing user LOGIN")
            
            if not request.password:
                raise HTTPException(
                    status_code=401,
                    detail="Password required for this user"
                )
            
            # Verify password
            if not backend["verify_password"](request.user_id, request.password):
                print(f"❌ Password verification failed")
                raise HTTPException(
                    status_code=401,
                    detail="Invalid username or password"
                )
            
            # Password correct
            token = backend["generate_token"](request.user_id)
            is_new_user = False
            user_data = backend["load_user_state"](request.user_id)
            
            if user_data is None:
                raise HTTPException(status_code=500, detail="Failed to load user data")
            
            print(f"✅ Login successful")
        
        # Case 2: User exists but trying to login/signup - username taken
        elif user_exists_in_system:
            print(f"📍 Case 2: Username already exists")
            raise HTTPException(
                status_code=400,
                detail="This username is already taken"
            )
        
        # Case 3: User doesn't exist - ALWAYS reject (no auto-registration)
        else:
            print(f"📍 Case 3: User doesn't exist - rejecting")
            raise HTTPException(
                status_code=404,
                detail="Your username doesn't exist"
            )
        
        safe_user = backend["convert_to_json_safe"](user_data)
    else:
        # Mock mode - still enforce same authentication rules
        _mock_init_storage(SAVE_TO, request.user_id)
        user_exists_in_mock = _mock_user_exists(request.user_id)
        token = None
        
        # Apply same logic as real backend
        if user_exists_in_mock:
            # Existing user - allow login (mock mode doesn't verify passwords)
            is_new_user = False
            safe_user = _mock_load_user(request.user_id) or {}
        elif not user_exists_in_mock:
            # User doesn't exist - reject (must use register endpoint)
            raise HTTPException(
                status_code=404,
                detail="Your username doesn't exist"
            )
    
    has_curriculum = bool(
        safe_user.get("curriculum") 
        and len(safe_user.get("curriculum", [])) > 0
    )
    
    return AuthLoginResponse(
        user=UserResponse(
            user_id=safe_user.get("user_id", request.user_id),
            study_buddy_preference=safe_user.get("study_buddy_preference"),
            study_buddy_persona=safe_user.get("study_buddy_persona"),
            study_buddy_name=safe_user.get("study_buddy_name", "Study Buddy"),
            curriculum=safe_user.get("curriculum"),
            uploaded_files=safe_user.get("uploaded_files"),
        ),
        is_new_user=is_new_user,
        has_curriculum=has_curriculum,
        token=token,
    )


@router.get("/user/{user_id}", response_model=UserResponse)
async def get_user(user_id: str):
    """
    Get user data by user_id.
    
    Args:
        user_id: The username to fetch
        
    Returns:
        UserResponse with the user data
        
    Raises:
        HTTPException 422: If username is invalid
        HTTPException 404: If user doesn't exist
    """
    # Sanitize username at the start (raises 422 if invalid)
    user_id = sanitize_username_or_422(user_id)
    
    backend = _get_backend_functions()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        if not backend["user_exists"](user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        user_data = backend["load_user_state"](user_id)
        if user_data is None:
            raise HTTPException(status_code=404, detail=f"User state for '{user_id}' not found")
        
        safe_user = backend["convert_to_json_safe"](user_data)
    else:
        if not _mock_user_exists(user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        safe_user = _mock_load_user(user_id)
        if safe_user is None:
            raise HTTPException(status_code=404, detail=f"User state for '{user_id}' not found")
    
    return UserResponse(
        user_id=safe_user.get("user_id"),
        study_buddy_preference=safe_user.get("study_buddy_preference"),
        study_buddy_persona=safe_user.get("study_buddy_persona"),
        study_buddy_name=safe_user.get("study_buddy_name", "Study Buddy"),
        curriculum=safe_user.get("curriculum"),
        uploaded_files=safe_user.get("uploaded_files"),
    )


class UpdatePreferencesRequest(BaseModel):
    """Request to update study buddy preferences."""
    study_buddy_preference: str
    study_buddy_persona: str
    study_buddy_name: Optional[str] = None


@router.patch("/user/{user_id}/preferences", response_model=UserResponse)
async def update_preferences(user_id: str, request: UpdatePreferencesRequest):
    """
    Update user's study buddy preferences and persona.
    This allows changing the persona without regenerating the curriculum.
    
    Raises:
        HTTPException 422: If username is invalid
        HTTPException 404: If user doesn't exist
    """
    # Sanitize username (raises 422 if invalid)
    user_id = sanitize_username_or_422(user_id)
    
    backend = _get_backend_functions()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        if not backend["user_exists"](user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        # Load user state
        user_state = backend["load_user_state"](user_id)
        if not user_state:
            raise HTTPException(status_code=404, detail=f"User state for '{user_id}' not found")
        
        # Update preferences
        user_state["study_buddy_preference"] = request.study_buddy_preference
        user_state["study_buddy_persona"] = request.study_buddy_persona
        if request.study_buddy_name:
            user_state["study_buddy_name"] = request.study_buddy_name
        
        # Save back to disk
        from nodes import save_user_state
        save_user_state(user_id, user_state)
        
        safe_user = backend["convert_to_json_safe"](user_state)
    else:
        # Mock mode - update in-memory store
        if user_id not in _mock_users:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        _mock_users[user_id]["study_buddy_preference"] = request.study_buddy_preference
        _mock_users[user_id]["study_buddy_persona"] = request.study_buddy_persona
        if request.study_buddy_name:
            _mock_users[user_id]["study_buddy_name"] = request.study_buddy_name
        
        safe_user = _mock_users[user_id]
    
    return UserResponse(
        user_id=safe_user.get("user_id"),
        study_buddy_preference=safe_user.get("study_buddy_preference"),
        study_buddy_persona=safe_user.get("study_buddy_persona"),
        study_buddy_name=safe_user.get("study_buddy_name", "Study Buddy"),
        curriculum=safe_user.get("curriculum"),
        uploaded_files=safe_user.get("uploaded_files"),
    )


# =============================================================================
# Health Check / Storage Verification Endpoints (for Astra deployment)
# =============================================================================

class StorageHealthResponse(BaseModel):
    """Response from storage health check."""
    status: str  # "ok" or "error"
    storage_path: str
    storage_writable: bool
    storage_mount_detected: bool
    require_storage_mount: bool
    storage_mount_checks: Dict[str, bool] = {}
    storage_sentinel_file: Optional[str] = None
    credentials_file_exists: bool
    user_count: int
    environment: str
    errors: list[str] = []
    message: str


@router.get("/health/storage", response_model=StorageHealthResponse)
async def check_storage_health():
    """
    Check if authentication storage is properly configured and writable.
    
    Use this endpoint to verify Astra deployment readiness.
    
    Returns:
        StorageHealthResponse with diagnostics
        
    Example:
        curl http://localhost:8000/api/auth/health/storage
    """
    try:
        from auth_manager import get_storage_info, verify_storage, CREDENTIALS_FILE
        
        info = get_storage_info()
        success, msg = verify_storage()

        storage_dir = Path(info["storage_dir"])
        require_storage_mount = env_flag(
            "AGENTICTA_REQUIRE_STORAGE_MOUNT",
            is_running_in_container(),
        )
        sentinel_file = os.environ.get("AGENTICTA_STORAGE_SENTINEL_FILE")
        storage_mount_detected, mount_checks, sentinel_path = detect_storage_mount(
            storage_dir,
            sentinel_file=sentinel_file,
        )
        
        # Determine environment
        env_var = os.environ.get("AGENTICTA_SAVE_TO")
        if env_var:
            if "astra" in env_var.lower() or "/workspace" in env_var:
                environment = "astra"
            else:
                environment = "custom"
        else:
            environment = "local"
        
        return StorageHealthResponse(
            status="ok" if success else "error",
            storage_path=str(CREDENTIALS_FILE),
            storage_writable=info["storage_writable"],
            storage_mount_detected=storage_mount_detected,
            require_storage_mount=require_storage_mount,
            storage_mount_checks=mount_checks,
            storage_sentinel_file=sentinel_path,
            credentials_file_exists=info["credentials_file_exists"],
            user_count=info["user_count"],
            environment=environment,
            errors=info["errors"],
            message=msg
        )
        
    except ImportError as e:
        return StorageHealthResponse(
            status="error",
            storage_path=str(Path(SAVE_TO) / ".credentials.json"),
            storage_writable=False,
            storage_mount_detected=False,
            require_storage_mount=False,
            storage_mount_checks={},
            storage_sentinel_file=None,
            credentials_file_exists=False,
            user_count=0,
            environment="unknown",
            errors=[f"Import error: {e}"],
            message="❌ Could not import auth_manager module"
        )
    except Exception as e:
        return StorageHealthResponse(
            status="error",
            storage_path=str(Path(SAVE_TO) / ".credentials.json"),
            storage_writable=False,
            storage_mount_detected=False,
            require_storage_mount=False,
            storage_mount_checks={},
            storage_sentinel_file=None,
            credentials_file_exists=False,
            user_count=0,
            environment="unknown",
            errors=[str(e)],
            message=f"❌ Storage check failed: {e}"
        )


class VersionResponse(BaseModel):
    """Response schema for version endpoint."""
    version: str
    name: str = "AI Study Assistant"


# Single authoritative version source - imported once at module level
_APP_VERSION: str = "unknown"
try:
    from version import VERSION as _APP_VERSION
except ImportError:
    pass


@router.get("/version", response_model=VersionResponse)
async def get_version():
    """
    Get the application version.
    
    Returns the version from the single authoritative source (version.py)
    for display on login/signup pages.
    """
    return VersionResponse(version=_APP_VERSION)
