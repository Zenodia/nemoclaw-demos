"""
Structured logging configuration for AgenticTA.

Usage:
    from logging_config import setup_logging, get_logger
    
    # Setup once at application start
    setup_logging(level="INFO")
    
    # Get logger in any module
    logger = get_logger(__name__)
    logger.info("Processing started", user_id=user_id, pdf_count=len(pdfs))
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for better readability."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(level="INFO", log_dir="/workspace/mnt/logs"):
    """
    Setup structured logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory to store log files
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    root_logger.handlers = []
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = ColoredFormatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (rotating daily)
    log_file = log_path / f"agenticta_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # Log startup
    root_logger.info(f"Logging initialized at level {level}")
    root_logger.info(f"Log file: {log_file}")
    
    return root_logger


def get_logger(name):
    """
    Get a logger for a specific module.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        logging.Logger: Configured logger
    
    Example:
        logger = get_logger(__name__)
        logger.info("Processing PDF", pdf_name="document.pdf", page_count=10)
    """
    return logging.getLogger(name)


# Convenience function for structured logging
def log_with_context(logger, level, message, **context):
    """
    Log with additional context information.
    
    Args:
        logger: Logger instance
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        **context: Additional context as key-value pairs
    """
    if context:
        context_str = " | " + " | ".join(f"{k}={v}" for k, v in context.items())
        message = message + context_str
    
    getattr(logger, level)(message)

