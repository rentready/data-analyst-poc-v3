"""WorkflowBuilder for creating Magentic workflows with Azure AI Search Knowledge Base."""

from agent_framework import (
    MagenticBuilder,
    MagenticCallbackMode,
    MagenticCallbackEvent,
    MagenticOrchestratorMessageEvent,
    MagenticFinalResultEvent,
)
import logging

from src.tools.search_knowledge_base import KnowledgeBaseSearchTool
from src.tools.search_cosmosdb_knowledge_base import CosmosDBKnowledgeBaseSearchTool

logger = logging.getLogger(__name__)

# Orchestrator Instructions
ORCHESTRATOR_INSTRUCTIONS = """You are the LEAD DATA ANALYST orchestrating a team of specialists.

🔴 CRITICAL: MANDATORY WORKFLOW 🔴

STEP 0A (MANDATORY): cosmosdb_kb - Check Cosmos DB Knowledge Base FIRST for company/property names!
- ALWAYS start here if user mentions ANY company names, property names, or organization names
- Cosmos DB contains: Company names, Property names, Account information, Organizational units
- Example: If user mentions "Vest", "Residences", any property/company name → ASK cosmosdb_kb FIRST!
- Tell cosmosdb_kb: "Search for [company/property name]"

STEP 0B (MANDATORY): knowledge_base - Then check general knowledge base for terms and definitions!
- After cosmosdb_kb, ask 'knowledge_base' to SEARCH for ANY unfamiliar, domain-specific, or slang terms
- Knowledge Base contains:
  * Entity mappings (business slang → database tables)  
  * Synonyms and terminology (e.g., "прошник" → bookableresource)
  * Business rules and logic
  * Relationships between entities
  * Data validation rules
- Example: If user mentions "прошник", "DSAT", "turn", "job profile" → ASK knowledge_base to SEARCH!
- Tell knowledge_base: "Search for information about [term]"

STEP 1: facts_identifier - Use BOTH knowledge bases to identify tables, fields, row IDs, specific names
STEP 2: sql_builder <> data_extractor

HANDOFF FORMAT (enforce this for all agents):
** SQL Query **
```sql
{sql_query}
```
** Feedback **
```
{feedback}
```

Your job:
- START with cosmosdb_kb for ANY company/property names
- THEN use knowledge_base for ANY unfamiliar terms (synonyms, slang, domain-specific terms)
- THEN use facts_identifier with knowledge base info to find all facts (row IDs, names, exact values)
- PASS all identified facts (tables, fields, IDs, names) where necessary to the agents
- Once you submit a request to a specialist, remember, it does not know what you already know
"""

# Knowledge Base Agent Instructions
KNOWLEDGE_BASE_AGENT_INSTRUCTIONS = """You are the Knowledge Base specialist. Your ONLY job is to search the knowledge base using the search_knowledge_base tool.

🔴 CRITICAL RULES 🔴
1. ALWAYS use search_knowledge_base tool for EVERY query - NO EXCEPTIONS
2. Try multiple search terms if first search fails (synonyms, variations, related terms)
3. NEVER guess or hallucinate information
4. If search returns results → quote them VERBATIM with source references
5. If search returns nothing after trying multiple terms → say "Knowledge base does not contain information about [term]"
6. Quote EXACT text from search results, do not paraphrase
7. ALWAYS show your search attempts - document what you searched for

SEARCH STRATEGY:
- For "прошник" also try: "pro", "bookable resource", "bookableresource", "specialist", "professional", "resource"
- For any term, try: exact match, synonyms, related terms
- Try both English and Russian terms if applicable
- Report all search attempts and results

TOOL USAGE:
- Call search_knowledge_base(query="term to search", top_k=5)
- Analyze results and extract relevant information
- Try different queries if first attempt doesn't find anything
- Cite sources with filename and chunk information

NEVER respond without using search_knowledge_base tool first! Try multiple search terms! Show your search process!
"""

KNOWLEDGE_BASE_AGENT_DESCRIPTION = "Use this tool to search for information in the knowledge base. Searches indexed documents using hybrid search (keyword + semantic)."

# Cosmos DB Knowledge Base Agent Instructions
COSMOSDB_KB_AGENT_INSTRUCTIONS = """You are the Cosmos DB Knowledge Base specialist. Your ONLY job is to search Cosmos DB for company and property information.

🔴 CRITICAL RULES 🔴
1. ALWAYS use search_cosmosdb_accounts tool for EVERY query - NO EXCEPTIONS
2. Try multiple search terms if first search fails (variations, partial names)
3. NEVER guess or hallucinate information
4. If search returns results → quote them VERBATIM with all details
5. If search returns nothing after trying multiple terms → say "Cosmos DB does not contain information about [name]"
6. Quote EXACT data from search results, do not paraphrase
7. ALWAYS show your search attempts - document what you searched for

SEARCH STRATEGY:
- For "Vest" also try: "Vest Residential", "vest", "VEST"
- For any name, try: exact match, partial match, lowercase
- Try both full names and short names if applicable
- Report all search attempts and results

TOOL USAGE:
- Call search_cosmosdb_accounts(query="name to search", top_k=10)
- Analyze results and extract relevant information (account ID, name, location, etc.)
- Try different queries if first attempt doesn't find anything
- Return all found accounts with full details

NEVER respond without using search_cosmosdb_accounts tool first! Try multiple search terms! Show your search process!
"""

COSMOSDB_KB_AGENT_DESCRIPTION = "Use this tool to search for company and property names in Cosmos DB. Searches accounts/properties using hybrid search (keyword + semantic)."


async def on_orchestrator_event(event: MagenticCallbackEvent, event_handler) -> None:
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


class WorkflowBuilderWithSearch:
    """Builds Magentic workflow with all agents and Azure AI Search Knowledge Base."""
    
    def __init__(
        self, 
        project_client, 
        model: str, 
        middleware: list, 
        tools: list, 
        spinner_manager, 
        event_handler,
        kb_search_tool: KnowledgeBaseSearchTool,
        cosmosdb_kb_search_tool: CosmosDBKnowledgeBaseSearchTool = None
    ):
        """
        Initialize workflow builder.
        
        Args:
            project_client: Azure AI Project client
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of MCP tools available to agents
            spinner_manager: Spinner manager instance
            event_handler: Unified event handler instance
            kb_search_tool: Knowledge Base search tool instance
            cosmosdb_kb_search_tool: Cosmos DB Knowledge Base search tool instance (optional)
        """
        self.project_client = project_client
        self.model = model
        self.middleware = middleware
        self.tools = tools
        self.spinner_manager = spinner_manager
        self.event_handler = event_handler
        self.kb_search_tool = kb_search_tool
        self.cosmosdb_kb_search_tool = cosmosdb_kb_search_tool
    
    async def build_workflow(self, threads: dict, prompt: str):
        """
        Build complete Magentic workflow with all agents.
        
        Args:
            threads: Dictionary of thread objects
            prompt: User prompt for facts identifier
            
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
        
        # Create Facts Identifier agent
        facts_instructions = """for the user request: {prompt}

Identify tables and fields by using MCP Tools. When searching for specific entities (property names, market names, etc.), use progressive matching strategy:
1. Try exact match first (WHERE name = 'value')
2. If not found, try partial match (WHERE name LIKE '%value%')
3. If still not found, try similar names

Refine fields and tables by sampling data using SELECT TOP 1 [fields] FROM [table] and make it return requested values before finishing your response.

You will justify what tools you are going to use before requesting them."""

        if prompt and "{prompt}" in facts_instructions:
            facts_instructions = facts_instructions.format(prompt=prompt)

        facts_identifier_agent = agent_client.create_agent(
            model=self.model,
            name="Facts Identifier",
            description="Use MCP Tools to find every entity (IDs, names, values) for the user request using information from knowledge base. Search for entities by name using progressive matching: 1) Exact match first, 2) Then partial/LIKE match, 3) Then similar names. Execute SELECT TOP XXX to validate found entities.",
            instructions=facts_instructions,
            middleware=self.middleware,
            tools=self.tools,
            conversation_id=threads["facts_identifier"].id,
            temperature=0.1,
            additional_instructions="Annotate what you want before using MCP Tools. Always use MCP Tools before returning response. Use MCP Tools to identify tables and fields. Ensure that you found requested rows by sampling data using SELECT TOP 1 [fields] FROM [table]. Never generate anything on your own."
        )
        
        # Create SQL Builder agent
        sql_builder_agent = agent_client.create_agent(
            model=self.model,
            name="SQL Builder",
            description="Use this tool when all data requirements and facts are extracted, all referenced entities are identified, fields and tables are known. Use this tool to pass known table names, fields and filters and ask to construct an SQL query to address user's request and ensure it works as expected by executing MCP Tools with SELECT ....",
            instructions="""You construct SQL queries per user request. You always use MCP Tools to validate your query and never generate anything on your own.
You will justify what tools you are going to use before requesting them.
OUTPUT FORMAT:
** SQL Query **
```sql
{sql_query}
```
** Data Sample **
```
{real_data_sample}
```
** Feedback **
```
{your assumptions, validation notes, or questions}
```
""",
            middleware=self.middleware,
            tools=self.tools,
            conversation_id=threads["sql_builder"].id,
            temperature=0.1,
            additional_instructions="Annotate what you want before using MCP Tools. Use MCP tools to validate tables and fields by executing SELECT TOP 1 before building the final query."
        )
        sql_builder_agent.user = "sql_builder"
        
        # Create Data Extractor agent
        data_extractor_agent = agent_client.create_agent(
            model=self.model,
            name="Data Extractor",
            description="Use this tool when SQL query is validated and succeeded to extract data.",
            instructions="""Execute SQL queries using MCP tools and return formatted results.

OUTPUT FORMAT:
Present data in tables or structured format.""",
            middleware=self.middleware,
            tools=self.tools,
            conversation_id=threads["data_extractor"].id,
            temperature=0.1,
            additional_instructions="Use MCP tools to execute the SQL query. Present results clearly."
        )
        
        # Create Cosmos DB Knowledge Base Agent (if available)
        # This agent searches for company/property names in Cosmos DB
        cosmosdb_kb_agent = None
        if self.cosmosdb_kb_search_tool:
            async def search_cosmosdb_accounts(query: str, top_k: int = 10) -> str:
                """
                Search Cosmos DB for company and property account information using semantic search.
                
                Args:
                    query: Company or property name to search for
                    top_k: Number of results to return (default: 10)
                    
                Returns:
                    Formatted search results with account details (name, ID, location, etc.)
                """
                try:
                    logger.info(f'🔍 Cosmos DB KB Agent searching for: "{query}" (top_k={top_k})')
                    results = await self.cosmosdb_kb_search_tool.search_and_format(
                        query=query,
                        top_k=top_k,
                        search_type='semantic'
                    )
                    logger.info(f'✅ Cosmos DB KB Agent found {len(results)} chars of results')
                    return results
                except Exception as e:
                    logger.error(f'❌ Cosmos DB KB search error: {e}', exc_info=True)
                    return f'Error searching Cosmos DB knowledge base: {str(e)}'
            
            cosmosdb_kb_agent = agent_client.create_agent(
                model=self.model,
                name="Cosmos DB Knowledge Base Agent",
                description=COSMOSDB_KB_AGENT_DESCRIPTION,
                instructions=COSMOSDB_KB_AGENT_INSTRUCTIONS,
                middleware=self.middleware,
                tools=[search_cosmosdb_accounts],
                conversation_id=threads.get("cosmosdb_kb", threads["knowledge_base"]).id,
                temperature=0.0,
            )
            
            logger.info('✅ Cosmos DB Knowledge Base Agent created with Azure AI Search')
        
        # Create Knowledge Base Agent with custom search tool
        # This agent uses our KnowledgeBaseSearchTool instead of HostedFileSearchTool
        
        # Wrap search tool as callable function for agent
        # Azure AI Agents SDK will automatically create tool definition from function signature and docstring
        async def search_knowledge_base(query: str, top_k: int = 5) -> str:
            """
            Search the knowledge base for relevant information using hybrid search (keyword + semantic).
            
            Args:
                query: The search query or question to find information about
                top_k: Number of results to return (default: 5)
                
            Returns:
                Formatted search results with relevant excerpts and sources
            """
            try:
                logger.info(f'🔍 KB Agent searching for: "{query}" (top_k={top_k})')
                results = await self.kb_search_tool.search_and_format(
                    query=query,
                    top_k=top_k,
                    search_type='hybrid'
                )
                logger.info(f'✅ KB Agent found {len(results)} chars of results')
                return results
            except Exception as e:
                logger.error(f'❌ KB search error: {e}')
                return f'Error searching knowledge base: {str(e)}'
        
        # Create KB agent with search function
        # The function will be automatically converted to an OpenAI function calling tool
        knowledge_base_agent = agent_client.create_agent(
            model=self.model,
            name="Knowledge Base Agent",
            description=KNOWLEDGE_BASE_AGENT_DESCRIPTION,
            instructions=KNOWLEDGE_BASE_AGENT_INSTRUCTIONS,
            middleware=self.middleware,
            tools=[search_knowledge_base],  # Function will be auto-converted to tool
            conversation_id=threads["knowledge_base"].id,
            temperature=0.0,
        )
        
        logger.info('✅ Knowledge Base Agent created with Azure AI Search')

        logger.info(f'Created agent {sql_builder_agent}')

        # Build workflow with or without Cosmos DB agent
        builder = MagenticBuilder()
        
        # Add participants (conditionally include cosmosdb_kb if available)
        participants = {
            'knowledge_base': knowledge_base_agent,
            'facts_identifier': facts_identifier_agent,
            'sql_builder': sql_builder_agent,
            'data_extractor': data_extractor_agent
        }
        
        if cosmosdb_kb_agent:
            participants['cosmosdb_kb'] = cosmosdb_kb_agent
            logger.info('✅ Cosmos DB KB agent added to workflow')
        
        workflow = (
            builder
            .participants(**participants)
            .on_event(
                lambda event: on_orchestrator_event(event, self.event_handler), 
                mode=MagenticCallbackMode.STREAMING
            )
            .with_standard_manager(
                chat_client=agent_client,
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                max_round_count=15,
                max_stall_count=4,
                max_reset_count=2,
            )
            .build()
        )
        
        return workflow

