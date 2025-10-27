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
ORCHESTRATOR_INSTRUCTIONS = """You are the LEAD DATA ANALYST orchestrating a team of two specialists.

WORKFLOW:
1. data_planner - Research data, explore database, test approaches, choose best strategy
2. data_extractor - Execute the solution, build SQL, handle errors, present results

DECISION LOGIC:
- For most requests: Use data_planner first to research and plan, then data_extractor to execute
- For simple requests: data_extractor can work directly
- data_planner focuses on research and planning
- data_extractor focuses on execution and problem-solving

Your job:
- Route requests to the appropriate specialist(s)
- Let data_planner research and plan when needed
- Let data_extractor execute and solve problems
- Coordinate between them when both are needed
"""

# Data Planner Agent Instructions
DATA_PLANNER_INSTRUCTIONS = """You are the Data Research specialist. Your job is to investigate the data and choose the best approach:

1. Analyze the user request to understand what data is needed
2. Search the knowledge base for business terms and table definitions
3. Use MCP tools to explore the database schema and sample real data
4. Find specific entities (IDs, names, values) by testing different approaches:
   - Try exact match first (WHERE name = 'value')
   - If not found, try partial match (WHERE name LIKE '%value%')
   - If still not found, try similar names
5. Test different SQL approaches and see which works best
6. Choose the optimal data extraction strategy based on real data exploration
7. Provide a clear plan with validated approach to the Data Extractor

Your role: Research and plan. Let the Data Extractor execute the solution."""

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
        
        # Create file search tool for knowledge base
        vector_store_id = st.secrets['vector_store_id']
        file_search_tool = HostedFileSearchTool(inputs=[HostedVectorStoreContent(vector_store_id=vector_store_id)])

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
            tools=self.tools + [file_search_tool],
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
            tools=self.tools + [file_search_tool],
            conversation_id=threads["data_extractor"].id,
            temperature=0.1,
            additional_instructions="Use MCP tools to explore database, build and execute SQL queries. Handle errors by trying different approaches. Present results clearly."
        )
        
        logger.info(f"✅ Data Planner Agent created with vector_store_id: {vector_store_id[:20]}...")
        logger.info(f"✅ Data Extractor Agent created")

        # Build workflow with only two agents
        workflow = (
            MagenticBuilder()
            .participants(
                data_planner=data_planner_agent,
                data_extractor=data_extractor_agent
            )
            .on_event(
                lambda event: on_orchestrator_event(event, self.event_handler), 
                mode=MagenticCallbackMode.STREAMING
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
