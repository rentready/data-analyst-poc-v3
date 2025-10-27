"""Custom MCP tool for searching Knowledge Base using Azure AI Search."""

import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from src.search.client import SearchClient
from src.search.embeddings import EmbeddingsGenerator

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Knowledge base search result."""
    content: str
    filename: str
    chunk_id: int
    file_type: str
    score: float
    captions: Optional[List[str]] = None


class KnowledgeBaseSearchTool:
    """Tool for searching Knowledge Base using Azure AI Search."""
    
    def __init__(
        self,
        search_client: SearchClient,
        embeddings_generator: EmbeddingsGenerator,
        top_k: int = 5,
        min_score: float = 0.7
    ):
        """
        Initialize Knowledge Base search tool.
        
        Args:
            search_client: Azure AI Search client
            embeddings_generator: Embeddings generator
            top_k: Default number of results to return
            min_score: Minimum relevance score
        """
        self.search_client = search_client
        self.embeddings_generator = embeddings_generator
        self.top_k = top_k
        self.min_score = min_score
    
    async def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[str] = None,
        search_type: str = 'hybrid'
    ) -> List[SearchResult]:
        """
        Search the knowledge base.
        
        Args:
            query: Search query text
            top_k: Number of results to return (overrides default)
            filters: OData filter expression (e.g., "file_type eq 'pdf'")
            search_type: Type of search ('hybrid', 'vector', 'keyword')
            
        Returns:
            List of search results
        """
        try:
            k = top_k or self.top_k
            
            # Generate embedding for query
            query_embedding = None
            if search_type in ['hybrid', 'vector']:
                logger.info(f'Generating embedding for query: "{query}"')
                query_embedding = await self.embeddings_generator.generate_embedding(query)
            
            # Execute search based on type
            if search_type == 'vector' and query_embedding:
                results = await self.search_client.vector_search(
                    query_vector=query_embedding,
                    top_k=k,
                    filters=filters
                )
            elif search_type == 'keyword':
                results = await self.search_client.keyword_search(
                    query=query,
                    top_k=k,
                    filters=filters
                )
            else:  # hybrid (default)
                results = await self.search_client.search(
                    query=query,
                    query_vector=query_embedding,
                    top_k=k,
                    min_score=self.min_score,
                    filters=filters
                )
            
            # Convert to SearchResult objects
            search_results = [
                SearchResult(
                    content=r['content'],
                    filename=r['filename'],
                    chunk_id=r['chunk_id'],
                    file_type=r['file_type'],
                    score=r['score'],
                    captions=r.get('captions', [])
                )
                for r in results
            ]
            
            logger.info(f'Found {len(search_results)} results for query: "{query}"')
            return search_results
        
        except Exception as e:
            logger.error(f'Knowledge base search failed: {e}')
            raise
    
    def format_results_for_agent(self, results: List[SearchResult]) -> str:
        """
        Format search results for agent consumption.
        
        Args:
            results: List of search results
            
        Returns:
            Formatted string with all results
        """
        if not results:
            return 'No information found in the knowledge base.'
        
        formatted_parts = []
        formatted_parts.append(f'Found {len(results)} relevant results in the knowledge base:\n')
        
        for i, result in enumerate(results, 1):
            formatted_parts.append(f'\n--- Result {i} (Score: {result.score:.3f}) ---')
            formatted_parts.append(f'Source: {result.filename} (chunk {result.chunk_id})')
            
            # Add captions if available (semantic search)
            if result.captions:
                formatted_parts.append('Relevant excerpts:')
                for caption in result.captions:
                    formatted_parts.append(f'  • {caption}')
            
            # Add full content
            formatted_parts.append(f'\nContent:\n{result.content}')
            formatted_parts.append('')  # Empty line for separation
        
        return '\n'.join(formatted_parts)
    
    async def search_and_format(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[str] = None,
        search_type: str = 'hybrid'
    ) -> str:
        """
        Search and return formatted results ready for agent.
        
        Args:
            query: Search query
            top_k: Number of results
            filters: OData filters
            search_type: Search type
            
        Returns:
            Formatted search results as string
        """
        results = await self.search(query, top_k, filters, search_type)
        return self.format_results_for_agent(results)


# Function that will be exposed as MCP tool
async def search_knowledge_base_tool(
    query: str,
    top_k: int = 5,
    file_type: Optional[str] = None,
    filename: Optional[str] = None
) -> str:
    """
    Search the knowledge base for relevant information.
    
    This tool searches through indexed documents in the Knowledge Base
    using hybrid search (combining keyword and semantic vector search).
    
    Args:
        query: The search query or question to find information about
        top_k: Number of results to return (default: 5)
        file_type: Filter by file type (e.g., 'pdf', 'txt', 'md')
        filename: Filter by specific filename (partial match)
        
    Returns:
        Formatted search results with relevant excerpts and sources
        
    Example:
        result = search_knowledge_base_tool(
            query="What is DSAT and where is it stored?",
            top_k=3,
            file_type="md"
        )
    """
    try:
        # Build OData filter if needed
        filters = []
        if file_type:
            filters.append(f"file_type eq '{file_type}'")
        if filename:
            filters.append(f"search.ismatch('{filename}', 'filename')")
        
        filter_str = ' and '.join(filters) if filters else None
        
        # Get tool instance from global config (will be injected)
        # For now, this is a placeholder - actual implementation will use dependency injection
        from src.config import get_kb_search_tool
        tool = get_kb_search_tool()
        
        # Perform search
        result = await tool.search_and_format(
            query=query,
            top_k=top_k,
            filters=filter_str,
            search_type='hybrid'
        )
        
        return result
    
    except Exception as e:
        logger.error(f'Search tool error: {e}')
        return f'Error searching knowledge base: {str(e)}'

