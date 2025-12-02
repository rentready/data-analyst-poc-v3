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
    
    def __init__(self, file_search_client, management_companies_client, properties_client, embeddings_generator):
        """
        Initialize the Azure Search Tool.
        
        Args:
            file_search_client: SearchClient for file-based knowledge base
            management_companies_client: SearchClient for management companies index
            properties_client: SearchClient for properties index
            embeddings_generator: EmbeddingsGenerator instance
        """
        self.file_search_client = file_search_client
        self.management_companies_client = management_companies_client
        self.properties_client = properties_client
        self.embeddings_generator = embeddings_generator
        
        logger.info("AzureSearchTool initialized with 3 indexes")
    
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
                    "Use this to find business terms, definitions, management companies, and properties. "
                    "Searches uploaded documents, management companies, and properties."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query - term, company name, property name, or question"
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["files", "management_companies", "properties", "all"],
                            "description": "Where to search: 'files' for documents, 'management_companies' for companies, 'properties' for properties, 'all' for everything",
                            "default": "all"
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
            logger.info(f"🔍 _search_files called: query='{query}', top_k={top_k}")
            logger.info(f"   file_search_client: {self.file_search_client}")
            
            # Use KEYWORD search ONLY (no embeddings needed)
            results = await self.file_search_client.search(
                query=query,
                search_type="keyword",  # KEYWORD ONLY!
                top_k=top_k
            )
            
            logger.info(f"   Search completed, got {len(results) if results else 0} results")
            
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
    
    async def _search_management_companies(self, query: str, top_k: int = 5) -> str:
        """Search in management companies index using keyword search."""
        if not self.management_companies_client:
            return "Management companies search not available"
        
        try:
            logger.info(f"Searching management companies: '{query}'")
            
            results = await self.management_companies_client.search(
                query=query,
                search_type="keyword",
                top_k=top_k
            )
            
            if not results:
                return "No management companies found."
            
            formatted_results = []
            for i, result in enumerate(results, 1):
                name = result.get('name', 'Unknown')
                city = result.get('address1_city', '')
                state = result.get('address1_stateorprovince', '')
                account_number = result.get('accountnumber', '')
                
                location = f"{city}, {state}" if city and state else city or state or "N/A"
                formatted_results.append(
                    f"Result {i}: {name} (#{account_number})\n"
                    f"Type: Management Company\n"
                    f"Location: {location}\n"
                )
            
            logger.info(f"Found {len(results)} management companies")
            return "\n".join(formatted_results)
            
        except Exception as e:
            logger.error(f"Error searching management companies: {e}", exc_info=True)
            return f"Error searching management companies: {str(e)}"
    
    async def _search_properties(self, query: str, top_k: int = 10) -> str:
        """Search in properties index using keyword search."""
        if not self.properties_client:
            return "Properties search not available"
        
        try:
            logger.info(f"Searching properties: '{query}'")
            
            results = await self.properties_client.search(
                query=query,
                search_type="keyword",
                top_k=top_k
            )
            
            if not results:
                return "No properties found."
            
            formatted_results = []
            for i, result in enumerate(results, 1):
                name = result.get('name', 'Unknown')
                city = result.get('address1_city', '')
                state = result.get('address1_stateorprovince', '')
                account_number = result.get('accountnumber', '')
                parent_account = result.get('parentaccountid', '')
                
                location = f"{city}, {state}" if city and state else city or state or "N/A"
                formatted_results.append(
                    f"Result {i}: {name} (#{account_number})\n"
                    f"Type: Property\n"
                    f"Location: {location}\n"
                )
                
                # Optionally include parent account ID for reference
                if parent_account:
                    formatted_results[-1] += f"Parent Account ID: {parent_account}\n"
            
            logger.info(f"Found {len(results)} properties")
            return "\n".join(formatted_results)
            
        except Exception as e:
            logger.error(f"Error searching properties: {e}", exc_info=True)
            return f"Error searching properties: {str(e)}"
    
    async def execute_async(
        self,
        query: str,
        search_type: str = "all",
        top_k: int = 5
    ) -> str:
        """
        Execute the search asynchronously.
        
        Args:
            query: Search query
            search_type: Where to search ('files', 'management_companies', 'properties', or 'all')
            top_k: Number of results
            
        Returns:
            Formatted search results
        """
        logger.info(f"Executing Azure Search Tool: query='{query}', type='{search_type}', top_k={top_k}")
        
        results = []
        
        if search_type in ["files", "all"]:
            file_results = await self._search_files(query, top_k)
            if file_results and "Error" not in file_results and "No results" not in file_results:
                results.append(f"=== DOCUMENTS ===\n{file_results}")
        
        if search_type in ["management_companies", "all"]:
            mgmt_results = await self._search_management_companies(query, top_k)
            if mgmt_results and "Error" not in mgmt_results and "No management" not in mgmt_results:
                results.append(f"=== MANAGEMENT COMPANIES ===\n{mgmt_results}")
        
        if search_type in ["properties", "all"]:
            prop_results = await self._search_properties(query, top_k * 2)  # More results for properties
            if prop_results and "Error" not in prop_results and "No properties" not in prop_results:
                results.append(f"=== PROPERTIES ===\n{prop_results}")
        
        if not results:
            return "No relevant information found in the knowledge base."
        
        combined_results = "\n\n".join(results)
        logger.info(f"Azure Search Tool completed: {len(combined_results)} characters returned")
        
        return combined_results
    
    def execute(self, query: str, search_type: str = "all", top_k: int = 5) -> str:
        """
        Synchronous wrapper for execute_async.
        This is the method that will be called by Azure AI Agent Framework.
        """
        logger.info(f"🚀 AzureSearchTool.execute() called:")
        logger.info(f"   query='{query}'")
        logger.info(f"   search_type='{search_type}'")
        logger.info(f"   top_k={top_k}")
        
        try:
            # Try to get the current running loop
            try:
                loop = asyncio.get_running_loop()
                logger.info(f"   Found running event loop: {loop}")
                # If we're already in an async context, use nest_asyncio to allow nested loops
                import nest_asyncio
                nest_asyncio.apply()
                logger.info("   Applied nest_asyncio")
                result = asyncio.run(self.execute_async(query, search_type, top_k))
                logger.info(f"   Result length: {len(result)} chars")
                return result
            except RuntimeError as e:
                logger.info(f"   No running loop (RuntimeError: {e}), creating new one")
                # No loop running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self.execute_async(query, search_type, top_k)
                    )
                    logger.info(f"   Result length: {len(result)} chars")
                    return result
                finally:
                    loop.close()
        except Exception as e:
            logger.error(f"❌ Error executing Azure Search Tool: {e}", exc_info=True)
            return f"Error executing search: {str(e)}"


def create_azure_search_tool(
    file_search_client,
    management_companies_client,
    properties_client,
    embeddings_generator
) -> AzureSearchTool:
    """
    Factory function to create AzureSearchTool instance.
    
    Args:
        file_search_client: SearchClient for file-based KB
        management_companies_client: SearchClient for management companies
        properties_client: SearchClient for properties
        embeddings_generator: EmbeddingsGenerator instance
        
    Returns:
        Configured AzureSearchTool instance
    """
    return AzureSearchTool(
        file_search_client,
        management_companies_client,
        properties_client,
        embeddings_generator
    )

