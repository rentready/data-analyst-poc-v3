"""Main Streamlit application class."""

import streamlit as st
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.credentials import setup_environment_variables, get_mcp_token_sync, initialize_msal_auth, get_user_initials
from src.ui.thread_manager import ThreadManager
from src.workflow.builder import WorkflowBuilder
from src.middleware.streaming_state import StreamingStateManager
from src.middleware.spinner_manager import SpinnerManager
from src.ui.message_history import render_chat_history
from src.ui.event_handler import create_streamlit_event_handler

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
        # Get configuration directly from secrets
        try:
            self.azure_endpoint = st.secrets["azure_ai_foundry"]["proj_endpoint"]
            self.model_name = st.secrets["azure_ai_foundry"]["model_deployment_name"]
        except KeyError:
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
        try:
            client_id = st.secrets["env"]["AZURE_CLIENT_ID"]
            tenant_id = st.secrets["env"]["AZURE_TENANT_ID"]
        except KeyError:
            st.error("❌ Please configure Azure AD settings in Streamlit secrets.")
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
        try:
            self.openai_api_key = st.secrets["open_ai"]["api_key"]
            self.openai_model = st.secrets["open_ai"]["model"]
            self.openai_base_url = st.secrets["open_ai"].get("base_url")
        except KeyError:
            st.error("❌ Please configure OpenAI settings in Streamlit secrets.")
            st.stop()
        
        # Get MCP configuration
        try:
            self.mcp_server_url = st.secrets["mcp"]["mcp_server_url"]
            self.mcp_allowed_tools = st.secrets["mcp"].get("allowed_tools", [])
        except KeyError:
            self.mcp_server_url = None
            self.mcp_allowed_tools = []
        
        # Initialize state managers
        self.streaming_state = StreamingStateManager()
        self.spinner_manager = SpinnerManager()
    
    def render_ui(self) -> None:
        """Render the main UI components."""
        st.title("🤖 Data Analyst Chat")
        
        # Initialize session state
        if "messages" not in st.session_state:
            st.session_state.messages = []
        
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
        api_key = self.openai_api_key
        model_name = self.openai_model
        base_url = self.openai_base_url

        # Get MCP token if MCP is configured
        mcp_token = None
        if self.mcp_server_url:
            mcp_config = {
                "mcp_client_id": st.secrets["mcp"]["mcp_client_id"],
                "mcp_client_secret": st.secrets["mcp"]["mcp_client_secret"],
                "AZURE_TENANT_ID": st.secrets["env"]["AZURE_TENANT_ID"]
            }
            mcp_token = get_mcp_token_sync(mcp_config)

        # With approval mode and allowed tools
        mcp_tool_with_approval = HostedMCPTool(
            name="rentready_mcp",
            description="Rent Ready MCP tool",
            url=self.mcp_server_url,
            approval_mode="never_require",
            allowed_tools=self.mcp_allowed_tools,
            headers={"Authorization": f"Bearer {mcp_token}"} if mcp_token else {},
        )

        # Prepare common client parameters
        client_params = {"model_id": model_name, "api_key": api_key}
        if base_url:
            client_params["base_url"] = base_url

        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=self.azure_endpoint, credential=credential) as project_client,
        ):
            # Create thread manager
            thread_manager = ThreadManager(project_client)
            
            # Create threads for all agents
            agent_names = ["facts_identifier", "sql_builder", "data_extractor", "glossary", "orchestrator"]
            threads = await thread_manager.get_all_threads(agent_names)
            
            # Create event handler (один раз для всех)
            event_handler = create_streamlit_event_handler(self.streaming_state, self.spinner_manager)
            
            # Create workflow builder
            workflow_builder = WorkflowBuilder(
                project_client=project_client,
                model=self.model_name,
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
