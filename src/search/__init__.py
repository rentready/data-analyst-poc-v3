"""Azure AI Search integration for Knowledge Base.

This module provides a complete solution for document indexing,
search, and knowledge base management using Azure AI Search.
"""

# Core components
from .client import SearchClient
from .indexer import DocumentIndexer
from .embeddings import EmbeddingsGenerator
from .chunking import TextChunker

# Data models
from .models import (
    TextChunk,
    IndexDocument,
    IndexResult,
    DeleteResult,
    SearchResult,
    FileInfo,
    IndexStatistics,
    DownloadResult,
    ChunkStrategy,
    FileType
)

# Interfaces
from .interfaces import (
    IEmbeddingsGenerator,
    ITextChunker,
    ISearchClient,
    ISearchClientFactory
)

# Exceptions
from .exceptions import (
    SearchError,
    EmbeddingGenerationError,
    DocumentIndexingError,
    DocumentNotFoundError,
    TextExtractionError,
    UnsupportedFileTypeError,
    ChunkingError,
    SearchQueryError,
    IndexConfigurationError
)

# Constants
from .constants import SearchDefaults, FileExtensions, IndexFieldNames

__all__ = [
    # Core
    'SearchClient',
    'DocumentIndexer',
    'EmbeddingsGenerator',
    'TextChunker',
    # Models
    'TextChunk',
    'IndexDocument',
    'IndexResult',
    'DeleteResult',
    'SearchResult',
    'FileInfo',
    'IndexStatistics',
    'DownloadResult',
    'ChunkStrategy',
    'FileType',
    # Interfaces
    'IEmbeddingsGenerator',
    'ITextChunker',
    'ISearchClient',
    'ISearchClientFactory',
    # Exceptions
    'SearchError',
    'EmbeddingGenerationError',
    'DocumentIndexingError',
    'DocumentNotFoundError',
    'TextExtractionError',
    'UnsupportedFileTypeError',
    'ChunkingError',
    'SearchQueryError',
    'IndexConfigurationError',
    # Constants
    'SearchDefaults',
    'FileExtensions',
    'IndexFieldNames',
]

