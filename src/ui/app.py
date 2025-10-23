"""Main Streamlit application class."""

import streamlit as st
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.config import get_config, get_mcp_config, setup_environment_variables, get_auth_config, get_openai_config, get_vector_store_id
from src.constants import PROJ_ENDPOINT_KEY, MCP_SERVER_URL_KEY, MODEL_DEPLOYMENT_NAME_KEY, OPENAI_API_KEY, OPENAI_MODEL_KEY, OPENAI_BASE_URL_KEY, MCP_ALLOWED_TOOLS_KEY
from src.mcp_client import get_mcp_token_sync, display_mcp_status
from src.auth import initialize_msal_auth, get_user_initials
from src.agents.thread_manager import ThreadManager
from src.workflow.builder import WorkflowBuilder
from src.middleware.streaming_state import StreamingStateManager
from src.middleware.spinner_manager import SpinnerManager
from src.ui.message_history import render_chat_history
from src.knowledge_base_ui import render_knowledge_base_sidebar
from src.events import create_streamlit_event_handler

from agent_framework import HostedMCPTool
from agent_framework.openai import OpenAIChatClient, OpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework.azure import AzureAIAgentClient
from azure.ai.projects.aio import AIProjectClient

from agent_framework.observability import setup_observability, get_tracer
from opentelemetry.trace import SpanKind
from opentelemetry.trace.span import format_trace_id

logger = logging.getLogger(__name__)

class DataAnalystApp:
    """Main application class for Data Analyst Chat."""
    
    def __init__(self):
        """Initialize the application."""
        self.config = None
        self.openai_config = None
        self.mcp_config = None
        self.streaming_state = None
        self.spinner_manager = None
    
    def initialize(self) -> None:
        """Initialize application: config, auth, MCP, session state."""
        # Get configuration
        self.config = get_config()
        if not self.config:
            st.error("❌ Please configure your Azure AI Foundry settings in Streamlit secrets.")
            st.stop()
        
        # Setup environment
        setup_environment_variables()

        # Setup observability with connection string from secrets
        connection_string = st.secrets.get("observability", {}).get("applicationinsights_connection_string")
        if connection_string:
            setup_observability(
                applicationinsights_connection_string=connection_string,
                enable_sensitive_data=True
            )
        
        # Get authentication configuration
        client_id, tenant_id, _ = get_auth_config()
        if not client_id or not tenant_id:
            st.stop()
        
        # Initialize MSAL authentication in sidebar
        with st.sidebar:
            token_credential = initialize_msal_auth(client_id, tenant_id)
        
        # Check if user is authenticated
        if not token_credential:
            st.error("❌ Please sign in to use the chatbot.")
            st.stop()
        
        # Store auth data in session state for later use
        if "auth_data" not in st.session_state:
            st.session_state.auth_data = token_credential
        
        # Get OpenAI configuration
        self.openai_config = get_openai_config()
        if not self.openai_config:
            st.error("❌ Please configure OpenAI settings in Streamlit secrets.")
            st.stop()
        
        # Get MCP configuration
        self.mcp_config = get_mcp_config()
        
        # Initialize state managers
        self.streaming_state = StreamingStateManager()
        self.spinner_manager = SpinnerManager()
    
    def render_ui(self) -> None:
        """Render the main UI components."""
        st.title("🤖 Data Analyst Chat")
        
        # Initialize session state
        if "messages" not in st.session_state:
            st.session_state.messages = []
        
        # Render Knowledge Base sidebar
        with st.sidebar:
            vector_store_id = get_vector_store_id()
            render_knowledge_base_sidebar(vector_store_id, self.config)
        
        # Render chat history
        render_chat_history()
        
        # Initialize current chat containers
        st.session_state.current_chat = st.empty()
        st.session_state.current_role = st.empty()
    
    def get_time(self) -> str:
        """Get the current UTC time."""
        current_time = datetime.now(timezone.utc)
        return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
    
    async def run_workflow(self, prompt: str) -> None:
        """Run the complete workflow for a user prompt."""
        self.spinner_manager.start("Planning your request...")
        
        # Prepare common client parameters
        api_key = self.openai_config[OPENAI_API_KEY]
        model_name = self.openai_config[OPENAI_MODEL_KEY]
        base_url = self.openai_config.get(OPENAI_BASE_URL_KEY)

        mcp_token = get_mcp_token_sync(self.mcp_config)

        # With approval mode and allowed tools
        mcp_tool_with_approval = HostedMCPTool(
            name="rentready_mcp",
            description="Rent Ready MCP tool",
            url=self.mcp_config[MCP_SERVER_URL_KEY],
            approval_mode="never_require",
            allowed_tools=self.mcp_config.get(MCP_ALLOWED_TOOLS_KEY, []),
            headers={"Authorization": f"Bearer {mcp_token}"},
        )

        # Prepare common client parameters
        client_params = {"model_id": model_name, "api_key": api_key}
        if base_url:
            client_params["base_url"] = base_url

        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=self.config[PROJ_ENDPOINT_KEY], credential=credential) as project_client,
        ):
            # Create thread manager with Vector Store ID for Knowledge Base
            vector_store_id = get_vector_store_id()
            thread_manager = ThreadManager(project_client, vector_store_id)
            
            # Create threads for all agents
            agent_names = ["facts_identifier", "sql_builder", "data_extractor", "knowledge_base", "orchestrator"]
            threads = await thread_manager.get_all_threads(agent_names)
            
            # Create separate clients for each agent
            async with (
                AzureAIAgentClient(project_client=project_client, model_deployment_name=self.config[MODEL_DEPLOYMENT_NAME_KEY], thread_id = threads["orchestrator"].id) as agent_client
            ):
                # Create event handler (один раз для всех)
                event_handler = create_streamlit_event_handler(self.streaming_state, self.spinner_manager)
                
                # Create workflow builder
                workflow_builder = WorkflowBuilder(
                    agent_client=agent_client,
                    project_client=project_client,
                    model=self.config[MODEL_DEPLOYMENT_NAME_KEY],
                    middleware=[self._create_tool_calls_middleware(event_handler)],
                    tools=[mcp_tool_with_approval, self.get_time],
                    spinner_manager=self.spinner_manager,
                    event_handler=event_handler
                )
                
                # Build workflow with all agents
                workflow = await workflow_builder.build_workflow(threads, prompt)

                await workflow.run(prompt)

                self.spinner_manager.stop()
    
    def _create_tool_calls_middleware(self, event_handler):
        """Create tool calls middleware with provided event handler."""
        from agent_framework import agent_middleware
        from src.middleware.agent_events_middleware import agent_events_middleware

        @agent_middleware
        async def tool_calls_middleware(context, next):
            """Middleware that handles tool calls events via event handler."""
            return await agent_events_middleware(context, next, event_handler)
        
        return tool_calls_middleware
    
    def handle_user_input(self) -> None:
        """Handle user input and run workflow."""
        if prompt := st.chat_input("Say something:"):
            # User message - simple dict (not an event)
            st.session_state.messages.append({"role": "user", "content": prompt, "agent_id": None})
            
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Get user initials
            user_initials = get_user_initials(st.session_state.get("auth_data", {}))
            span_name = f"Magentic ({user_initials}): {prompt}" if user_initials else f"Magentic: {prompt}"
            
            with get_tracer().start_as_current_span(span_name, kind=SpanKind.CLIENT) as current_span:
                print(f"Trace ID: {format_trace_id(current_span.get_span_context().trace_id)}")
                asyncio.run(self.run_workflow(prompt))
    
    def run(self) -> None:
        """Main application entry point."""
        self.initialize()
        self.render_ui()
        self.handle_user_input()
