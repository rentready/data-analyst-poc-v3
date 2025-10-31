"""Azure AI Search client wrapper."""

import logging
from typing import List, Dict, Optional, Any
from azure.search.documents.aio import SearchClient as AzureSearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery, QueryType, QueryCaptionType, QueryAnswerType

logger = logging.getLogger(__name__)

# Configuration constants
VECTOR_FIELD_NAME = 'content_vector'
SEMANTIC_CONFIG_NAME = 'semantic-config'
DEFAULT_MIN_SCORE = 0.0
DEFAULT_TOP_K = 5


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
        top_k: int = DEFAULT_TOP_K,
        min_score: float = DEFAULT_MIN_SCORE,
        filters: Optional[str] = None,
        search_type: str = 'hybrid'
    ) -> List[Dict[str, Any]]:
        """
        Search the index using specified search type.
        Returns all fields from the index automatically.
        
        Args:
            query: Text query
            query_vector: Query embedding vector (optional, for hybrid/vector search)
            top_k: Number of results to return (default: 5)
            min_score: Minimum relevance score (default: 0.0)
            filters: OData filter expression
            search_type: Type of search ('hybrid', 'semantic', 'keyword', 'vector')
            
        Returns:
            List of search results with scores and all available fields
        """
        try:
            # Build search parameters
            search_params = self._build_search_params(
                query=query,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
                search_type=search_type
            )
            
            # Execute search and process results
            results = await self._execute_search(search_params, min_score)
            
            logger.info(f'Search completed: {len(results)} results for query "{query}" (type: {search_type})')
            return results
        
        except Exception as e:
            logger.error(f'Search failed for query "{query}" (type: {search_type}): {e}', exc_info=True)
            raise
    
    def _build_search_params(
        self,
        query: str,
        query_vector: Optional[List[float]],
        top_k: int,
        filters: Optional[str],
        search_type: str
    ) -> Dict[str, Any]:
        """
        Build search parameters dictionary.
        
        Args:
            query: Text query
            query_vector: Query embedding vector
            top_k: Number of results
            filters: OData filters
            search_type: Type of search
            
        Returns:
            Dictionary of search parameters
        """
        search_params = {
            'search_text': query,
            'top': top_k
        }
        
        # Add vector search if applicable
        if query_vector and search_type in ['hybrid', 'vector'] and self.use_hybrid_search:
            search_params['vector_queries'] = [self._create_vector_query(query_vector, top_k)]
        
        # Add semantic search configuration if applicable
        if search_type in ['semantic', 'hybrid'] and self.use_semantic_search:
            search_params.update(self._get_semantic_params())
        
        # Add filters if provided
        if filters:
            search_params['filter'] = filters
        
        return search_params
    
    @staticmethod
    def _create_vector_query(query_vector: List[float], top_k: int) -> VectorizedQuery:
        """
        Create a vectorized query object.
        
        Args:
            query_vector: Query embedding vector
            top_k: Number of nearest neighbors
            
        Returns:
            VectorizedQuery object
        """
        return VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=top_k,
            fields=VECTOR_FIELD_NAME
        )
    
    @staticmethod
    def _get_semantic_params() -> Dict[str, Any]:
        """
        Get semantic search parameters.
        
        Returns:
            Dictionary of semantic search parameters
        """
        return {
            'query_type': QueryType.SEMANTIC,
            'semantic_configuration_name': SEMANTIC_CONFIG_NAME,
            'query_caption': QueryCaptionType.EXTRACTIVE,
            'query_answer': QueryAnswerType.EXTRACTIVE
        }
    
    async def _execute_search(
        self,
        search_params: Dict[str, Any],
        min_score: float
    ) -> List[Dict[str, Any]]:
        """
        Execute search and process results.
        
        Args:
            search_params: Search parameters dictionary
            min_score: Minimum relevance score filter
            
        Returns:
            List of processed search results
        """
        results = []
        
        async with self._get_client() as client:
            search_results = await client.search(**search_params)
            
            async for result in search_results:
                score = result.get('@search.score', 0.0)
                
                # Filter by minimum score
                if score >= min_score:
                    result_dict = self._process_search_result(result, score)
                    results.append(result_dict)
        
        return results
    
    @staticmethod
    def _process_search_result(result: Dict[str, Any], score: float) -> Dict[str, Any]:
        """
        Process a single search result.
        
        Args:
            result: Raw search result from Azure AI Search
            score: Search relevance score
            
        Returns:
            Processed result dictionary
        """
        result_dict = {'score': score}
        
        # Add all non-internal fields
        for key, value in result.items():
            if not key.startswith('@search.'):
                result_dict[key] = value
        
        # Add semantic captions if available
        captions = result.get('@search.captions', [])
        if captions:
            result_dict['captions'] = SearchClient._extract_caption_texts(captions)
        
        return result_dict
    
    @staticmethod
    def _extract_caption_texts(captions: List[Any]) -> List[str]:
        """
        Extract text from caption objects.
        
        Args:
            captions: List of caption objects (dict or string)
            
        Returns:
            List of caption text strings
        """
        caption_texts = []
        
        for caption in captions:
            if isinstance(caption, dict):
                text = caption.get('text', '')
                if text:
                    caption_texts.append(text)
            elif isinstance(caption, str):
                caption_texts.append(caption)
        
        return caption_texts
    
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

