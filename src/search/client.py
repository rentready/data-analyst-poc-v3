"""Azure AI Search client wrapper."""

import logging
from typing import List, Dict, Optional, Any
from azure.search.documents.aio import SearchClient as AzureSearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery, QueryType, QueryCaptionType, QueryAnswerType

logger = logging.getLogger(__name__)


class SearchClient:
    """Wrapper for Azure AI Search client with optimized search methods."""
    
    def __init__(
        self,
        endpoint: str,
        index_name: str,
        api_key: str,
        use_semantic_search: bool = True,
        use_hybrid_search: bool = True
    ):
        """
        Initialize Azure AI Search client.
        
        Args:
            endpoint: Azure Search service endpoint
            index_name: Name of the search index
            api_key: Admin or query API key
            use_semantic_search: Enable semantic search
            use_hybrid_search: Enable hybrid search (keyword + vector)
        """
        self.endpoint = endpoint
        self.index_name = index_name
        self.api_key = api_key
        self.use_semantic_search = use_semantic_search
        self.use_hybrid_search = use_hybrid_search
    
    def _get_client(self) -> AzureSearchClient:
        """Create a new search client for the current event loop."""
        return AzureSearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=AzureKeyCredential(self.api_key)
        )
    
    async def search(
        self,
        query: str,
        query_vector: Optional[List[float]] = None,
        top_k: int = 5,
        min_score: float = 0.0,
        filters: Optional[str] = None,
        select_fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search the index using hybrid search (keyword + vector).
        
        Args:
            query: Text query
            query_vector: Query embedding vector
            top_k: Number of results to return
            min_score: Minimum relevance score (0-1)
            filters: OData filter expression
            select_fields: Fields to return
            
        Returns:
            List of search results with scores
        """
        try:
            search_params = {
                'search_text': query,
                'top': top_k,
                'select': select_fields or ['id', 'content', 'filename', 'chunk_id', 'file_type']
            }
            
            # Add vector search if embedding provided
            if query_vector and self.use_hybrid_search:
                vector_query = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=top_k,
                    fields='content_vector'
                )
                search_params['vector_queries'] = [vector_query]
            
            # Add semantic search configuration
            if self.use_semantic_search:
                search_params['query_type'] = QueryType.SEMANTIC
                search_params['semantic_configuration_name'] = 'semantic-config'
                search_params['query_caption'] = QueryCaptionType.EXTRACTIVE
                search_params['query_answer'] = QueryAnswerType.EXTRACTIVE
            
            # Add filters if provided
            if filters:
                search_params['filter'] = filters
            
            # Execute search
            results = []
            async with self._get_client() as client:
                search_results = await client.search(**search_params)
                
                async for result in search_results:
                    score = result.get('@search.score', 0.0)
                    
                    # Filter by minimum score
                    if score >= min_score:
                        results.append({
                            'id': result.get('id'),
                            'content': result.get('content'),
                            'filename': result.get('filename'),
                            'chunk_id': result.get('chunk_id'),
                            'file_type': result.get('file_type'),
                            'score': score,
                            'captions': result.get('@search.captions', []) if self.use_semantic_search else []
                        })
            
            logger.info(f'Search completed: {len(results)} results for query "{query}"')
            return results
        
        except Exception as e:
            logger.error(f'Search failed: {e}')
            raise
    
    async def vector_search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Pure vector search (no text query).
        
        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            filters: OData filter expression
            
        Returns:
            List of search results
        """
        try:
            vector_query = VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top_k,
                fields='content_vector'
            )
            
            search_params = {
                'search_text': None,
                'vector_queries': [vector_query],
                'select': ['id', 'content', 'filename', 'chunk_id', 'file_type'],
                'top': top_k
            }
            
            if filters:
                search_params['filter'] = filters
            
            results = []
            async with self._get_client() as client:
                search_results = await client.search(**search_params)
                
                async for result in search_results:
                    results.append({
                        'id': result.get('id'),
                        'content': result.get('content'),
                        'filename': result.get('filename'),
                        'chunk_id': result.get('chunk_id'),
                        'file_type': result.get('file_type'),
                        'score': result.get('@search.score', 0.0)
                    })
            
            logger.info(f'Vector search completed: {len(results)} results')
            return results
        
        except Exception as e:
            logger.error(f'Vector search failed: {e}')
            raise
    
    async def keyword_search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Pure keyword search (no vector).
        
        Args:
            query: Text query
            top_k: Number of results to return
            filters: OData filter expression
            
        Returns:
            List of search results
        """
        try:
            search_params = {
                'search_text': query,
                'top': top_k,
                'select': ['id', 'content', 'filename', 'chunk_id', 'file_type']
            }
            
            if filters:
                search_params['filter'] = filters
            
            results = []
            async with self._get_client() as client:
                search_results = await client.search(**search_params)
                
                async for result in search_results:
                    results.append({
                        'id': result.get('id'),
                        'content': result.get('content'),
                        'filename': result.get('filename'),
                        'chunk_id': result.get('chunk_id'),
                        'file_type': result.get('file_type'),
                        'score': result.get('@search.score', 0.0)
                    })
            
            logger.info(f'Keyword search completed: {len(results)} results for query "{query}"')
            return results
        
        except Exception as e:
            logger.error(f'Keyword search failed: {e}')
            raise
    
    async def get_document_count(self) -> int:
        """Get total number of documents in the index."""
        try:
            async with self._get_client() as client:
                result = await client.get_document_count()
            return result
        except Exception as e:
            logger.error(f'Failed to get document count: {e}')
            return 0
    
    async def close(self):
        """Close the search client. (No-op as clients are created per-request)"""
        pass

