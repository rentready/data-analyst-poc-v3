"""Custom exceptions for search operations.

This module defines exception hierarchy for better error handling
and debugging in search operations.
"""

from typing import Optional


class SearchError(Exception):
    """Base exception for all search-related errors."""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error
        self.message = message
    
    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


class EmbeddingGenerationError(SearchError):
    """Raised when embedding generation fails."""
    
    def __init__(self, text_preview: str, original_error: Exception):
        """
        Initialize embedding generation error.
        
        Args:
            text_preview: First 50 chars of text that failed
            original_error: Original exception from embeddings API
        """
        self.text_preview = text_preview[:50] + "..." if len(text_preview) > 50 else text_preview
        super().__init__(
            f"Failed to generate embedding for text: '{self.text_preview}'",
            original_error
        )


class DocumentIndexingError(SearchError):
    """Raised when document indexing fails."""
    
    def __init__(self, filename: str, reason: str, original_error: Optional[Exception] = None):
        self.filename = filename
        self.reason = reason
        super().__init__(
            f"Failed to index document '{filename}': {reason}",
            original_error
        )


class DocumentNotFoundError(SearchError):
    """Raised when document is not found in index."""
    
    def __init__(self, filename: str):
        self.filename = filename
        super().__init__(f"Document not found in index: '{filename}'")


class TextExtractionError(SearchError):
    """Raised when text extraction from file fails."""
    
    def __init__(self, filename: str, file_type: str, original_error: Exception):
        self.filename = filename
        self.file_type = file_type
        super().__init__(
            f"Failed to extract text from '{filename}' (type: {file_type})",
            original_error
        )


class UnsupportedFileTypeError(SearchError):
    """Raised when file type is not supported."""
    
    def __init__(self, file_type: str):
        self.file_type = file_type
        super().__init__(f"Unsupported file type: '{file_type}'")


class ChunkingError(SearchError):
    """Raised when text chunking fails."""
    
    def __init__(self, reason: str, original_error: Optional[Exception] = None):
        self.reason = reason
        super().__init__(f"Failed to chunk text: {reason}", original_error)


class SearchQueryError(SearchError):
    """Raised when search query execution fails."""
    
    def __init__(self, query: str, original_error: Exception):
        self.query = query
        super().__init__(
            f"Failed to execute search query: '{query[:100]}'",
            original_error
        )


class IndexConfigurationError(SearchError):
    """Raised when search index configuration is invalid."""
    
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Invalid index configuration: {reason}")

