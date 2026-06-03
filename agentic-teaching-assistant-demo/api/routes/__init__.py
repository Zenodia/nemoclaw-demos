"""
API Routes Package

Contains all FastAPI route modules.
"""

from . import auth, curriculum, chat, files, quiz, calendar, youtube

__all__ = ["auth", "curriculum", "chat", "files", "quiz", "calendar", "youtube"]

