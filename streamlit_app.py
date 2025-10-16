"""Ultra simple chat - refactored with event stream architecture."""

from tracemalloc import stop
import streamlit as st
import logging
import asyncio
from src.config import get_config, get_mcp_config, setup_environment_variables, get_auth_config, get_openai_config
from src.constants import PROJ_ENDPOINT_KEY, MCP_SERVER_URL_KEY, MODEL_DEPLOYMENT_NAME_KEY, OPENAI_API_KEY, OPENAI_MODEL_KEY, OPENAI_BASE_URL_KEY, MCP_ALLOWED_TOOLS_KEY
from src.mcp_client import get_mcp_token_sync, display_mcp_status
from src.auth import initialize_msal_auth
from agent_framework import HostedMCPTool, MagenticBuilder
from agent_framework.openai import OpenAIChatClient, OpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework.azure import AzureAIAgentClient
from datetime import datetime, timezone
from azure.ai.projects.aio import AIProjectClient

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
    MagenticBuilder
)

from src.workaround_mcp_headers import patch_azure_ai_client
from src.workaround_magentic import patch_magentic_orchestrator
import src.workaround_agent_executor as agent_executor_workaround
from src.workaround_agent_executor import patch_magentic_for_event_interception
from src.event_renderer import EventRenderer, SpinnerManager

# Apply patches BEFORE creating client
patch_azure_ai_client()
patch_magentic_orchestrator()
patch_magentic_for_event_interception()

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


# Containers for streaming agent messages
_message_containers = {}
_message_accumulated_text = {}

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

async def on_runstep_event(agent_id: str, event) -> None:
    """
    Handle RunStep, ThreadRun and MessageDeltaChunk from Azure AI agents.
    
    Args:
        agent_id: ID of the agent that generated the step
        event: RunStep, ThreadRun or MessageDeltaChunk object from Azure AI
    """
    try:
        from azure.ai.agents.models import (
            RunStepType,
            RunStepStatus,
            MessageDeltaChunk,
            ThreadRun,
            RunStep,
            RunStatus,
            ThreadMessage
        )
        
        # Handle ThreadRun (agent took task) - delegate to EventRenderer
        if isinstance(event, ThreadRun):
            event.agent_id = agent_id
            if hasattr(event, 'status'):
                if event.status == RunStatus.QUEUED:
                    pass;
                elif event.status == RunStatus.COMPLETED:
                    st.session_state.current_chat = st.empty()
                    SpinnerManager.start("Thinking about next steps...")
                else:
                    st.session_state.current_chat = st.chat_message("🤖")
                    st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
                    with st.session_state.current_chat:
                        EventRenderer.render(event, auto_start_spinner="Thinking...")
            return

        if isinstance(event, ThreadMessage):
            pass;
            return

        if isinstance(event, MessageDeltaChunk):
            if agent_id in _message_containers:
                # Extract text from delta
                if hasattr(event, 'delta') and hasattr(event.delta, 'content'):
                    for content in event.delta.content:
                        if hasattr(content, 'text') and hasattr(content.text, 'value'):
                            _message_accumulated_text[agent_id] += content.text.value
                
                # Update container
                _message_containers[agent_id].markdown(_message_accumulated_text[agent_id])
            return

        if isinstance(event, RunStep):
            run_step = event

            # Handle MESSAGE_CREATION
            if run_step.type == RunStepType.MESSAGE_CREATION:
                # IN_PROGRESS - create container for streaming
                if run_step.status == RunStepStatus.IN_PROGRESS:
                    if agent_id not in _message_containers:
                        _message_containers[agent_id] = st.session_state.current_chat.empty()
                        _message_accumulated_text[agent_id] = ""
                        SpinnerManager.stop()
                
                # COMPLETED - remove container, display through renderer
                elif run_step.status == RunStepStatus.COMPLETED:
                    if agent_id in _message_containers:
                        final_text = _message_accumulated_text.get(agent_id, "")
                        # Remove streaming container
                        _message_containers[agent_id].empty()
                        del _message_containers[agent_id]
                        del _message_accumulated_text[agent_id]
                        if final_text != "":
                            with st.session_state.current_chat:
                            # Render through EventRenderer (collapsed by default)
                                EventRenderer.render(final_text)
                            
                            # Save only text content for session persistence
                            st.session_state.messages.append({"role": "🤖", "content": final_text, "agent_id": agent_id})
                return

            # Handle TOOL_CALLS - delegate to EventRenderer
            if (event.type == RunStepType.TOOL_CALLS):
            
                if (hasattr(event, 'step_details') and 
                    hasattr(event.step_details, 'tool_calls') and 
                    event.step_details.tool_calls):

                    with st.session_state.current_chat:
                        EventRenderer.render(event)
                    st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
                    SpinnerManager.stop()
                else:
                    with st.session_state.current_chat:
                        SpinnerManager.start("Invoking a tool...")

            return
        
    except ImportError:
        logger.warning("Azure AI models not available for RunStep processing")
    except Exception as e:
        logger.error(f"Error processing RunStep: {e}", exc_info=True)


async def on_orchestrator_event(event: MagenticCallbackEvent) -> None:
    """
    The `on_event` callback processes events emitted by the workflow.
    Events include: orchestrator messages, agent delta updates, agent messages, and final result events.
    """
    
    if isinstance(event, MagenticOrchestratorMessageEvent):
        
        if event.kind == "user_task":
            SpinnerManager.start("Thinking...")
            return;
        # Render through EventRenderer
        with st.chat_message("assistant"):
            EventRenderer.render(event, auto_start_spinner="Handing the task to the assistants...")
            st.session_state.messages.append({"role": "assistant", "event": event, "agent_id": None})
    
    elif isinstance(event, MagenticFinalResultEvent):

        if event.message is not None:
            with st.chat_message("assistant"):
                EventRenderer.render(event)
                st.session_state.messages.append({"role": "assistant", "event": event, "agent_id": None})

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

def main():


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
        SpinnerManager.start("Planning the task...")
        # Prepare common client parameters
        client_params = {"model_id": model_name, "api_key": api_key}
        if base_url:
            client_params["base_url"] = base_url

        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=config[PROJ_ENDPOINT_KEY], credential=credential) as project_client,
        ):
            # Create separate threads for each agent
            facts_identifier_thread = await project_client.agents.threads.create() if st.session_state.get("facts_identifier_thread", None) is None else st.session_state.facts_identifier_thread
            sql_builder_thread = await project_client.agents.threads.create() if st.session_state.get("sql_builder_thread", None) is None else st.session_state.sql_builder_thread
            sql_validator_thread = await project_client.agents.threads.create() if st.session_state.get("sql_validator_thread", None) is None else st.session_state.sql_validator_thread
            data_extractor_thread = await project_client.agents.threads.create() if st.session_state.get("data_extractor_thread", None) is None else st.session_state.data_extractor_thread
            glossary_thread = await project_client.agents.threads.create() if st.session_state.get("glossary_thread", None) is None else st.session_state.glossary_thread
            orchestrator_thread = await project_client.agents.threads.create() if st.session_state.get("orchestrator_thread", None) is None else st.session_state.orchestrator_thread

            
            # Create separate clients for each agent
            async with (
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=facts_identifier_thread.id) as facts_identifier_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=sql_builder_thread.id) as sql_builder_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=sql_validator_thread.id) as sql_validator_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=data_extractor_thread.id) as data_extractor_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=glossary_thread.id) as glossary_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=orchestrator_thread.id) as orchestrator_client,
            ):
                facts_identifier_agent = facts_identifier_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="Facts Identifier",
                    description="Use MCP Tools to find every entity (IDs, names, values) for the user request which is not covered by the glossary. Search for entities by name using progressive matching: 1) Exact match first, 2) Then partial/LIKE match, 3) Then similar names, 4) Take larger datasets. Execute SELECT TOP XXX to validate found entities.",
                    instructions=f"""for the user request: {prompt}

                        Identify tables and fields by using MCP Tools. When searching for specific entities (property names, market names, etc.), use progressive matching strategy:
                        1. Try exact match first (WHERE name = 'value')
                        2. If not found, try partial match (WHERE name LIKE '%value%')
                        3. If still not found, try similar names
                        
                        Refine fields and tables by sampling data using SELECT TOP 1 [fields] FROM [table] and make it return requested values before finishing your response.
                        
                        You will justify what tools you are going to use before requesting them.
                        """,

                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=sql_builder_thread.id,
                    temperature=0.1,
                    additional_instructions="Annotate what you want before using MCP Tools. Always use MCP Tools before returning response. Use MCP Tools to identify tables and fields. Ensure that you found requested rows by sampling data using SELECT TOP 1 [fields] FROM [table]. Never generate anything on your own."
                )

                sql_builder_agent = sql_builder_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="SQL Builder",
                    user="sql_builder",
                    description=SQL_BUILDER_DESCRIPTION,
                    instructions=SQL_BUILDER_INSTRUCTIONS,
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=sql_builder_thread.id,
                    temperature=0.1,
                    additional_instructions=SQL_BUILDER_ADDITIONAL_INSTRUCTIONS,
                )

                logger.info(f"Created agent {sql_builder_agent}")

                data_extractor_agent = data_extractor_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="Data Extractor",
                    description=DATA_EXTRACTOR_DESCRIPTION,
                    instructions=DATA_EXTRACTOR_INSTRUCTIONS,
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=data_extractor_thread.id,
                    temperature=0.1,
                    additional_instructions=DATA_EXTRACTOR_ADDITIONAL_INSTRUCTIONS,
                )

                glossary_agent = glossary_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="Glossary",
                    description=GLOSSARY_AGENT_DESCRIPTION,
                    instructions=st.secrets["glossary"]["instructions"],
                    conversation_id=glossary_thread.id,
                    temperature=0.1,
                    additional_instructions=GLOSSARY_AGENT_ADDITIONAL_INSTRUCTIONS,
                )

                st.session_state.facts_identifier_thread = facts_identifier_thread
                st.session_state.sql_builder_thread = sql_builder_thread
                st.session_state.sql_validator_thread = sql_validator_thread
                st.session_state.data_extractor_thread = data_extractor_thread
                st.session_state.glossary_thread = glossary_thread
                st.session_state.orchestrator_thread = orchestrator_thread
                
                # Set global callbacks for workaround module
                agent_executor_workaround.global_runstep_callback = on_runstep_event

                workflow = (
                    MagenticBuilder()
                    .participants(
                        facts_identifier_agent = facts_identifier_agent,
                        sql_builder = sql_builder_agent,
                        data_extractor = data_extractor_agent,
                        glossary = glossary_agent,
                    )
                    .on_event(on_orchestrator_event, mode=MagenticCallbackMode.STREAMING)
                    .with_standard_manager(
                        chat_client=orchestrator_client,
                        instructions=ORCHESTRATOR_INSTRUCTIONS,

                        max_round_count=15,
                        max_stall_count=4,
                        max_reset_count=2,
                    )
                    .build()
                )

                await workflow.run(prompt)

                SpinnerManager.stop()

                    

    if prompt := st.chat_input("Say something:"):
            # User message - simple dict (not an event)
            st.session_state.messages.append({"role": "user", "content": prompt, "agent_id": None})
            
            with st.chat_message("user"):
                st.markdown(prompt)
            
            asyncio.run(run_workflow(prompt))
        

if __name__ == "__main__":
    main()
