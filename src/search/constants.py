"""Constants for search operations.

This module centralizes magic numbers and strings to improve maintainability.
"""


class SearchDefaults:
    """Default values for search operations."""
    
    # Search parameters
    MIN_SCORE = 0.0  # Minimum relevance score (0.0 = no filtering)
    TOP_K = 5  # Number of results to return
    
    # Chunking parameters
    CHUNK_SIZE = 500  # Default chunk size in characters
    CHUNK_OVERLAP = 50  # Overlap between chunks
    
    # Embeddings parameters
    BATCH_SIZE = 10  # Number of texts to embed in one batch
    MAX_RETRIES = 3  # Maximum retry attempts for API calls
    
    # Index parameters
    MAX_UPLOAD_BATCH = 1000  # Max documents per upload batch


class FileExtensions:
    """Supported file extensions."""
    PDF = '.pdf'
    TXT = '.txt'
    DOCX = '.docx'
    
    ALL = [PDF, TXT, DOCX]
    
    @classmethod
    def is_supported(cls, extension: str) -> bool:
        """Check if file extension is supported."""
        return extension.lower() in cls.ALL


class IndexFieldNames:
    """Azure Search index field names."""
    ID = 'id'
    CONTENT = 'content'
    CONTENT_VECTOR = 'content_vector'
    FILENAME = 'filename'
    CHUNK_ID = 'chunk_id'
    FILE_TYPE = 'file_type'
    UPLOAD_DATE = 'upload_date'
    METADATA = 'metadata'


class ErrorMessages:
    """Standard error messages."""
    NO_TEXT_EXTRACTED = "No text could be extracted from the file"
    NO_CHUNKS_CREATED = "No chunks were created from the text"
    EMBEDDING_FAILED = "Failed to generate embeddings"
    INDEXING_FAILED = "Failed to index document"
    FILE_NOT_FOUND = "File not found in index"
    INVALID_FILE_TYPE = "Unsupported file type"


class LogMessages:
    """Standard log messages."""
    EXTRACTING_TEXT = "Extracting text from {filename}"
    CHUNKING_TEXT = "Chunking text from {filename}"
    GENERATING_EMBEDDINGS = "Generating embeddings for {count} chunks"
    UPLOADING_DOCS = "Uploading {count} documents to index"
    INDEXED_SUCCESS = "Indexed {filename}: {success} chunks succeeded, {failed} failed"
    DELETED_SUCCESS = "Deleted {count} chunks for file {filename}"
    DOWNLOADED_SUCCESS = "Downloaded {filename}: {chunks} chunks, {chars} chars"

