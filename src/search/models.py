"""Data models for search operations.

This module provides type-safe data models for search operations,
improving code quality and maintainability.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ChunkStrategy(str, Enum):
    """Text chunking strategies."""
    SEMANTIC = "semantic"
    FIXED_SIZE = "fixed_size"
    SENTENCE = "sentence"


class FileType(str, Enum):
    """Supported file types for indexing."""
    PDF = "pdf"
    TXT = "txt"
    DOCX = "docx"
    
    @classmethod
    def from_extension(cls, extension: str) -> 'FileType':
        """Get FileType from file extension."""
        ext = extension.lower().lstrip('.')
        try:
            return cls(ext)
        except ValueError:
            raise ValueError(f"Unsupported file type: {extension}")


@dataclass
class TextChunk:
    """
    Represents a chunk of text extracted from a document.
    
    Note: Mutable to allow for compatibility with existing chunking logic.
    """
    content: str
    chunk_id: int
    filename: str
    file_type: str
    metadata: Optional[Dict[str, Any]] = None
    start_pos: Optional[int] = None  # Character position in source text
    end_pos: Optional[int] = None  # Character position in source text
    
    def __post_init__(self):
        """Validate chunk data."""
        if not self.content:
            raise ValueError("Chunk content cannot be empty")
        if self.chunk_id < 0:
            raise ValueError("Chunk ID must be non-negative")
        if self.start_pos is not None and self.end_pos is not None:
            if self.end_pos <= self.start_pos:
                raise ValueError("end_pos must be greater than start_pos")


@dataclass(frozen=True)
class IndexDocument:
    """
    Document prepared for indexing in Azure AI Search.
    
    Contains all fields required by the search index schema.
    """
    id: str
    content: str
    content_vector: List[float]
    filename: str
    chunk_id: int
    file_type: str
    upload_date: str  # ISO format
    metadata: Optional[str] = None  # JSON string
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Azure Search API."""
        return {
            'id': self.id,
            'content': self.content,
            'content_vector': self.content_vector,
            'filename': self.filename,
            'chunk_id': self.chunk_id,
            'file_type': self.file_type,
            'upload_date': self.upload_date,
            'metadata': self.metadata
        }


@dataclass
class IndexResult:
    """Result of document indexing operation."""
    filename: str
    total_chunks: int
    indexed_chunks: int
    failed_chunks: int
    
    @property
    def success(self) -> bool:
        """Check if indexing was fully successful."""
        return self.failed_chunks == 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_chunks == 0:
            return 0.0
        return (self.indexed_chunks / self.total_chunks) * 100


@dataclass
class DeleteResult:
    """Result of document deletion operation."""
    filename: str
    deleted_count: int
    success: bool


@dataclass
class SearchResult:
    """Single search result from Azure AI Search."""
    id: str
    content: str
    filename: str
    chunk_id: int
    file_type: str
    score: float
    captions: List[str] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return f"SearchResult(filename={self.filename}, chunk={self.chunk_id}, score={self.score:.3f})"


@dataclass
class FileInfo:
    """Information about an indexed file."""
    filename: str
    file_type: str
    upload_date: str
    chunk_count: int
    
    def __repr__(self) -> str:
        return f"FileInfo({self.filename}, {self.chunk_count} chunks)"


@dataclass
class IndexStatistics:
    """Statistics about the search index."""
    total_documents: int
    total_files: int
    files: List[FileInfo] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return f"IndexStatistics({self.total_files} files, {self.total_documents} documents)"


@dataclass
class DownloadResult:
    """Result of document download operation."""
    filename: str
    content: str
    chunk_count: int
    success: bool
    
    def to_bytes(self, encoding: str = 'utf-8') -> bytes:
        """Convert content to bytes."""
        return self.content.encode(encoding)

