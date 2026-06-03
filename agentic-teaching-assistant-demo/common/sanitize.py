"""
Username Sanitization Module

Provides a canonical username sanitizer used across all layers:
- API routes (api/routes/auth.py)
- Backend logic (nodes.py)
- Credential storage (auth_manager.py)

This ensures usernames are stored and looked up under consistent keys,
preventing mismatches between credentials and user state.
"""

import re
from typing import Optional


class InvalidUsernameError(ValueError):
    """
    Raised when a username cannot be sanitized to a valid format.
    
    This exception should be caught at the API boundary and converted
    to an appropriate HTTP error (e.g., 422 Unprocessable Entity).
    """
    
    def __init__(self, original_username: str, message: Optional[str] = None):
        self.original_username = original_username
        self.message = message or f"Invalid username: '{original_username}'. Must contain at least one alphanumeric character."
        super().__init__(self.message)


def sanitize_username(username: str) -> str:
    """
    Sanitize username to a canonical, filesystem-safe format.
    
    Transformations applied:
    1. Strip leading/trailing whitespace
    2. Convert to lowercase
    3. Replace spaces with underscores
    4. Remove all characters except: a-z, 0-9, underscore, hyphen
    
    Args:
        username: The raw username input
        
    Returns:
        The sanitized username (e.g., "John Doe@123!" -> "john_doe123")
        
    Raises:
        InvalidUsernameError: If username is empty or becomes empty after sanitization
        
    Examples:
        >>> sanitize_username("John Doe")
        'john_doe'
        >>> sanitize_username("USER@123!")
        'user123'
        >>> sanitize_username("test_user-1")
        'test_user-1'
        >>> sanitize_username("   ")
        InvalidUsernameError: Invalid username
    """
    if not username:
        raise InvalidUsernameError(username or "", "Username cannot be empty")
    
    # Step 1: Strip whitespace
    sanitized = username.strip()
    
    if not sanitized:
        raise InvalidUsernameError(username, "Username cannot be empty or whitespace only")
    
    # Step 2: Lowercase
    sanitized = sanitized.lower()
    
    # Step 3: Replace spaces with underscores
    sanitized = sanitized.replace(" ", "_")
    
    # Step 4: Remove non-alphanumeric characters (keep underscore and hyphen)
    sanitized = re.sub(r'[^a-z0-9_-]', '', sanitized)
    
    # Validate result is not empty
    if not sanitized:
        raise InvalidUsernameError(
            username, 
            f"Invalid username: '{username}'. Must contain at least one alphanumeric character, underscore, or hyphen."
        )
    
    return sanitized
