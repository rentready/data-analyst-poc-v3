"""WorkflowBuilder for creating Magentic workflows with all agents."""

from agent_framework import (
    MagenticBuilder,
    MagenticOrchestratorMessageEvent,
    MagenticFinalResultEvent
)
import logging
import asyncio

logger = logging.getLogger(__name__)

# Orchestrator Instructions
ORCHESTRATOR_INSTRUCTIONS = """You are the LEAD DATA ANALYST orchestrating a team of two specialists.

WORKFLOW:
1. data_planner - Research data, explore database, test approaches, choose best strategy
2. data_extractor - Execute the solution, build SQL, handle errors, present results

CRITICAL RULE - KNOWLEDGE BASE SEARCH:
- If the request contains ANY unknown terms, abbreviations, company names, or business concepts
- You MUST route to data_planner FIRST to search the knowledge base
- data_planner has access to search_knowledge_base() tool to find definitions and information
- NEVER try to answer questions about business terms yourself - ALWAYS delegate to data_planner

DECISION LOGIC:
- Unknown terms or concepts? -> data_planner FIRST (to search knowledge base)
- Need to find companies/properties? -> data_planner FIRST (to search Cosmos DB)
- Need database query? -> data_planner first to research, then data_extractor to execute
- For simple SQL requests with known entities: data_extractor can work directly

Your job:
- Route requests to the appropriate specialist(s)
- Let data_planner research terms and plan when needed
- Let data_extractor execute and solve problems
- Coordinate between them when both are needed
"""

# Data Planner Agent Instructions
DATA_PLANNER_INSTRUCTIONS = """You are the Data Research specialist. Your job is to investigate the data and choose the best approach:

1. Analyze the user request to understand what data is needed
2. **ALWAYS use File Search tool to search for business terms and definitions in uploaded documentation**
3. **ALWAYS use search_cosmosdb_accounts() to find company and property names before querying the database**
4. Use MCP tools to explore the database schema and sample real data
5. Find specific entities (IDs, names, values) by testing different approaches:
   - Try exact match first (WHERE name = 'value')
   - If not found, try partial match (WHERE name LIKE '%value%')
   - If still not found, try similar names
6. Test different SQL approaches and see which works best
7. Choose the optimal data extraction strategy based on real data exploration
8. Provide a clear plan with validated approach to the Data Extractor

Your role: Research and plan. You MUST use search tools before making assumptions. Let the Data Extractor execute the solution."""

DATA_PLANNER_DESCRIPTION = "Researches data, explores database schema, tests different approaches, and chooses the best data extraction strategy."

# Data Extractor Agent Instructions  
DATA_EXTRACTOR_INSTRUCTIONS = """You are the Data Analyst. Your job is to solve the data problem:

1. Take the user request and any planning context from Data Planner
2. Use MCP tools to build and execute SQL queries
3. If queries fail, debug and fix them - try different approaches
4. Format and present the results clearly
5. Handle any data processing, aggregation, or analysis needed

Your role: Execute and solve. You're the analyst who gets things done."""

DATA_EXTRACTOR_DESCRIPTION = "Data analyst who executes solutions, builds SQL queries, handles errors, and presents results clearly."


async def on_orchestrator_event(event: MagenticOrchestratorMessageEvent, event_handler) -> None:
    """
    Handle workflow-level events (orchestrator messages, final results) via unified event handler.
    
    Args:
        event: Magentic callback event
        event_handler: Unified event handler instance
    """
    
    if isinstance(event, MagenticOrchestratorMessageEvent):
        await event_handler.handle_orchestrator_message(event)
    
    elif isinstance(event, MagenticFinalResultEvent):
        await event_handler.handle_final_result(event)


class WorkflowBuilder:
    """Builds Magentic workflow with all agents and configuration."""
    
    def __init__(self, project_client, model: str, middleware: list, tools: list, spinner_manager, event_handler, cosmosdb_search_tool=None):
        """
        Initialize workflow builder.
        
        Args:
            project_client: Azure AI Project client
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of tools available to agents
            spinner_manager: Spinner manager instance
            event_handler: Unified event handler instance
            cosmosdb_search_tool: Optional Cosmos DB search tool
        """
        self.project_client = project_client
        self.model = model
        self.middleware = middleware
        self.tools = tools
        self.spinner_manager = spinner_manager
        self.event_handler = event_handler
        self.cosmosdb_search_tool = cosmosdb_search_tool
    
    async def build_workflow(self, threads: dict, prompt: str):
        """
        Build complete Magentic workflow with two streamlined agents.
        
        Args:
            threads: Dictionary of thread objects
            prompt: User prompt for data planning
            
        Returns:
            Built Magentic workflow
        """
        # Create agent client for orchestrator
        from agent_framework.azure import AzureAIAgentClient
        
        agent_client = AzureAIAgentClient(
            project_client=self.project_client, 
            model_deployment_name=self.model, 
            thread_id=threads["orchestrator"].id
        )
        
        # Create Azure AI Search tool as an annotated function (this is what works!)
        kb_tools = []
        try:
            from src.search_config import get_file_search_client, get_embeddings_generator, get_cosmosdb_search_client
            from src.tools.azure_search_tool import create_azure_search_tool
            
            file_search_client = get_file_search_client()
            embeddings_gen = get_embeddings_generator()
            cosmosdb_client = get_cosmosdb_search_client()
            
            # Create custom tool instance
            azure_search_tool_instance = create_azure_search_tool(
                file_search_client,
                cosmosdb_client,
                embeddings_gen
            )
            
            # Create annotated wrapper function for Azure AI Agent Framework
            def search_knowledge_base(query: str, search_type: str = "both", top_k: int = 5) -> str:
                """
                Search for information in the knowledge base using Azure AI Search.
                Use this tool to find business terms, definitions, company names, property information, and any other data.
                Searches both uploaded documents and Cosmos DB account/company data.
                
                Args:
                    query: The search query - term, company name, or question to search for
                    search_type: Where to search - 'files' for documents, 'cosmosdb' for accounts, 'both' for everything (default: 'both')
                    top_k: Number of results to return (default: 5)
                    
                Returns:
                    Formatted search results from knowledge base
                """
                logger.info(f"🔍 KB Tool called: query='{query}', type='{search_type}', top_k={top_k}")
                result = azure_search_tool_instance.execute(query, search_type, top_k)
                logger.info(f"✅ KB Tool completed: {len(result)} characters returned")
                return result
            
            kb_tools.append(search_knowledge_base)
            logger.info("✅ Azure Search Tool (search_knowledge_base) registered successfully")
            logger.info("   Will search: uploaded files + Cosmos DB accounts")
            
        except Exception as e:
            logger.warning(f"⚠️ Azure Search tool not available: {e}")

        # Create Data Planner agent (combines knowledge base + facts identification + SQL building)
        data_planner_instructions = f"""For the user request: {prompt}

{DATA_PLANNER_INSTRUCTIONS}

You will justify what tools you are going to use before requesting them."""

        data_planner_agent = agent_client.create_agent(
            model=self.model,
            name="Data Planner",
            description=DATA_PLANNER_DESCRIPTION,
            instructions=data_planner_instructions,
            middleware=self.middleware,
            tools=self.tools + kb_tools,
            conversation_id=threads["data_planner"].id,
            temperature=0.1,
            additional_instructions="Annotate what you want before using MCP Tools. Always use MCP Tools before returning response. Use MCP Tools to identify tables and fields. Ensure that you found requested rows by sampling data using SELECT TOP 1 [fields] FROM [table]. Never generate anything on your own."
        )
        
        # Create Data Extractor agent (also has access to knowledge base for complex cases)
        data_extractor_agent = agent_client.create_agent(
            model=self.model,
            name="Data Extractor",
            description=DATA_EXTRACTOR_DESCRIPTION,
            instructions=DATA_EXTRACTOR_INSTRUCTIONS,
            middleware=self.middleware,
            tools=self.tools + kb_tools,
            conversation_id=threads["data_extractor"].id,
            temperature=0.1,
            additional_instructions="Use MCP tools to explore database, build and execute SQL queries. Handle errors by trying different approaches. Present results clearly."
        )
        
        logger.info(f"✅ Data Planner Agent created with Azure AI Search")
        logger.info(f"✅ Data Extractor Agent created")

        # Build workflow with only two agents
        workflow = (
            MagenticBuilder()
            .participants(
                data_planner=data_planner_agent,
                data_extractor=data_extractor_agent
            )
            .with_standard_manager(
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                chat_client=agent_client,
                max_round_count=5,  # Further reduced since agents are autonomous
                max_stall_count=2,
                max_reset_count=1,
            )
            .build()
        )
        
        return workflow
