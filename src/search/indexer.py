"""Document processing and indexing to Azure AI Search."""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional, BinaryIO
from pathlib import Path
from azure.search.documents.aio import SearchClient as AzureSearchClient
from azure.core.credentials import AzureKeyCredential
# IndexDocumentsAction removed in azure-search-documents 11.6.0

from .chunking import TextChunker, TextChunk
from .embeddings import EmbeddingsGenerator

logger = logging.getLogger(__name__)


class DocumentIndexer:
    """Process and index documents to Azure AI Search."""
    
    def __init__(
        self,
        search_endpoint: str,
        index_name: str,
        api_key: str,
        embeddings_generator: EmbeddingsGenerator,
        chunker: Optional[TextChunker] = None
    ):
        """
        Initialize document indexer.
        
        Args:
            search_endpoint: Azure Search service endpoint
            index_name: Name of the search index
            api_key: Admin API key
            embeddings_generator: Embeddings generator instance
            chunker: Text chunker instance (optional)
        """
        self.search_endpoint = search_endpoint
        self.index_name = index_name
        self.api_key = api_key
        self.embeddings_generator = embeddings_generator
        self.chunker = chunker or TextChunker()
    
    def _get_client(self) -> AzureSearchClient:
        """Create a new search client for the current event loop."""
        return AzureSearchClient(
            endpoint=self.search_endpoint,
            index_name=self.index_name,
            credential=AzureKeyCredential(self.api_key)
        )
    
    def _extract_text_from_file(self, file_content: bytes, file_type: str) -> str:
        """
        Extract text from various file formats.
        
        Args:
            file_content: File content as bytes
            file_type: File extension (pdf, txt, docx, md, json, csv)
            
        Returns:
            Extracted text
        """
        try:
            if file_type in ['txt', 'md', 'json', 'csv']:
                # Text-based files
                return file_content.decode('utf-8', errors='ignore')
            
            elif file_type == 'pdf':
                # PDF extraction (requires PyPDF2 or pdfplumber)
                try:
                    import io
                    from PyPDF2 import PdfReader
                    
                    pdf_file = io.BytesIO(file_content)
                    reader = PdfReader(pdf_file)
                    
                    text_parts = []
                    for page in reader.pages:
                        text_parts.append(page.extract_text())
                    
                    return '\n\n'.join(text_parts)
                
                except ImportError:
                    logger.warning('PyPDF2 not installed, cannot extract PDF text')
                    return ''
            
            elif file_type == 'docx':
                # DOCX extraction (requires python-docx)
                try:
                    import io
                    from docx import Document
                    
                    docx_file = io.BytesIO(file_content)
                    doc = Document(docx_file)
                    
                    text_parts = [paragraph.text for paragraph in doc.paragraphs]
                    return '\n\n'.join(text_parts)
                
                except ImportError:
                    logger.warning('python-docx not installed, cannot extract DOCX text')
                    return ''
            
            else:
                logger.warning(f'Unsupported file type: {file_type}')
                return ''
        
        except Exception as e:
            logger.error(f'Failed to extract text from {file_type}: {e}')
            return ''
    
    async def index_document(
        self,
        file_content: bytes,
        filename: str,
        file_type: str,
        metadata: Optional[Dict] = None
    ) -> Dict[str, any]:
        """
        Process and index a single document.
        
        Args:
            file_content: Document content as bytes
            filename: Name of the file
            file_type: File extension
            metadata: Additional metadata
            
        Returns:
            Indexing result with statistics
        """
        try:
            # Extract text
            logger.info(f'Extracting text from {filename}')
            text = self._extract_text_from_file(file_content, file_type)
            
            if not text:
                raise ValueError(f'No text extracted from {filename}')
            
            # Chunk text
            logger.info(f'Chunking text from {filename}')
            chunks = self.chunker.chunk_text(text, filename, file_type, metadata)
            
            if not chunks:
                raise ValueError(f'No chunks created from {filename}')
            
            # Generate embeddings for all chunks
            logger.info(f'Generating embeddings for {len(chunks)} chunks')
            chunk_texts = [chunk.content for chunk in chunks]
            embeddings = await self.embeddings_generator.generate_embeddings_batch(chunk_texts)
            logger.info(f'Generated {len(embeddings) if embeddings else 0} embeddings')
            
            # Prepare documents for indexing
            documents = []
            upload_date = datetime.now(timezone.utc).isoformat()
            
            for chunk, embedding in zip(chunks, embeddings):
                if embedding is None:
                    logger.warning(f'Skipping chunk {chunk.chunk_id} - no embedding generated')
                    continue
                
                doc_id = str(uuid.uuid4())
                
                document = {
                    'id': doc_id,
                    'content': chunk.content,
                    'content_vector': embedding,
                    'filename': chunk.filename,
                    'chunk_id': chunk.chunk_id,
                    'file_type': chunk.file_type,
                    'upload_date': upload_date,
                    'metadata': str(chunk.metadata) if chunk.metadata else None
                }
                
                documents.append(document)
            
            # Check if we have documents to upload
            if not documents:
                logger.error(f'No documents to upload for {filename} - all embeddings were None or empty')
                raise ValueError(f'Failed to create indexable documents from {filename} - no valid embeddings generated')
            
            # Upload to Azure Search
            logger.info(f'Uploading {len(documents)} documents to index')
            async with self._get_client() as client:
                result = await client.upload_documents(documents=documents)
                logger.info(f'Upload result received: {len(result) if result else 0} items')
            
            # Count successes and failures
            success_count = sum(1 for r in result if r.succeeded)
            failure_count = len(result) - success_count
            
            logger.info(f'Indexed {filename}: {success_count} chunks succeeded, {failure_count} failed')
            
            return {
                'filename': filename,
                'total_chunks': len(chunks),
                'indexed_chunks': success_count,
                'failed_chunks': failure_count,
                'success': failure_count == 0
            }
        
        except Exception as e:
            logger.error(f'Failed to index document {filename}: {e}')
            raise
    
    async def delete_document_by_filename(self, filename: str) -> Dict[str, any]:
        """
        Delete all chunks of a document by filename.
        
        Args:
            filename: Name of the file to delete
            
        Returns:
            Deletion result
        """
        try:
            async with self._get_client() as client:
                # Search for all chunks with this filename
                search_results = await client.search(
                    search_text='*',
                    filter=f"filename eq '{filename}'",
                    select=['id']
                )
                
                doc_ids = [result['id'] async for result in search_results]
                
                if not doc_ids:
                    logger.warning(f'No documents found with filename: {filename}')
                    return {'filename': filename, 'deleted_count': 0}
                
                # Delete documents
                documents_to_delete = [{'id': doc_id} for doc_id in doc_ids]
                result = await client.delete_documents(documents=documents_to_delete)
            
            success_count = sum(1 for r in result if r.succeeded)
            
            logger.info(f'Deleted {success_count} chunks for file {filename}')
            
            return {
                'filename': filename,
                'deleted_count': success_count,
                'success': True
            }
        
        except Exception as e:
            logger.error(f'Failed to delete document {filename}: {e}')
            raise
    
    async def list_indexed_files(self) -> List[Dict[str, any]]:
        """
        List all unique files in the index.
        
        Returns:
            List of files with metadata
        """
        try:
            async with self._get_client() as client:
                # Get all unique filenames using facets
                search_results = await client.search(
                    search_text='*',
                    facets=['filename'],
                    select=['filename', 'file_type', 'upload_date'],
                    top=1000
                )
                
                # Group by filename
                files_dict = {}
                async for result in search_results:
                    filename = result.get('filename')
                    if filename and filename not in files_dict:
                        files_dict[filename] = {
                            'filename': filename,
                            'file_type': result.get('file_type'),
                            'upload_date': result.get('upload_date'),
                            'chunk_count': 0
                        }
                    
                    if filename:
                        files_dict[filename]['chunk_count'] += 1
                
                files = list(files_dict.values())
                logger.info(f'Found {len(files)} indexed files')
                
                return files
        
        except Exception as e:
            logger.error(f'Failed to list indexed files: {e}')
            return []
    
    async def get_index_statistics(self) -> Dict[str, any]:
        """
        Get index statistics.
        
        Returns:
            Statistics dictionary
        """
        try:
            async with self._get_client() as client:
                doc_count = await client.get_document_count()
            files = await self.list_indexed_files()
            
            return {
                'total_documents': doc_count,
                'total_files': len(files),
                'files': files
            }
        
        except Exception as e:
            logger.error(f'Failed to get index statistics: {e}')
            return {'error': str(e)}
    
    async def download_document_by_filename(self, filename: str) -> Dict[str, any]:
        """
        Download document content by filename.
        Reconstructs the original document from all chunks.
        
        Args:
            filename: Name of the file to download
            
        Returns:
            Dictionary with filename, content, and file_type
        """
        try:
            async with self._get_client() as client:
                # Search for all chunks with this filename, sorted by chunk_id
                search_results = await client.search(
                    search_text='*',
                    filter=f"filename eq '{filename}'",
                    select=['content', 'chunk_id', 'file_type'],
                    order_by=['chunk_id'],
                    top=1000
                )
                
                chunks = []
                file_type = None
                
                async for result in search_results:
                    chunks.append(result.get('content', ''))
                    if file_type is None:
                        file_type = result.get('file_type')
                
                if not chunks:
                    logger.warning(f'No chunks found for file: {filename}')
                    return {
                        'filename': filename,
                        'content': None,
                        'file_type': None,
                        'success': False,
                        'error': 'File not found'
                    }
                
                # Reconstruct document content
                content = '\n\n'.join(chunks)
                
                logger.info(f'Downloaded {filename}: {len(chunks)} chunks, {len(content)} chars')
                
                return {
                    'filename': filename,
                    'content': content,
                    'file_type': file_type,
                    'chunk_count': len(chunks),
                    'success': True
                }
        
        except Exception as e:
            logger.error(f'Failed to download document {filename}: {e}')
            return {
                'filename': filename,
                'content': None,
                'file_type': None,
                'success': False,
                'error': str(e)
            }
    
    async def close(self):
        """Close the search client. (No-op as clients are created per-request)"""
        pass

