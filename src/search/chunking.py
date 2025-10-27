"""Text chunking strategies for document processing."""

import logging
import re
from typing import List, Dict, Optional

from .models import TextChunk
from .constants import SearchDefaults

logger = logging.getLogger(__name__)


class TextChunker:
    """Chunk text using various strategies."""
    
    def __init__(
        self,
        chunk_size: int = SearchDefaults.CHUNK_SIZE,
        chunk_overlap: int = SearchDefaults.CHUNK_OVERLAP,
        strategy: str = 'semantic'
    ):
        """
        Initialize text chunker.
        
        Args:
            chunk_size: Maximum size of each chunk (in characters)
            chunk_overlap: Number of characters to overlap between chunks
            strategy: Chunking strategy ('fixed_size', 'semantic', 'sentence')
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy
    
    def chunk_text(
        self,
        text: str,
        filename: str,
        file_type: str,
        metadata: Optional[Dict] = None
    ) -> List[TextChunk]:
        """
        Chunk text using configured strategy.
        
        Args:
            text: Text to chunk
            filename: Source filename
            file_type: Type of file (pdf, txt, etc.)
            metadata: Additional metadata
            
        Returns:
            List of TextChunk objects
        """
        if self.strategy == 'semantic':
            return self._semantic_chunking(text, filename, file_type, metadata)
        elif self.strategy == 'sentence':
            return self._sentence_chunking(text, filename, file_type, metadata)
        else:
            return self._fixed_chunking(text, filename, file_type, metadata)
    
    def _fixed_chunking(
        self,
        text: str,
        filename: str,
        file_type: str,
        metadata: Optional[Dict] = None
    ) -> List[TextChunk]:
        """
        Fixed-size chunking with overlap.
        Simple but effective for most use cases.
        """
        chunks = []
        text_length = len(text)
        
        if text_length == 0:
            return []
        
        start = 0
        chunk_id = 0
        
        while start < text_length:
            end = min(start + self.chunk_size, text_length)
            
            # Try to break at sentence boundary if possible
            if end < text_length:
                # Look for sentence end markers
                sentence_end = max(
                    text.rfind('.', start, end),
                    text.rfind('!', start, end),
                    text.rfind('?', start, end),
                    text.rfind('\n\n', start, end)
                )
                
                if sentence_end > start + self.chunk_size // 2:
                    end = sentence_end + 1
            
            chunk_text = text[start:end].strip()
            
            if chunk_text:
                chunks.append(TextChunk(
                    content=chunk_text,
                    chunk_id=chunk_id,
                    filename=filename,
                    file_type=file_type,
                    metadata=metadata,
                    start_pos=start,
                    end_pos=end
                ))
                chunk_id += 1
            
            # Move start with overlap
            start = end - self.chunk_overlap if end < text_length else text_length
        
        logger.info(f'Created {len(chunks)} fixed-size chunks from {filename}')
        return chunks
    
    def _semantic_chunking(
        self,
        text: str,
        filename: str,
        file_type: str,
        metadata: Optional[Dict] = None
    ) -> List[TextChunk]:
        """
        Semantic chunking based on document structure.
        Splits by sections, paragraphs, and semantic boundaries.
        """
        chunks = []
        chunk_id = 0
        
        # Split by major sections (headers, double newlines)
        sections = re.split(r'\n\n+|\n#+\s', text)
        
        current_chunk = []
        current_length = 0
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
            
            section_length = len(section)
            
            # If section is too large, split it further
            if section_length > self.chunk_size:
                # Finalize current chunk if exists
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append(TextChunk(
                        content=chunk_text,
                        chunk_id=chunk_id,
                        filename=filename,
                        file_type=file_type,
                        metadata=metadata
                    ))
                    chunk_id += 1
                    current_chunk = []
                    current_length = 0
                
                # Split large section using fixed chunking
                subsections = self._split_large_section(section)
                for subsection in subsections:
                    chunks.append(TextChunk(
                        content=subsection,
                        chunk_id=chunk_id,
                        filename=filename,
                        file_type=file_type,
                        metadata=metadata
                    ))
                    chunk_id += 1
            
            # Add section to current chunk if it fits
            elif current_length + section_length <= self.chunk_size:
                current_chunk.append(section)
                current_length += section_length + 2  # +2 for newlines
            
            # Finalize current chunk and start new one
            else:
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append(TextChunk(
                        content=chunk_text,
                        chunk_id=chunk_id,
                        filename=filename,
                        file_type=file_type,
                        metadata=metadata
                    ))
                    chunk_id += 1
                
                current_chunk = [section]
                current_length = section_length
        
        # Finalize last chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append(TextChunk(
                content=chunk_text,
                chunk_id=chunk_id,
                filename=filename,
                file_type=file_type,
                metadata=metadata
            ))
        
        logger.info(f'Created {len(chunks)} semantic chunks from {filename}')
        return chunks
    
    def _sentence_chunking(
        self,
        text: str,
        filename: str,
        file_type: str,
        metadata: Optional[Dict] = None
    ) -> List[TextChunk]:
        """
        Sentence-based chunking.
        Keeps sentences intact, groups them into chunks.
        """
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        chunks = []
        chunk_id = 0
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            sentence_length = len(sentence)
            
            # If single sentence is too large, split it
            if sentence_length > self.chunk_size:
                # Finalize current chunk
                if current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    chunks.append(TextChunk(
                        content=chunk_text,
                        chunk_id=chunk_id,
                        filename=filename,
                        file_type=file_type,
                        metadata=metadata
                    ))
                    chunk_id += 1
                    current_chunk = []
                    current_length = 0
                
                # Split long sentence using fixed chunking
                parts = self._split_large_section(sentence)
                for part in parts:
                    chunks.append(TextChunk(
                        content=part,
                        chunk_id=chunk_id,
                        filename=filename,
                        file_type=file_type,
                        metadata=metadata
                    ))
                    chunk_id += 1
            
            # Add sentence to current chunk
            elif current_length + sentence_length <= self.chunk_size:
                current_chunk.append(sentence)
                current_length += sentence_length + 1  # +1 for space
            
            # Finalize current chunk and start new one
            else:
                if current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    chunks.append(TextChunk(
                        content=chunk_text,
                        chunk_id=chunk_id,
                        filename=filename,
                        file_type=file_type,
                        metadata=metadata
                    ))
                    chunk_id += 1
                
                current_chunk = [sentence]
                current_length = sentence_length
        
        # Finalize last chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunks.append(TextChunk(
                content=chunk_text,
                chunk_id=chunk_id,
                filename=filename,
                file_type=file_type,
                metadata=metadata
            ))
        
        logger.info(f'Created {len(chunks)} sentence-based chunks from {filename}')
        return chunks
    
    def _split_large_section(self, text: str) -> List[str]:
        """Split a large section into smaller parts."""
        parts = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            end = min(start + self.chunk_size, text_length)
            parts.append(text[start:end].strip())
            start = end - self.chunk_overlap if end < text_length else text_length
        
        return parts

