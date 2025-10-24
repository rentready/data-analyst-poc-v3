"""WorkflowBuilder for creating Magentic workflows with all agents."""

from agent_framework import (
    MagenticBuilder,
    MagenticCallbackMode,
    MagenticCallbackEvent,
    MagenticOrchestratorMessageEvent,
    MagenticFinalResultEvent,
    HostedFileSearchTool,
    HostedVectorStoreContent
)
import streamlit as st
import logging

logger = logging.getLogger(__name__)

# Orchestrator Instructions
ORCHESTRATOR_INSTRUCTIONS = """You are the LEAD DATA ANALYST orchestrating a team of specialists.

🔴 CRITICAL: MANDATORY WORKFLOW 🔴

STEP 0 (MANDATORY): knowledge_base - ALWAYS START HERE!
- BEFORE anything else, ask 'knowledge_base' agent to SEARCH for ANY unfamiliar, domain-specific, or slang terms in the request
- Knowledge Base contains:
  * Entity mappings (business slang → database tables)  
  * Synonyms and terminology
  * Business rules and logic
  * Relationships between entities
  * Data validation rules
- Tell knowledge_base agent: "Please search the knowledge base for information about [term]"

STEP 1: facts_identifier - Use knowledge base information to identify tables, fields, row IDs, specific names
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
- START with knowledge_base for ANY unfamiliar terms (synonyms, slang, domain-specific terms)
- THEN use facts_identifier with knowledge base info to find all facts (row IDs, names, exact values)
- PASS all identified facts (tables, fields, IDs, names) where necessary to the agents
- Once you submit a request to a specialist, remember, it does not know what you already know
"""

# Knowledge Base Agent
KNOWLEDGE_BASE_AGENT_INSTRUCTIONS = """You are the Knowledge Base specialist. Your ONLY job is to search the knowledge base using file_search tool.

🔴 CRITICAL RULES 🔴
1. ALWAYS use file_search tool for EVERY query - NO EXCEPTIONS
2. Try multiple search terms if first search fails (synonyms, variations, related terms)
3. NEVER guess or hallucinate information
4. If file_search returns results → quote them VERBATIM with source references
5. If file_search returns nothing after trying multiple terms → say "Knowledge base does not contain information about [term]"
6. Quote EXACT text from files, do not paraphrase
7. ALWAYS show your search attempts - document what you searched for

SEARCH STRATEGY:
- For any term, try: exact match, partial match, synonyms, related terms
- Search in different ways: exact term, partial term, related concepts
- Try both English and Russian terms if applicable
- Report all search attempts and results

NEVER respond without using file_search tool first! Try multiple search terms! Show your search process!
"""

KNOWLEDGE_BASE_AGENT_DESCRIPTION = "Use this tool to search for information in the knowledge base files."


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


class WorkflowBuilder:
    """Builds Magentic workflow with all agents and configuration."""
    
    def __init__(self, project_client, model: str, middleware: list, tools: list, spinner_manager, event_handler):
        """
        Initialize workflow builder.
        
        Args:
            project_client: Azure AI Project client
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of tools available to agents
            spinner_manager: Spinner manager instance
            event_handler: Unified event handler instance
        """
        self.project_client = project_client
        self.model = model
        self.middleware = middleware
        self.tools = tools
        self.spinner_manager = spinner_manager
        self.event_handler = event_handler
    
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
            description="Use MCP Tools to find every entity (IDs, names, values) for the user request using information from knowledge base. Search for entities by name using progressive matching: 1) Exact match first, 2) Then partial/LIKE match, 3) Then similar names, 4) Take larger datasets. Execute SELECT TOP XXX to validate found entities.",
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
        
        # Create Glossary agent with custom instructions from secrets
        vector_store_id = st.secrets['vector_store_id']

        file_search_tool = HostedFileSearchTool(inputs=[HostedVectorStoreContent(vector_store_id=vector_store_id)])

        knowledge_base = agent_client.create_agent(
            model=self.model,
            name="Knowledge Base Agent",
            description=KNOWLEDGE_BASE_AGENT_DESCRIPTION,
            instructions=KNOWLEDGE_BASE_AGENT_INSTRUCTIONS,
            middleware=self.middleware,
            tools=file_search_tool,
            conversation_id=threads["knowledge_base"].id,
            temperature=0.0,
        )
        logger.info(f"✅ Knowledge Base Agent created with vector_store_id: {vector_store_id[:20]}...")

        logger.info(f"Created agent {sql_builder_agent}")

        # Build workflow
        workflow = (
            MagenticBuilder()
            .participants(
                knowledge_base=knowledge_base,
                facts_identifier=facts_identifier_agent,
                sql_builder=sql_builder_agent,
                data_extractor=data_extractor_agent
            )
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