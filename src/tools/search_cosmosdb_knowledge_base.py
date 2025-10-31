"""Tool for searching Cosmos DB knowledge base via Azure AI Search."""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_TOP_K = 10
MAX_CAPTIONS_PER_RESULT = 2
DEFAULT_SEARCH_TYPE = 'semantic'


class CosmosDBKnowledgeBaseSearchTool:
    """
    Tool for searching Cosmos DB accounts/properties knowledge base.
    
    Responsibilities:
    - Search Cosmos DB index via Azure AI Search
    - Format search results for agent consumption
    
    Uses semantic search (no vector embeddings needed for Cosmos DB).
    """
    
    def __init__(self, search_client):
        """
        Initialize Cosmos DB knowledge base search tool.
        
        Args:
            search_client: Azure AI Search client instance
        """
        self.search_client = search_client
        logger.info('Initialized CosmosDBKnowledgeBaseSearchTool')
    
    async def search_and_format(
        self, 
        query: str, 
        top_k: int = DEFAULT_TOP_K,
        search_type: str = DEFAULT_SEARCH_TYPE
    ) -> str:
        """
        Search Cosmos DB knowledge base and format results for agent consumption.
        
        Args:
            query: Search query
            top_k: Number of results to return (default: 10)
            search_type: Type of search - always 'semantic' for Cosmos DB
            
        Returns:
            Formatted search results as string
        """
        try:
            logger.info(f'🔍 Cosmos DB KB searching for: "{query}" (top_k={top_k}, type={search_type})')
            
            # Perform search (always semantic, NO vector search for Cosmos DB)
            results = await self.search_client.search(
                query=query,
                top_k=top_k,
                search_type=DEFAULT_SEARCH_TYPE  # Always semantic (no vector embeddings)
            )
            
            if not results:
                logger.info('❌ No results found in Cosmos DB')
                return f'No relevant accounts or properties found for query: "{query}"'
            
            # Format results using helper method
            formatted_text = self._format_results(results)
            
            logger.info(f'✅ Formatted {len(results)} Cosmos DB results ({len(formatted_text)} chars)')
            return formatted_text
            
        except Exception as e:
            logger.error(f'❌ Cosmos DB KB search error: {e}', exc_info=True)
            return f'Error searching Cosmos DB knowledge base: {str(e)}'
    
    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Format search results for agent consumption.
        
        Args:
            results: List of search results from Azure AI Search
            
        Returns:
            Formatted string with all results
        """
        formatted_results = [f'Found {len(results)} relevant accounts/properties:\n']
        
        for idx, result in enumerate(results, 1):
            formatted_results.append(self._format_single_result(idx, result))
        
        return '\n'.join(formatted_results)
    
    def _format_single_result(self, idx: int, result: Dict[str, Any]) -> str:
        """
        Format a single search result.
        
        Args:
            idx: Result index (1-based)
            result: Single search result dictionary
            
        Returns:
            Formatted result string
        """
        lines = [f'\n--- Result {idx} ---']
        
        # Add account information
        lines.append(f'Account Name: {result.get("name", "N/A")}')
        lines.append(f'Account ID: {result.get("accountid", "N/A")}')
        lines.append(f'Account Number: {result.get("accountnumber", "N/A")}')
        
        # Add location
        location = self._format_location(result)
        lines.append(f'Location: {location}')
        
        # Add relevance score
        score = result.get('score')
        if score is not None:
            lines.append(f'Relevance Score: {score:.2f}')
        
        # Add semantic captions
        captions_text = self._format_captions(result.get('captions', []))
        if captions_text:
            lines.append(captions_text)
        
        return '\n'.join(lines)
    
    @staticmethod
    def _format_location(result: Dict[str, Any]) -> str:
        """
        Format location from city and state fields.
        
        Args:
            result: Search result dictionary
            
        Returns:
            Formatted location string
        """
        city = result.get('address1_city', '')
        state = result.get('address1_stateorprovince', '')
        
        if city or state:
            return f'{city}, {state}' if city and state else (city or state)
        return 'N/A'
    
    @staticmethod
    def _format_captions(captions: List[Any]) -> str:
        """
        Format semantic captions from search results.
        
        Args:
            captions: List of caption objects (dict or string)
            
        Returns:
            Formatted captions string or empty string
        """
        if not captions:
            return ''
        
        caption_lines = ['Key Information:']
        
        for caption in captions[:MAX_CAPTIONS_PER_RESULT]:
            caption_text = ''
            
            if isinstance(caption, dict):
                caption_text = caption.get('text', '')
            elif isinstance(caption, str):
                caption_text = caption
            
            if caption_text:
                caption_lines.append(f'  • {caption_text}')
        
        return '\n'.join(caption_lines) if len(caption_lines) > 1 else ''

