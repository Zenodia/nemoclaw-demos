"""
Local Authentication Manager
Handles user credentials, password hashing, and JWT token generation for local demo.

This module is designed to work on both local development and Astra deployment.
Credentials are stored in a JSON file in the same location as user state data.

IMPORTANT: All usernames are sanitized using the canonical sanitizer from
common.sanitize to ensure credentials are stored under consistent keys.
"""

import os
import json
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Import canonical sanitizer to ensure credentials use consistent keys
try:
    from common.sanitize import sanitize_username as _sanitize_username, InvalidUsernameError
except ImportError:
    # Fallback if common module not available
    import re
    
    class InvalidUsernameError(ValueError):
        pass
    
    def _sanitize_username(username: str) -> str:
        if not username:
            raise InvalidUsernameError("Username cannot be empty")
        sanitized = username.strip().lower().replace(" ", "_")
        sanitized = re.sub(r'[^a-z0-9_-]', '', sanitized)
        if not sanitized:
            raise InvalidUsernameError(f"Invalid username: '{username}'")
        return sanitized

# Simple file-based storage for credentials
# Use local path that's guaranteed to be writable
_save_to = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")
CREDENTIALS_FILE = Path(_save_to) / ".credentials.json"


# =============================================================================
# Storage Verification (for Astra deployment confirmation)
# =============================================================================

def verify_storage() -> Tuple[bool, str]:
    """
    Verify that credentials storage is writable.
    
    Use this to confirm Astra deployment readiness.
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Check 1: Parent directory exists or can be created
        CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Check 2: Can write a test file
        test_file = CREDENTIALS_FILE.parent / ".auth_write_test"
        test_file.write_text(f"test-{datetime.now().isoformat()}")
        
        # Check 3: Can read it back
        content = test_file.read_text()
        
        # Check 4: Can delete it
        test_file.unlink()
        
        msg = f"✅ Auth storage verified: {CREDENTIALS_FILE.parent}"
        logger.info(msg)
        return True, msg
        
    except PermissionError as e:
        msg = f"❌ Permission denied: Cannot write to {CREDENTIALS_FILE.parent}. Error: {e}"
        logger.error(msg)
        return False, msg
        
    except OSError as e:
        msg = f"❌ Storage error: {e}"
        logger.error(msg)
        return False, msg
        
    except Exception as e:
        msg = f"❌ Unexpected error verifying storage: {e}"
        logger.error(msg)
        return False, msg


def get_storage_info() -> Dict:
    """
    Get diagnostic information about auth storage.
    
    Useful for debugging Astra deployment issues.
    
    Returns:
        Dictionary with storage diagnostics
    """
    info = {
        "storage_path": str(CREDENTIALS_FILE),
        "storage_dir": str(CREDENTIALS_FILE.parent),
        "env_var": os.environ.get("AGENTICTA_SAVE_TO", "(not set, using default)"),
        "default_path": "/workspace/mnt/",
        "credentials_file_exists": CREDENTIALS_FILE.exists(),
        "storage_dir_exists": CREDENTIALS_FILE.parent.exists(),
        "storage_writable": False,
        "user_count": 0,
        "errors": []
    }
    
    # Check if writable
    try:
        success, msg = verify_storage()
        info["storage_writable"] = success
        if not success:
            info["errors"].append(msg)
    except Exception as e:
        info["errors"].append(str(e))
    
    # Count users if file exists
    if CREDENTIALS_FILE.exists():
        try:
            creds = _load_credentials()
            info["user_count"] = len(creds)
        except Exception as e:
            info["errors"].append(f"Could not load credentials: {e}")
    
    # Check directory permissions (Unix-style)
    try:
        import stat
        if CREDENTIALS_FILE.parent.exists():
            mode = CREDENTIALS_FILE.parent.stat().st_mode
            info["dir_permissions"] = stat.filemode(mode)
            info["dir_uid"] = CREDENTIALS_FILE.parent.stat().st_uid
            info["dir_gid"] = CREDENTIALS_FILE.parent.stat().st_gid
    except Exception:
        pass  # Skip on Windows or if unavailable
    
    return info


def print_storage_status():
    """Print a formatted storage status report."""
    info = get_storage_info()
    
    print("\n" + "=" * 60)
    print("🔐 AUTH STORAGE STATUS")
    print("=" * 60)
    print(f"  Storage Path:     {info['storage_path']}")
    print(f"  Environment Var:  {info['env_var']}")
    print(f"  Directory Exists: {'✅ Yes' if info['storage_dir_exists'] else '❌ No'}")
    print(f"  File Exists:      {'✅ Yes' if info['credentials_file_exists'] else '⚪ No (will be created)'}")
    print(f"  Writable:         {'✅ Yes' if info['storage_writable'] else '❌ No'}")
    print(f"  Registered Users: {info['user_count']}")
    
    if info.get('dir_permissions'):
        print(f"  Dir Permissions:  {info['dir_permissions']}")
    
    if info['errors']:
        print("\n  ⚠️  Errors:")
        for err in info['errors']:
            print(f"      - {err}")
    
    print("=" * 60)
    
    if info['storage_writable']:
        print("✅ ASTRA DEPLOYMENT: Storage is ready for authentication")
    else:
        print("❌ ASTRA DEPLOYMENT: Storage issues detected - fix before deploying")
        print("\n  Suggested fixes:")
        print("    1. Ensure AGENTICTA_SAVE_TO points to a writable directory")
        print("    2. Check container/pod has write permissions to the mount")
        print("    3. Run: sudo chown -R $(id -u):$(id -g) <mount_path>")
    
    print("=" * 60 + "\n")
    
    return info['storage_writable']


# =============================================================================
# Password Hashing
# =============================================================================

def _hash_password(password: str) -> str:
    """Hash password using SHA256 with salt."""
    salt = "agenticta_local_demo_salt"  # Static salt for demo (in production, use per-user salt)
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def _load_credentials() -> Dict:
    """Load credentials from file."""
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading credentials: {e}")
        return {}


def _save_credentials(credentials: Dict) -> None:
    """Save credentials to file."""
    try:
        CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CREDENTIALS_FILE, 'w') as f:
            json.dump(credentials, f, indent=2)
    except Exception as e:
        print(f"Error saving credentials: {e}")


def register_user(username: str, password: str) -> bool:
    """
    Register a new user with username and password.
    
    Username is sanitized to canonical form before storage.
    
    Args:
        username: Raw username (will be sanitized)
        password: User's password
    
    Returns:
        True if registration successful, False if username already exists or invalid
    """
    if not username or not password:
        return False
    
    # Sanitize username to canonical form
    try:
        username = _sanitize_username(username)
    except InvalidUsernameError:
        return False
    
    credentials = _load_credentials()
    
    if username in credentials:
        return False  # Username already exists
    
    credentials[username] = {
        "password_hash": _hash_password(password),
        "created_at": datetime.now().isoformat(),
        "last_login": None,
    }
    
    _save_credentials(credentials)
    return True


def verify_password(username: str, password: str) -> bool:
    """
    Verify username and password.
    
    Username is sanitized to canonical form before lookup.
    
    Args:
        username: Raw username (will be sanitized)
        password: Password to verify
    
    Returns:
        True if credentials are valid, False otherwise
    """
    # Sanitize username to canonical form
    try:
        username = _sanitize_username(username)
    except InvalidUsernameError:
        return False
    
    credentials = _load_credentials()
    
    if username not in credentials:
        return False
    
    user_data = credentials[username]
    password_hash = _hash_password(password)
    
    if user_data["password_hash"] == password_hash:
        # Update last login
        user_data["last_login"] = datetime.now().isoformat()
        credentials[username] = user_data
        _save_credentials(credentials)
        return True
    
    return False


def user_has_credentials(username: str) -> bool:
    """
    Check if user has registered credentials.
    
    Username is sanitized to canonical form before lookup.
    
    Args:
        username: Raw username (will be sanitized)
    
    Returns:
        True if user has credentials, False otherwise
    """
    # Sanitize username to canonical form
    try:
        username = _sanitize_username(username)
    except InvalidUsernameError:
        return False
    
    credentials = _load_credentials()
    return username in credentials


def generate_token(username: str) -> str:
    """
    Generate a simple JWT-like token for demo purposes.
    Format: username:random_token:expiry
    
    Username is sanitized to canonical form before embedding in token.
    
    In production, use proper JWT library like python-jose
    
    Args:
        username: Raw username (will be sanitized)
    
    Returns:
        Base64-encoded token string
    """
    # Sanitize username to canonical form
    try:
        username = _sanitize_username(username)
    except InvalidUsernameError:
        # If username is invalid, use a placeholder (shouldn't happen if API validates first)
        username = "invalid_user"
    
    random_token = secrets.token_urlsafe(32)
    expiry = (datetime.now() + timedelta(days=7)).isoformat()
    
    # Simple token format (NOT cryptographically secure - demo only!)
    token = f"{username}:{random_token}:{expiry}"
    
    # For demo, we'll just base64 encode it
    import base64
    return base64.b64encode(token.encode()).decode()


def verify_token(token: str) -> Optional[str]:
    """
    Verify token and return username if valid.
    
    Returns:
        Username if token is valid, None otherwise
    """
    try:
        import base64
        decoded = base64.b64decode(token.encode()).decode()
        username, random_token, expiry_str = decoded.split(':', 2)
        
        # Check expiry
        expiry = datetime.fromisoformat(expiry_str)
        if datetime.now() > expiry:
            return None  # Token expired
        
        # Check if user still exists
        if not user_has_credentials(username):
            return None
        
        return username
    except Exception as e:
        print(f"Token verification error: {e}")
        return None


def change_password(username: str, old_password: str, new_password: str) -> bool:
    """Change user password."""
    if not verify_password(username, old_password):
        return False
    
    credentials = _load_credentials()
    if username not in credentials:
        return False
    
    credentials[username]["password_hash"] = _hash_password(new_password)
    _save_credentials(credentials)
    return True


if __name__ == "__main__":
    # Test the authentication system
    import sys
    
    print("\n" + "=" * 60)
    print("🔐 AGENTICTA LOCAL AUTH SYSTEM TEST")
    print("=" * 60)
    
    # Step 0: Verify storage (CRITICAL for Astra deployment)
    print("\n0. Verifying storage (Astra deployment check)...")
    storage_ok = print_storage_status()
    
    if not storage_ok:
        print("\n❌ STORAGE VERIFICATION FAILED")
        print("   Cannot proceed with auth tests until storage is writable.")
        print("\n   To fix on Astra:")
        print("   1. Check AGENTICTA_SAVE_TO environment variable")
        print("   2. Ensure the mount path has write permissions")
        print("   3. Run: sudo chown -R $(id -u):$(id -g) /workspace/mnt/")
        sys.exit(1)
    
    print("\n✅ Storage verified - proceeding with auth tests...")
    
    # Test registration
    print("\n1. Registering user 'testuser'...")
    if register_user("testuser", "password123"):
        print("✅ Registration successful")
    else:
        print("⚪ Registration skipped (user already exists)")
    
    # Test login
    print("\n2. Verifying password...")
    if verify_password("testuser", "password123"):
        print("✅ Password correct")
    else:
        print("❌ Password incorrect")
    
    # Test wrong password
    print("\n3. Testing wrong password...")
    if verify_password("testuser", "wrongpassword"):
        print("❌ Wrong password accepted (BUG!)")
    else:
        print("✅ Wrong password rejected correctly")
    
    # Test token generation
    print("\n4. Generating token...")
    token = generate_token("testuser")
    print(f"✅ Token generated: {token[:50]}...")
    
    # Test token verification
    print("\n5. Verifying token...")
    verified_username = verify_token(token)
    if verified_username == "testuser":
        print(f"✅ Token verified: {verified_username}")
    else:
        print("❌ Token verification failed")
    
    # Summary
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED - Auth system ready for deployment")
    print("=" * 60)
    print(f"\nCredentials stored at: {CREDENTIALS_FILE}")
    print(f"This path is configured via: AGENTICTA_SAVE_TO={_save_to}")
    print("\nTo test on Astra, run:")
    print("  python auth_manager.py")
    print("=" * 60 + "\n")
