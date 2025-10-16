"""Ultra simple chat - refactored with event stream architecture."""

from tracemalloc import stop
import streamlit as st
import logging
import os
import asyncio
from src.config import get_config, get_mcp_config, setup_environment_variables, get_auth_config, get_openai_config, get_vector_store_id
from src.constants import PROJ_ENDPOINT_KEY, AGENT_ID_KEY, MCP_SERVER_URL_KEY, MODEL_DEPLOYMENT_NAME_KEY, OPENAI_API_KEY, OPENAI_MODEL_KEY, OPENAI_BASE_URL_KEY, MCP_ALLOWED_TOOLS_KEY
from src.mcp_client import get_mcp_token_sync, display_mcp_status
from src.auth import initialize_msal_auth
from agent_framework import HostedMCPTool, ChatMessage, AgentRunResponseUpdate
from agent_framework import WorkflowBuilder, MagenticBuilder, WorkflowOutputEvent, RequestInfoEvent, WorkflowFailedEvent, RequestInfoExecutor, WorkflowStatusEvent, WorkflowRunState
from agent_framework.openai import OpenAIChatClient, OpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework.azure import AzureAIAgentClient
from datetime import datetime, timezone
from azure.ai.projects.aio import AIProjectClient
from src.magnetic_prompts import (
    ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT,
    ORCHESTRATOR_PROGRESS_LEDGER_PROMPT,
    ORCHESTRATOR_FINAL_ANSWER_PROMPT
)
from src.agent_instructions import (
    SQL_BUILDER_INSTRUCTIONS,
    SQL_BUILDER_ADDITIONAL_INSTRUCTIONS,
    SQL_BUILDER_DESCRIPTION,
    SQL_VALIDATOR_INSTRUCTIONS,
    SQL_VALIDATOR_ADDITIONAL_INSTRUCTIONS,
    SQL_VALIDATOR_DESCRIPTION,
    DATA_EXTRACTOR_INSTRUCTIONS,
    DATA_EXTRACTOR_ADDITIONAL_INSTRUCTIONS,
    DATA_EXTRACTOR_DESCRIPTION,
    GLOSSARY_AGENT_ADDITIONAL_INSTRUCTIONS,
    GLOSSARY_AGENT_DESCRIPTION,
    ORCHESTRATOR_INSTRUCTIONS
)
from agent_framework import (
    ChatAgent,
    HostedCodeInterpreterTool,
    MagenticAgentDeltaEvent,
    MagenticAgentMessageEvent,
    MagenticBuilder,
    MagenticCallbackEvent,
    MagenticCallbackMode,
    MagenticFinalResultEvent,
    MagenticOrchestratorMessageEvent,
    ExecutorInvokedEvent,
    MCPStreamableHTTPTool,
    WorkflowOutputEvent,
)

from src.workaround_mcp_headers import patch_azure_ai_client
from src.workaround_magentic import patch_magentic_orchestrator
import src.workaround_agent_executor as agent_executor_workaround
from src.workaround_agent_executor import patch_magentic_for_event_interception
from src.event_renderer import EventRenderer
# Simplified: Direct AI Project + Vector Store integration

# Применяем патчи ДО создания клиента
patch_azure_ai_client()
patch_magentic_orchestrator()
patch_magentic_for_event_interception()

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


# Контейнеры для streaming сообщений агентов
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
        
        # Обработка ThreadRun (агент взял задачу) - делегируем в EventRenderer
        if isinstance(event, ThreadRun):
            event.agent_id = agent_id
            if hasattr(event, 'status'):
                if event.status == RunStatus.QUEUED:
                    pass;
                elif event.status == RunStatus.COMPLETED:
                    st.session_state.current_chat = st.empty()
                    logger.info(f"ThreadRun COMPLETED: {event}")
                else:
                    st.session_state.current_chat = st.chat_message("🤖")
                    st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
                    with st.session_state.current_chat:
                        EventRenderer.render(event)
            return

        if isinstance(event, ThreadMessage):
            pass;
            return

        if isinstance(event, MessageDeltaChunk):
            if agent_id in _message_containers:
                # Извлекаем текст из delta
                if hasattr(event, 'delta') and hasattr(event.delta, 'content'):
                    for content in event.delta.content:
                        if hasattr(content, 'text') and hasattr(content.text, 'value'):
                            _message_accumulated_text[agent_id] += content.text.value
                
                # Обновляем контейнер
                _message_containers[agent_id].markdown(_message_accumulated_text[agent_id])
            return

        if isinstance(event, RunStep):
            run_step = event

            # Обработка MESSAGE_CREATION
            if run_step.type == RunStepType.MESSAGE_CREATION:
                # IN_PROGRESS - создаем контейнер для streaming
                if run_step.status == RunStepStatus.IN_PROGRESS:
                    if agent_id not in _message_containers:
                        _message_containers[agent_id] = st.session_state.current_chat.empty()
                        _message_accumulated_text[agent_id] = ""
                
                # COMPLETED - убираем контейнер, выводим через рендерер
                elif run_step.status == RunStepStatus.COMPLETED:
                    if agent_id in _message_containers:
                        final_text = _message_accumulated_text.get(agent_id, "")
                        # Убираем streaming контейнер
                        _message_containers[agent_id].empty()
                        del _message_containers[agent_id]
                        del _message_accumulated_text[agent_id]
                        if final_text != "":
                            with st.session_state.current_chat:
                            # Рендерим через EventRenderer (свернутое по умолчанию)
                                EventRenderer.render(final_text)
                            
                            # Save only text content for session persistence
                            st.session_state.messages.append({"role": "🤖", "content": final_text, "agent_id": agent_id})
                return

            # Обработка TOOL_CALLS - делегируем в EventRenderer
            if (event.type == RunStepType.TOOL_CALLS and 
                hasattr(event, 'step_details') and 
                hasattr(event.step_details, 'tool_calls') and 
                event.step_details.tool_calls):

                with st.session_state.current_chat:
                    EventRenderer.render(event)
                st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
            return;
        
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
            pass;
            return;
        # Рендерим через EventRenderer
        with st.chat_message("assistant"):
            EventRenderer.render(event)
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

async def get_vector_store_files(vector_store_id: str, config: dict):
    """
    Get list of files in Vector Store using REST API.
    Reference: https://learn.microsoft.com/en-us/rest/api/aifoundry/aiagents/vector-store-files/list-vector-store-files
    
    Args:
        vector_store_id: ID of the Vector Store
        config: Configuration dictionary with project endpoint
        
    Returns:
        List of file dicts with id, filename, status
    """
    try:
        async with DefaultAzureCredential() as credential:
            # Get token for authentication
            token = await credential.get_token("https://ai.azure.com/.default")
            
            # Build REST API URL
            endpoint = config[PROJ_ENDPOINT_KEY]
            url = f"{endpoint}/vector_stores/{vector_store_id}/files?api-version=v1"
            
            # Make HTTP request
            import aiohttp
            headers = {
                'Authorization': f'Bearer {token.token}',
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        files = []
                        
                        # Process each file from response
                        for file_data in data.get('data', []):
                            # Get full file details to get filename
                            file_id = file_data.get('id')
                            file_url = f"{endpoint}/files/{file_id}?api-version=v1"
                            
                            async with session.get(file_url, headers=headers) as file_response:
                                if file_response.status == 200:
                                    file_details = await file_response.json()
                                    
                                    # Debug: Log full response to see what API returns
                                    logger.info(f'GET /files/{file_id} response: {file_details}')
                                    
                                    filename = file_details.get('filename', '')
                                    logger.info(f'Extracted filename for {file_id}: "{filename}"')
                                    
                                    if not filename:
                                        filename = f'File {file_id[:8]}...'
                                        logger.warning(f'Filename is empty, using fallback: {filename}')
                                    
                                    files.append({
                                        'id': file_id,
                                        'filename': filename,
                                        'status': file_data.get('status', 'unknown')
                                    })
                                else:
                                    # Fallback if can't get filename
                                    logger.warning(f'GET /files/{file_id} failed with status {file_response.status}')
                                    files.append({
                                        'id': file_id,
                                        'filename': f'File {file_id[:8]}...',
                                        'status': file_data.get('status', 'unknown')
                                    })
                        
                        return files
                    else:
                        logger.error(f'Failed to list files: HTTP {response.status}')
                        return []
                
    except Exception as e:
        logger.error(f'Failed to list vector store files: {e}')
        return []


async def upload_file_to_vector_store(file_data: bytes, filename: str, vector_store_id: str, config: dict):
    """
    Upload file to AI Project and add to Vector Store.
    Uses Python SDK for file upload (properly handles filename) and REST API for adding to Vector Store.
    
    Args:
        file_data: File content as bytes
        filename: Name of the file
        vector_store_id: ID of the Vector Store
        config: Configuration dictionary with project endpoint
    """
    import tempfile
    import os
    
    temp_file_path = None
    try:
        async with DefaultAzureCredential() as credential:
            async with AIProjectClient(endpoint=config[PROJ_ENDPOINT_KEY], credential=credential) as project_client:
                # Step 1: Save file temporarily (SDK requires file path, not BytesIO)
                # Create temp directory and save file with original name
                temp_dir = tempfile.mkdtemp()
                temp_file_path = os.path.join(temp_dir, filename)
                with open(temp_file_path, 'wb') as temp_file:
                    temp_file.write(file_data)
                
                # Step 2: Upload file to AI Project using SDK
                # SDK properly handles filename in multipart/form-data
                uploaded_file = await project_client.agents.files.upload_and_poll(
                    file_path=temp_file_path,
                    purpose='assistants'
                )
                
                file_id = uploaded_file.id
                logger.info(f'Uploaded file to AI Project: {file_id}, filename: {uploaded_file.filename}')
                
                # Step 3: Add file to Vector Store using REST API
                # (SDK doesn't have stable API for this yet)
                token = await credential.get_token("https://ai.azure.com/.default")
                endpoint = config[PROJ_ENDPOINT_KEY]
                vs_file_url = f"{endpoint}/vector_stores/{vector_store_id}/files?api-version=v1"
                
                import aiohttp
                headers = {
                    'Authorization': f'Bearer {token.token}',
                    'Content-Type': 'application/json'
                }
                
                payload = {'file_id': file_id}
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(vs_file_url, headers=headers, json=payload) as response:
                        if response.status == 200:
                            vs_file_info = await response.json()
                            logger.info(f'Added file {file_id} to vector store {vector_store_id}')
                            return file_id, vs_file_info.get('id')
                        else:
                            error_text = await response.text()
                            logger.error(f'Failed to add file to vector store: HTTP {response.status}, {error_text}')
                            raise Exception(f'Failed to add file to vector store: HTTP {response.status}')
                
    except Exception as e:
        logger.error(f'Failed to upload file to vector store: {e}')
        raise
    finally:
        # Clean up temporary file and directory
        if temp_file_path:
            try:
                import shutil
                temp_dir = os.path.dirname(temp_file_path)
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.debug(f'Cleaned up temporary directory: {temp_dir}')
            except Exception as e:
                logger.warning(f'Failed to clean up temporary directory: {e}')


async def delete_file_from_vector_store(filename: str, vector_store_id: str, config: dict):
    """
    Delete file from Vector Store by filename.
    
    Args:
        filename: Name of the file to delete
        vector_store_id: ID of the Vector Store
        config: Configuration dictionary with project endpoint
    """
    try:
        async with DefaultAzureCredential() as credential:
            # Get token for authentication
            token = await credential.get_token("https://ai.azure.com/.default")
            
            # Build REST API URL
            endpoint = config[PROJ_ENDPOINT_KEY]
            
            import aiohttp
            headers = {
                'Authorization': f'Bearer {token.token}',
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                # Step 1: List all files in vector store
                list_url = f"{endpoint}/vector_stores/{vector_store_id}/files?api-version=v1"
                
                async with session.get(list_url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f'Failed to list files: HTTP {response.status}')
                        return False
                    
                    data = await response.json()
                    files = data.get('data', [])
                
                # Step 2: Find file by name
                file_id_to_delete = None
                for file_data in files:
                    file_id = file_data.get('id')
                    file_url = f"{endpoint}/files/{file_id}?api-version=v1"
                    
                    async with session.get(file_url, headers=headers) as response:
                        if response.status == 200:
                            file_details = await response.json()
                            if file_details.get('filename') == filename:
                                file_id_to_delete = file_id
                                break
                
                if not file_id_to_delete:
                    logger.warning(f'File {filename} not found in vector store')
                    return False
                
                # Step 3: Delete from vector store
                delete_vs_url = f"{endpoint}/vector_stores/{vector_store_id}/files/{file_id_to_delete}?api-version=v1"
                
                async with session.delete(delete_vs_url, headers=headers) as response:
                    if response.status in [200, 204]:
                        logger.info(f'Deleted file {file_id_to_delete} ({filename}) from vector store')
                    else:
                        logger.error(f'Failed to delete from vector store: HTTP {response.status}')
                        return False
                
                # Step 4: Delete file from AI Project
                delete_file_url = f"{endpoint}/files/{file_id_to_delete}?api-version=v1"
                
                async with session.delete(delete_file_url, headers=headers) as response:
                    if response.status in [200, 204]:
                        logger.info(f'Deleted file {file_id_to_delete} from AI Project')
                        return True
                    else:
                        logger.warning(f'Failed to delete file from AI Project: HTTP {response.status}')
                        # Still return True as it was removed from vector store
                        return True
                
    except Exception as e:
        logger.error(f'Failed to delete file from vector store: {e}')
        return False


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
    
    # Knowledge Base Management in Sidebar
    with st.sidebar:
        st.header('📚 Knowledge Base')
        
        vector_store_id = get_vector_store_id()
        if vector_store_id:
            # Display files from Vector Store using REST API
            try:
                import asyncio
                files = asyncio.run(get_vector_store_files(vector_store_id, config))
                
                if files:
                    st.metric('Files in Knowledge Base', len(files))
                    
                    with st.expander('View Files', expanded=False):
                        st.info('💡 Files are accessible by agents via File Search Tool. Download is not supported for assistant files.')
                        for file_info in files:
                            col1, col2, col3 = st.columns([4, 1, 1])
                            with col1:
                                st.text(file_info['filename'])
                            with col2:
                                status = file_info.get('status', 'unknown')
                                if status == 'completed':
                                    st.caption('✅ Ready')
                                elif status == 'in_progress':
                                    st.caption('⏳ Processing')
                                elif status == 'failed':
                                    st.caption('❌ Failed')
                            with col3:
                                if st.button('🗑️', key=f"delete_{file_info['id']}", help='Delete file'):
                                    try:
                                        deleted = asyncio.run(delete_file_from_vector_store(
                                            file_info['filename'],
                                            vector_store_id,
                                            config
                                        ))
                                        if deleted:
                                            st.success(f"✅ Deleted {file_info['filename']}")
                                        else:
                                            st.warning(f"⚠️ Could not delete {file_info['filename']}")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f'❌ Error: {e}')
                else:
                    st.info('No files in Knowledge Base yet')
            except Exception as e:
                st.warning(f'Could not load files: {e}')
            
            st.divider()
            
            # File uploader
            uploaded_files = st.file_uploader(
                'Upload documents',
                accept_multiple_files=True,
                type=['pdf', 'txt', 'docx', 'md', 'json', 'csv'],
                help='Upload documents that agents can search through'
            )
            
            if uploaded_files and st.button('📤 Upload', type='primary'):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                upload_errors = []
                upload_success = []
                
                for idx, uploaded_file in enumerate(uploaded_files):
                    file_data = uploaded_file.getvalue()
                    status_text.text(f'Uploading {uploaded_file.name}...')
                    
                    try:
                        import asyncio
                        asyncio.run(upload_file_to_vector_store(
                            file_data,
                            uploaded_file.name,
                            vector_store_id,
                            config
                        ))
                        upload_success.append(uploaded_file.name)
                    except Exception as e:
                        upload_errors.append(f'{uploaded_file.name}: {e}')
                    
                    progress_bar.progress((idx + 1) / len(uploaded_files))
                
                status_text.empty()
                progress_bar.empty()
                
                if upload_success:
                    st.success(f'✅ Uploaded {len(upload_success)} file(s)!')
                
                if upload_errors:
                    st.error('⚠️ Upload errors:')
                    for error in upload_errors:
                        st.error(f'  • {error}')
                
                st.rerun()
            
            st.caption(f'📋 Vector Store: `{vector_store_id[:20]}...`')
        else:
            st.info('💡 Configure `vector_store_id` in secrets.toml')
        
        st.divider()

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
        # Prepare common client parameters
        client_params = {"model_id": model_name, "api_key": api_key}
        if base_url:
            client_params["base_url"] = base_url

        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=config[PROJ_ENDPOINT_KEY], credential=credential) as project_client,
        ):
            # Vector Store for File Search (if configured)
            vector_store_id = get_vector_store_id()
            if vector_store_id:
                logger.info(f'File Search Tool enabled with vector store: {vector_store_id}')
            
            # Создаем отдельные threads для каждого агента
            facts_identifier_thread = await project_client.agents.threads.create() if st.session_state.get("facts_identifier_thread", None) is None else st.session_state.facts_identifier_thread
            sql_builder_thread = await project_client.agents.threads.create() if st.session_state.get("sql_builder_thread", None) is None else st.session_state.sql_builder_thread
            sql_validator_thread = await project_client.agents.threads.create() if st.session_state.get("sql_validator_thread", None) is None else st.session_state.sql_validator_thread
            data_extractor_thread = await project_client.agents.threads.create() if st.session_state.get("data_extractor_thread", None) is None else st.session_state.data_extractor_thread
            glossary_thread = await project_client.agents.threads.create() if st.session_state.get("glossary_thread", None) is None else st.session_state.glossary_thread
            knowledge_base_thread = await project_client.agents.threads.create() if st.session_state.get("knowledge_base_thread", None) is None else st.session_state.knowledge_base_thread
            orchestrator_thread = await project_client.agents.threads.create() if st.session_state.get("orchestrator_thread", None) is None else st.session_state.orchestrator_thread

            
            # Создаем отдельные клиенты для каждого агента
            async with (
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=facts_identifier_thread.id) as facts_identifier_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=sql_builder_thread.id) as sql_builder_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=sql_validator_thread.id) as sql_validator_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=data_extractor_thread.id) as data_extractor_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=glossary_thread.id) as glossary_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=knowledge_base_thread.id) as knowledge_base_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=orchestrator_thread.id) as orchestrator_client,
            ):
                # Facts Identifier - NO file_search, only MCP
                facts_instructions = f"""for the user request: {prompt}
                
                Identify tables and fields by using MCP Tools. When searching for specific entities (property names, market names, etc.), use progressive matching strategy:
                1. Try exact match first (WHERE name = 'value')
                2. If not found, try partial match (WHERE name LIKE '%value%')
                3. If still not found, try similar names
                
                Refine fields and tables by sampling data using SELECT TOP 1 [fields] FROM [table] and make it return requested values before finishing your response.
                
                You will justify what tools you are going to use before requesting them.
                """
                
                facts_additional = "Annotate what you want before using MCP Tools. Always use MCP Tools before returning response. Use MCP Tools to identify tables and fields. Ensure that you found requested rows by sampling data using SELECT TOP 1 [fields] FROM [table]. Never generate anything on your own."
                
                facts_identifier_agent = facts_identifier_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="Facts Identifier",
                    description="Use MCP Tools to find every entity (IDs, names, values) for the user request which is not covered by the glossary. Search for entities by name using progressive matching: 1) Exact match first, 2) Then partial/LIKE match, 3) Then similar names, 4) Take larger datasets. Execute SELECT TOP XXX to validate found entities.",
                    instructions=facts_instructions,
                    tools=[mcp_tool_with_approval, get_time],
                    conversation_id=sql_builder_thread.id,
                    temperature=0.1,
                    additional_instructions=facts_additional
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

                # Glossary - NO file_search
                glossary_agent = glossary_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="Glossary",
                    description=GLOSSARY_AGENT_DESCRIPTION,
                    instructions=st.secrets["glossary"]["instructions"],
                    tools=[get_time],
                    conversation_id=glossary_thread.id,
                    temperature=0.1,
                    additional_instructions=GLOSSARY_AGENT_ADDITIONAL_INSTRUCTIONS,
                )

                # Knowledge Base Agent - ONLY file_search, NO MCP
                knowledge_base_agent = None
                if vector_store_id:
                    knowledge_base_agent = knowledge_base_client.create_agent(
                        model=config[MODEL_DEPLOYMENT_NAME_KEY],
                        name="Knowledge Base Agent",
                        description="Search knowledge base for entity mappings and domain information. Returns exact information from knowledge base files.",
                        instructions="""You are a domain knowledge base search assistant.

CRITICAL INSTRUCTIONS:
1. You have a Q&A knowledge base uploaded as files
2. The knowledge base contains EXACT entity mappings (business terms → database tables)
3. When asked about entity mappings, search your knowledge base using file_search tool
4. The format is "Q: question / A: answer"
5. QUOTE the exact answer from the knowledge base with [citation]
6. DO NOT make up answers - only use information from the knowledge base
7. If you find the answer → cite it exactly with source
8. If you don't find anything → say "I don't have information about [term]"

Example:
User asks: "What is розовые слоны?"
You search the knowledge base and find: "Q: What is 'розовые слоны'? A: 'розовые слоны' (pink elephants) is business slang that maps to the msdyn_workorder database table."
You respond: "According to the knowledge base [citation], 'розовые слоны' (pink elephants) maps to the msdyn_workorder database table."

NEVER invent table names or information not found in the knowledge base!""",
                        tools=[{"type": "file_search"}],
                        tool_resources={
                            "file_search": {
                                "vector_store_ids": [vector_store_id]
                            }
                        },
                        conversation_id=knowledge_base_thread.id,
                        temperature=0.0
                    )
                    logger.info(f"Created Knowledge Base Agent with file_search: {knowledge_base_agent.id}")

                st.session_state.facts_identifier_thread = facts_identifier_thread
                st.session_state.sql_builder_thread = sql_builder_thread
                st.session_state.sql_validator_thread = sql_validator_thread
                st.session_state.data_extractor_thread = data_extractor_thread
                st.session_state.glossary_thread = glossary_thread
                st.session_state.knowledge_base_thread = knowledge_base_thread
                st.session_state.orchestrator_thread = orchestrator_thread
                
                # Устанавливаем глобальные callbacks для workaround модуля
                agent_executor_workaround.global_runstep_callback = on_runstep_event

                # Build participants dict
                participants_dict = {
                    "facts_identifier_agent": facts_identifier_agent,
                    "sql_builder": sql_builder_agent,
                    "data_extractor": data_extractor_agent,
                    "glossary": glossary_agent,
                }
                
                # Add knowledge_base agent if configured
                if knowledge_base_agent:
                    participants_dict["knowledge_base"] = knowledge_base_agent

                # Orchestrator instructions with knowledge_base context
                if knowledge_base_agent:
                    # Override workflow to make Knowledge Base Agent the FIRST step
                    orchestrator_instructions = """You are the LEAD DATA ANALYST orchestrating a team of specialists.

🔴 CRITICAL: MANDATORY WORKFLOW 🔴

STEP 0 (MANDATORY): knowledge_base - ALWAYS START HERE!
- BEFORE anything else, ask 'knowledge_base' agent about ANY unfamiliar or domain-specific terms in the request
- Knowledge Base contains:
  * Entity mappings (business slang → database tables)
  * Business rules and logic
  * Relationships between entities
  * Domain-specific terminology
- Example: If user mentions "розовые слоны", "property", "job profile" → ASK knowledge_base FIRST!

STEP 1: glossary - Get business term definitions and table/field names (use knowledge_base info if available)

STEP 2: facts_identifier_agent - Use glossary info + knowledge_base info + MCP tools to identify all facts

STEP 3: sql_builder <> data_extractor

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
1. 🔴 ALWAYS START by asking 'knowledge_base' about unfamiliar terms or domain concepts
2. THEN use glossary to get business terms and table/field names
3. THEN use facts_identifier with all gathered info to find facts (row IDs, names, exact values)
4. PASS all identified facts (tables, fields, IDs, names) to the agents
5. Remember: specialists don't know what you already know - provide all context!
"""
                else:
                    orchestrator_instructions = ORCHESTRATOR_INSTRUCTIONS

                workflow = (
                    MagenticBuilder()
                    .participants(**participants_dict)
                    .on_event(on_orchestrator_event, mode=MagenticCallbackMode.STREAMING)
                    .with_standard_manager(
                        chat_client=orchestrator_client,
                        instructions=orchestrator_instructions,
                        max_round_count=15,
                        max_stall_count=4,
                        max_reset_count=2,
                    )
                    .build()
                )

                await workflow.run(prompt)
                    

    if prompt := st.chat_input("Say something:"):
            # User message - simple dict (not an event)
            st.session_state.messages.append({"role": "user", "content": prompt, "agent_id": None})
            
            with st.chat_message("user"):
                st.markdown(prompt)
            
            
            # Используем sync-over- async для Streamlit
            #nest_asyncio.apply()
            asyncio.run(run_workflow(prompt))
        

if __name__ == "__main__":
    main()
