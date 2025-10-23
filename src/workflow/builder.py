"""WorkflowBuilder for creating Magentic workflows with all agents."""

from agent_framework import (
    MagenticBuilder,
    MagenticCallbackMode,
    AgentRunContext
)
from src.agent_instructions import (
    ORCHESTRATOR_INSTRUCTIONS,
    KNOWLEDGE_BASE_AGENT_INSTRUCTIONS,
    KNOWLEDGE_BASE_AGENT_DESCRIPTION
)
from src.config import get_vector_store_id
from src.workflow.orchestrator_handler import on_orchestrator_event
import streamlit as st
import logging

logger = logging.getLogger(__name__)

class WorkflowBuilder:
    """Builds Magentic workflow with all agents and configuration."""
    
    def __init__(self, agent_client, project_client, model: str, middleware: list, tools: list, spinner_manager):
        """
        Initialize workflow builder.
        
        Args:
            agent_client: Azure AI agent client
            project_client: Azure AI Project client (for file_search tools)
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of tools available to agents
            spinner_manager: Spinner manager instance
        """
        self.agent_client = agent_client
        self.project_client = project_client
        self.model = model
        self.middleware = middleware
        self.tools = tools
        self.spinner_manager = spinner_manager
    
    async def build_workflow(self, threads: dict, prompt: str):
        """
        Build complete Magentic workflow with all agents.
        
        Args:
            threads: Dictionary of thread objects
            prompt: User prompt for facts identifier
            
        Returns:
            Built Magentic workflow
        """
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

        facts_identifier_agent = self.agent_client.create_agent(
            model=self.model,
            name="Facts Identifier",
            description="Use MCP Tools to find every entity (IDs, names, values) for the user request which is not covered by the glossary. Search for entities by name using progressive matching: 1) Exact match first, 2) Then partial/LIKE match, 3) Then similar names, 4) Take larger datasets. Execute SELECT TOP XXX to validate found entities.",
            instructions=facts_instructions,
            middleware=self.middleware,
            tools=self.tools,
            conversation_id=threads["facts_identifier"].id,
            temperature=0.1,
            additional_instructions="Annotate what you want before using MCP Tools. Always use MCP Tools before returning response. Use MCP Tools to identify tables and fields. Ensure that you found requested rows by sampling data using SELECT TOP 1 [fields] FROM [table]. Never generate anything on your own."
        )
        
        # Create SQL Builder agent
        sql_builder_agent = self.agent_client.create_agent(
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
        data_extractor_agent = self.agent_client.create_agent(
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
        glossary_agent = self.agent_client.create_agent(
            model=self.model,
            name="Glossary",
            description="Business terminology and definitions reference",
            instructions=st.secrets["glossary"]["instructions"],
            middleware=self.middleware,
            tools=self.tools,
            conversation_id=threads["glossary"].id,
            temperature=0.1,
            additional_instructions="Answer concisely and clearly. Focus on practical business context."
        )

        # Create Knowledge Base Agent with File Search
        vector_store_id = get_vector_store_id()
        knowledge_base_agent = None
        if vector_store_id:
            knowledge_base_agent = self.agent_client.create_agent(
                model=self.model,
                name="Knowledge Base Agent",
                description=KNOWLEDGE_BASE_AGENT_DESCRIPTION,
                instructions=KNOWLEDGE_BASE_AGENT_INSTRUCTIONS,
                tools=[{"type": "file_search"}],
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
                conversation_id=threads["knowledge_base"].id,
                temperature=0.0,
            )
            logger.info(f"✅ Knowledge Base Agent created with vector_store_id: {vector_store_id[:20]}...")
        else:
            logger.warning("⚠️ Knowledge Base Agent not created - vector_store_id not configured")

        logger.info(f"Created agent {sql_builder_agent}")

        # Store threads in session state for persistence
        st.session_state.facts_identifier_thread = threads["facts_identifier"]
        st.session_state.sql_builder_thread = threads["sql_builder"]
        st.session_state.data_extractor_thread = threads["data_extractor"]
        st.session_state.glossary_thread = threads["glossary"]
        st.session_state.knowledge_base_thread = threads["knowledge_base"]
        st.session_state.orchestrator_thread = threads["orchestrator"]

        # Build participants dict
        participants = {
            "glossary": glossary_agent,
            "facts_identifier": facts_identifier_agent,
            "sql_builder": sql_builder_agent,
            "data_extractor": data_extractor_agent
        }
        
        # Add knowledge_base agent if available
        if knowledge_base_agent:
            participants["knowledge_base"] = knowledge_base_agent
        
        # Build workflow
        workflow = (
            MagenticBuilder()
            .participants(**participants)
            .on_event(
                lambda event: on_orchestrator_event(event, self.spinner_manager), 
                mode=MagenticCallbackMode.STREAMING
            )
            .with_standard_manager(
                chat_client=self.agent_client,
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                max_round_count=15,
                max_stall_count=4,
                max_reset_count=2,
            )
            .build()
        )
        
        return workflow
