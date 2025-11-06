"""Custom Azure AI Search Tool for Azure AI Agent Framework."""
import logging
from typing import Dict, Any, Optional
import asyncio

logger = logging.getLogger(__name__)


class AzureSearchTool:
    """
    Custom tool for Azure AI Agent Framework that wraps Azure AI Search functionality.
    This tool is designed to be compatible with Azure AI Agents function calling.
    """
    
    def __init__(self, file_search_client, cosmosdb_search_client, embeddings_generator):
        """
        Initialize the Azure Search Tool.
        
        Args:
            file_search_client: SearchClient for file-based knowledge base
            cosmosdb_search_client: SearchClient for Cosmos DB knowledge base
            embeddings_generator: EmbeddingsGenerator instance
        """
        self.file_search_client = file_search_client
        self.cosmosdb_search_client = cosmosdb_search_client
        self.embeddings_generator = embeddings_generator
        
        logger.info("AzureSearchTool initialized")
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """
        Get the tool definition for Azure AI Agent Framework.
        Returns OpenAI function calling compatible schema.
        """
        return {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": (
                    "Search for information in the knowledge base. "
                    "Use this to find business terms, definitions, company names, and property information. "
                    "Searches both uploaded documents and Cosmos DB account data."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query - term, company name, or question to search for"
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["files", "cosmosdb", "both"],
                            "description": "Where to search: 'files' for documents, 'cosmosdb' for accounts, 'both' for everything",
                            "default": "both"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    
    async def _search_files(self, query: str, top_k: int = 5) -> str:
        """Search in file-based knowledge base using keyword search (NO embeddings needed)."""
        try:
            logger.info(f"Searching files with keyword search: '{query}'")
            
            # Use KEYWORD search ONLY (no embeddings needed)
            results = await self.file_search_client.search(
                query=query,
                search_type="keyword",  # KEYWORD ONLY!
                top_k=top_k
            )
            
            if not results:
                return "No results found in files."
            
            # Format results
            formatted_results = []
            for i, result in enumerate(results, 1):
                filename = result.get('filename', 'Unknown')
                content = result.get('content', '')[:500]
                formatted_results.append(
                    f"Result {i} (File: {filename}):\n{content}\n"
                )
            
            logger.info(f"Found {len(results)} results in files")
            return "\n".join(formatted_results)
            
        except Exception as e:
            logger.error(f"Error searching files: {e}", exc_info=True)
            return f"Error searching files: {str(e)}"
    
    async def _search_cosmosdb(self, query: str, top_k: int = 10) -> str:
        """Search in Cosmos DB knowledge base."""
        if not self.cosmosdb_search_client:
            return "Cosmos DB search not available"
        
        try:
            from src.tools.search_cosmosdb_knowledge_base import CosmosDBKnowledgeBaseSearchTool
            
            cosmosdb_tool = CosmosDBKnowledgeBaseSearchTool(
                self.cosmosdb_search_client
            )
            
            results = await cosmosdb_tool.search_and_format(query, top_k)
            return results
            
        except Exception as e:
            logger.error(f"Error searching Cosmos DB: {e}", exc_info=True)
            return f"Error searching Cosmos DB: {str(e)}"
    
    async def execute_async(
        self,
        query: str,
        search_type: str = "both",
        top_k: int = 5
    ) -> str:
        """
        Execute the search asynchronously.
        
        Args:
            query: Search query
            search_type: Where to search ('files', 'cosmosdb', or 'both')
            top_k: Number of results
            
        Returns:
            Formatted search results
        """
        logger.info(f"Executing Azure Search Tool: query='{query}', type='{search_type}', top_k={top_k}")
        
        results = []
        
        if search_type in ["files", "both"]:
            file_results = await self._search_files(query, top_k)
            if file_results and "Error" not in file_results:
                results.append(f"=== DOCUMENTS ===\n{file_results}")
        
        if search_type in ["cosmosdb", "both"]:
            cosmosdb_results = await self._search_cosmosdb(query, top_k)
            if cosmosdb_results and "Error" not in cosmosdb_results:
                results.append(f"=== ACCOUNTS (Companies/Properties) ===\n{cosmosdb_results}")
        
        if not results:
            return "No relevant information found in the knowledge base."
        
        combined_results = "\n\n".join(results)
        logger.info(f"Azure Search Tool completed: {len(combined_results)} characters returned")
        
        return combined_results
    
    def execute(self, query: str, search_type: str = "both", top_k: int = 5) -> str:
        """
        Synchronous wrapper for execute_async.
        This is the method that will be called by Azure AI Agent Framework.
        """
        try:
            # Try to get the current running loop
            try:
                loop = asyncio.get_running_loop()
                # If we're already in an async context, use nest_asyncio to allow nested loops
                import nest_asyncio
                nest_asyncio.apply()
                result = asyncio.run(self.execute_async(query, search_type, top_k))
                return result
            except RuntimeError:
                # No loop running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self.execute_async(query, search_type, top_k)
                    )
                    return result
                finally:
                    loop.close()
        except Exception as e:
            logger.error(f"Error executing Azure Search Tool: {e}", exc_info=True)
            return f"Error executing search: {str(e)}"


def create_azure_search_tool(
    file_search_client,
    cosmosdb_search_client,
    embeddings_generator
) -> AzureSearchTool:
    """
    Factory function to create AzureSearchTool instance.
    
    Args:
        file_search_client: SearchClient for file-based KB
        cosmosdb_search_client: SearchClient for Cosmos DB KB
        embeddings_generator: EmbeddingsGenerator instance
        
    Returns:
        Configured AzureSearchTool instance
    """
    return AzureSearchTool(
        file_search_client,
        cosmosdb_search_client,
        embeddings_generator
    )

