"""Ultra simple chat - refactored with event stream architecture."""

from tracemalloc import stop
import streamlit as st
import logging
import asyncio
from src.config import get_config, get_mcp_config, setup_environment_variables, get_auth_config, get_openai_config
from src.constants import PROJ_ENDPOINT_KEY, MCP_SERVER_URL_KEY, MODEL_DEPLOYMENT_NAME_KEY, OPENAI_API_KEY, OPENAI_MODEL_KEY, OPENAI_BASE_URL_KEY, MCP_ALLOWED_TOOLS_KEY
from src.mcp_client import get_mcp_token_sync, display_mcp_status
from src.auth import initialize_msal_auth, get_user_initials
from agent_framework import HostedMCPTool, MagenticBuilder
from agent_framework.openai import OpenAIChatClient, OpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework.azure import AzureAIAgentClient
from datetime import datetime, timezone
from azure.ai.projects.aio import AIProjectClient

from agent_framework.observability import setup_observability, get_tracer
from opentelemetry.trace import SpanKind
from opentelemetry.trace.span import format_trace_id

from src.agent_instructions import (
    SQL_BUILDER_INSTRUCTIONS,
    SQL_BUILDER_ADDITIONAL_INSTRUCTIONS,
    SQL_BUILDER_DESCRIPTION,
    DATA_EXTRACTOR_INSTRUCTIONS,
    DATA_EXTRACTOR_ADDITIONAL_INSTRUCTIONS,
    DATA_EXTRACTOR_DESCRIPTION,
    GLOSSARY_AGENT_ADDITIONAL_INSTRUCTIONS,
    GLOSSARY_AGENT_DESCRIPTION,
    ORCHESTRATOR_INSTRUCTIONS
)
from agent_framework import (
    MagenticBuilder,
    MagenticCallbackEvent,
    MagenticCallbackMode,
    MagenticFinalResultEvent,
    MagenticOrchestratorMessageEvent,
    HostedMCPTool, 
    MagenticBuilder,
    AgentRunContext,
    AgentRunResponse,
    AgentRunResponseUpdate,
    ChatMessage,
    Role,
    TextContent
)
from typing import Callable, Awaitable, AsyncIterable

from src.middleware.agent_events_middleware import agent_events_middleware
from src.middleware.streaming_state import StreamingStateManager
from src.middleware.spinner_manager import SpinnerManager
from src.agents.factory import AgentFactory
from src.agents.thread_manager import ThreadManager
from src.workflow.builder import WorkflowBuilder

from src.event_renderer import EventRenderer

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

# Log agent_framework version on startup
import agent_framework
logger.info(f"🔧 agent_framework version: {agent_framework.__version__ if hasattr(agent_framework, '__version__') else 'unknown'}")

# Global state managers (will be initialized in main)
streaming_state = None
spinner_manager = None

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("🤖 Data Analyst Chat")

current_chat = st.empty()
prev_agent_id = None
prev_role = None
for item in st.session_state.messages:
    if (prev_agent_id != item["agent_id"] or prev_role != item["role"]):
        prev_role = item["role"]
        prev_agent_id = item["agent_id"]
        current_chat = st.chat_message(item["role"])

    content = item["event"] if "event" in item else item.get("content", None)
    if content is None:
        continue;
    with current_chat:
        EventRenderer.render(content)

def get_time() -> str:
    """Get the current UTC time."""
    current_time = datetime.now(timezone.utc)
    return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."

st.session_state.current_chat = st.empty()
st.session_state.current_role = st.empty()


# Orchestrator event handler moved to src/workflow/orchestrator_handler.py

def initialize_app() -> None:
    """
    Initialize application: config, auth, MCP, agent manager, session state.
    """
    # Get configuration
    config = get_config()
    if not config:
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
    
    # No modifications - just pass through

# Вариант 1: С вашим callback
def my_tool_calls_handler(event, agent_id):
    """Handle tool calls event."""
    from azure.ai.agents.models import RunStepType
    
    if event.type == RunStepType.TOOL_CALLS:
        pass;
        # Ваш код
        #with st.session_state.current_chat:
        #    EventRenderer.render(event)
        #st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
        #SpinnerManager.stop()

# Создаем middleware функцию с правильным декоратором
from agent_framework import agent_middleware

@agent_middleware
async def tool_calls_middleware(context, next):
    """Middleware that handles tool calls events."""
    return await agent_events_middleware(
        context, 
        next, 
        streaming_state, 
        spinner_manager, 
        on_tool_calls=my_tool_calls_handler
    )

def main():
    global streaming_state, spinner_manager
    
    # Initialize global state managers
    streaming_state = StreamingStateManager()
    spinner_manager = SpinnerManager()

    initialize_app()

    config = get_config()
    
    # Get OpenAI configuration
    openai_config = get_openai_config()
    if not openai_config:
        st.error("❌ Please configure OpenAI settings in Streamlit secrets.")
        st.stop()
    
    api_key = openai_config[OPENAI_API_KEY]
    model_name = openai_config[OPENAI_MODEL_KEY]
    base_url = openai_config.get(OPENAI_BASE_URL_KEY)

    mcp_config = get_mcp_config()
    mcp_token = get_mcp_token_sync(mcp_config)

    # With approval mode and allowed tools
    mcp_tool_with_approval = HostedMCPTool(
        name="rentready_mcp",
        description="Rent Ready MCP tool",
        url=mcp_config[MCP_SERVER_URL_KEY],
        approval_mode="never_require",
        allowed_tools=mcp_config.get(MCP_ALLOWED_TOOLS_KEY, []),
        headers={"Authorization": f"Bearer {mcp_token}"},
    )

    async def run_workflow(prompt: str):
        spinner_manager.start("Planning your request...")
        
        # Prepare common client parameters
        client_params = {"model_id": model_name, "api_key": api_key}
        if base_url:
            client_params["base_url"] = base_url

        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=config[PROJ_ENDPOINT_KEY], credential=credential) as project_client,
        ):
            # Create thread manager
            thread_manager = ThreadManager(project_client)
            
            # Create threads for all agents
            agent_names = ["facts_identifier", "sql_builder", "data_extractor", "glossary", "orchestrator"]
            threads = await thread_manager.get_all_threads(agent_names)
            
            # Create separate clients for each agent
            async with (
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id = threads["orchestrator"].id) as agent_client
            ):
                # Create agent factory
                agent_factory = AgentFactory(
                    agent_client=agent_client,
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    middleware=[tool_calls_middleware],
                    tools=[mcp_tool_with_approval, get_time]
                )
                
                # Create workflow builder
                workflow_builder = WorkflowBuilder(agent_factory, spinner_manager)
                
                # Build workflow with all agents
                workflow = await workflow_builder.build_workflow(agent_client, threads, prompt)

                await workflow.run(prompt)

                spinner_manager.stop()

                    

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
            asyncio.run(run_workflow(prompt))
        

if __name__ == "__main__":
    main()
