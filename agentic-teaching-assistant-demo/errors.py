"""
Custom exception classes for AgenticTA.

Provides specific exceptions for different error scenarios to enable
better error handling and user-friendly error messages.
"""


class AgenticTAError(Exception):
    """Base exception for all AgenticTA errors."""
    pass


class LLMError(AgenticTAError):
    """Base exception for LLM-related errors."""
    pass


class LLMAPIError(LLMError):
    """Raised when LLM API call fails."""
    def __init__(self, message, provider=None, status_code=None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class LLMRateLimitError(LLMError):
    """Raised when LLM API rate limit is exceeded."""
    def __init__(self, message, retry_after=None):
        self.retry_after = retry_after
        super().__init__(message)


class LLMResponseError(LLMError):
    """Raised when LLM response cannot be parsed."""
    pass


class RAGError(AgenticTAError):
    """Base exception for RAG-related errors."""
    pass


class RAGConnectionError(RAGError):
    """Raised when cannot connect to RAG server."""
    def __init__(self, message, server_url=None):
        self.server_url = server_url
        super().__init__(message)


class RAGSearchError(RAGError):
    """Raised when document search fails."""
    pass


class DocumentProcessingError(AgenticTAError):
    """Raised when PDF processing fails."""
    def __init__(self, message, pdf_path=None, page_number=None):
        self.pdf_path = pdf_path
        self.page_number = page_number
        super().__init__(message)


class CurriculumGenerationError(AgenticTAError):
    """Raised when curriculum generation fails."""
    pass


class UserStateError(AgenticTAError):
    """Raised when user state operations fail."""
    def __init__(self, message, user_id=None):
        self.user_id = user_id
        super().__init__(message)


class ConfigurationError(AgenticTAError):
    """Raised when configuration is invalid or missing."""
    pass


# User-friendly error messages mapping
USER_FRIENDLY_MESSAGES = {
    LLMAPIError: (
        "⚠️  AI Service Issue\n"
        "The AI service is temporarily unavailable. Please try again in a moment.\n\n"
        "Technical details: {error}"
    ),
    LLMRateLimitError: (
        "⏳ Rate Limit Reached\n"
        "We're processing requests too quickly. Please wait {retry_after} seconds and try again.\n\n"
        "Tip: Try uploading fewer PDFs at once."
    ),
    RAGConnectionError: (
        "⚠️  Connection Issue\n"
        "The document search service is not ready yet. Please wait 30 seconds and try again.\n\n"
        "Technical details: Cannot connect to {server_url}"
    ),
    DocumentProcessingError: (
        "📄 PDF Processing Error\n"
        "We couldn't process the PDF file '{pdf_path}'.\n\n"
        "Please ensure:\n"
        "• The PDF is not corrupted\n"
        "• The PDF contains readable text (not just images)\n"
        "• The file size is under 50MB"
    ),
    CurriculumGenerationError: (
        "❌ Curriculum Generation Failed\n"
        "We couldn't generate the curriculum from your PDFs.\n\n"
        "Please try:\n"
        "• Uploading different PDF files\n"
        "• Checking that PDFs contain educational content\n"
        "• Contacting support if the issue persists"
    ),
}


def get_user_friendly_message(error: Exception) -> str:
    """
    Get a user-friendly error message for an exception.
    
    Args:
        error: Exception instance
    
    Returns:
        str: User-friendly error message
    """
    error_type = type(error)
    template = USER_FRIENDLY_MESSAGES.get(error_type)
    
    if not template:
        # Generic message for unknown errors
        return (
            f"❌ An Error Occurred\n"
            f"{str(error)}\n\n"
            f"Please try again or contact support if the issue persists."
        )
    
    # Format template with error attributes
    try:
        return template.format(
            error=str(error),
            **{k: v for k, v in vars(error).items() if isinstance(v, (str, int, float))}
        )
    except (KeyError, AttributeError):
        return template.format(error=str(error))

