"""Interfaces for search components (SOLID: DIP, ISP)."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, BinaryIO
from dataclasses import dataclass


@dataclass
class TextChunk:
    """Represents a chunk of text with metadata."""
    content: str
    chunk_id: int
    filename: str
    file_type: str
    metadata: Optional[Dict[str, Any]] = None


class IEmbeddingsGenerator(ABC):
    """Interface for embeddings generation."""
    
    @abstractmethod
    async def generate_embeddings(self, text: str) -> Optional[List[float]]:
        """
        Generate embeddings for a single text.
        
        Args:
            text: Input text
            
        Returns:
            List of floats representing the embedding, or None if failed
        """
        pass
    
    @abstractmethod
    async def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of input texts
            
        Returns:
            List of embeddings (each can be None if generation failed)
        """
        pass


class ITextChunker(ABC):
    """Interface for text chunking."""
    
    @abstractmethod
    def chunk_text(
        self,
        text: str,
        filename: str,
        file_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[TextChunk]:
        """
        Split text into chunks.
        
        Args:
            text: Text to chunk
            filename: Source filename
            file_type: Type of file
            metadata: Optional metadata
            
        Returns:
            List of TextChunk objects
        """
        pass


class ISearchClient(ABC):
    """Interface for search client operations."""
    
    @abstractmethod
    async def upload_documents(self, documents: List[Dict[str, Any]]) -> List[Any]:
        """Upload documents to the search index."""
        pass
    
    @abstractmethod
    async def search(self, **kwargs) -> Any:
        """Execute a search query."""
        pass
    
    @abstractmethod
    async def delete_documents(self, documents: List[Dict[str, Any]]) -> List[Any]:
        """Delete documents from the search index."""
        pass
    
    @abstractmethod
    async def get_document_count(self) -> int:
        """Get total number of documents in the index."""
        pass


class ISearchClientFactory(ABC):
    """Factory interface for creating search clients."""
    
    @abstractmethod
    def create_client(self) -> ISearchClient:
        """Create a new search client instance."""
        pass

