"""Ultra simple chat - refactored with event stream architecture."""

from tracemalloc import stop
import streamlit as st
import logging
import os
import asyncio
from src.config import get_config, get_mcp_config, setup_environment_variables, get_auth_config, get_openai_config
from src.constants import PROJ_ENDPOINT_KEY, AGENT_ID_KEY, MCP_SERVER_URL_KEY, MODEL_DEPLOYMENT_NAME_KEY, OPENAI_API_KEY, OPENAI_MODEL_KEY, OPENAI_BASE_URL_KEY
from src.mcp_client import get_mcp_token_sync, display_mcp_status
from src.auth import initialize_msal_auth
from agent_framework import HostedMCPTool, ChatMessage
from agent_framework import WorkflowBuilder, MagenticBuilder, WorkflowOutputEvent, RequestInfoEvent, WorkflowFailedEvent, RequestInfoExecutor, WorkflowStatusEvent, WorkflowRunState
from agent_framework.openai import OpenAIChatClient, OpenAIResponsesClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework.azure import AzureAIAgentClient
from datetime import datetime, timezone
from azure.ai.projects.aio import AIProjectClient
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
    MCPStreamableHTTPTool,
    WorkflowOutputEvent,
)

from src.workaround_mcp_headers import patch_azure_ai_client

# Применяем патч ДО создания клиента
patch_azure_ai_client()

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

def get_time() -> str:
    """Get the current UTC time."""
    current_time = datetime.now(timezone.utc)
    return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."

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
    st.title("🤖 Ultra Simple Chat")

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
        allowed_tools=[],
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
            AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY]) as client,
        ):
            logger.info(f"MCP token: {mcp_token}")

            sql_builder_agent = client.create_agent(
                name="Sql Generator",
                description="SQL query builder agent",
                instructions="You are data analyst and you will observe the user's question and you will build a SQL Query to use in subsequent steps. You will use the MCP tool to get the data before any asuumptions about what query should be.",
                tools=[
                    mcp_tool_with_approval,
                    get_time
                ],
            )

            sql_validtor_agent = client.create_agent(
                name="Sql Validator",
                description="SQL query validator agent",
                instructions="You are data analyst and you will observe the SQL Query and you will validate it.",
                tools=[
                    mcp_tool_with_approval,
                    get_time
                ],
            )

            data_extractor_agent = client.create_agent(
                name="Data Extractor",
                description="Data extraction agent",
                instructions="You are data analyst and you will observe the SQL Query and you will extract the data from the database.",
                tools=[
                    mcp_tool_with_approval,
                    get_time
                ],
            )

            # Словари для хранения контейнеров и накопленного текста для каждого агента
            agent_containers = {}
            agent_accumulated_text = {}
            
            async def on_event(event: MagenticCallbackEvent) -> None:
                """
                The `on_event` callback processes events emitted by the workflow.
                Events include: orchestrator messages, agent delta updates, agent messages, and final result events.
                """
                if isinstance(event, MagenticOrchestratorMessageEvent):
                    st.write(f"**[Orchestrator - {event.kind}]**")
                    st.write(getattr(event.message, 'text', ''))
                    st.write("---")
                
                elif isinstance(event, MagenticAgentDeltaEvent):
                    agent_id = event.agent_id
                    
                    # Создаем новый контейнер для агента, если его еще нет
                    if agent_id not in agent_containers:
                        st.write(f"**[{agent_id}]**")
                        agent_containers[agent_id] = st.empty()
                        agent_accumulated_text[agent_id] = ""
                    
                    # Накапливаем текст
                    agent_accumulated_text[agent_id] += event.text
                    
                    # Обновляем контейнер с накопленным текстом
                    agent_containers[agent_id].markdown(agent_accumulated_text[agent_id])
                
                elif isinstance(event, MagenticAgentMessageEvent):
                    agent_id = event.agent_id
                    msg = event.message
                    
                    # Очищаем streaming контейнер
                    if agent_id in agent_containers:
                        agent_containers[agent_id].empty()
                        del agent_containers[agent_id]
                        del agent_accumulated_text[agent_id]
                    
                    # Выводим финальное сообщение
                    if msg is not None:
                        st.write(f"**[{agent_id} - Final]**")
                        st.markdown(msg.text or "")
                        st.write("---")
                
                elif isinstance(event, MagenticFinalResultEvent):
                    st.write("=" * 50)
                    st.write("**FINAL RESULT:**")
                    st.write("=" * 50)
                    if event.message is not None:
                        st.markdown(event.message.text)
                    st.write("=" * 50)
                
                # Только логируем события, не выводим пользователю
                logger.debug(f"Event: {type(event).__name__}")

            workflow = (
                MagenticBuilder()
                .participants(sql_builder = sql_builder_agent, sql_validator = sql_validtor_agent, data_extractor = data_extractor_agent,)
                .on_event(on_event, mode=MagenticCallbackMode.STREAMING)
                .with_standard_manager(
                    chat_client=OpenAIChatClient(**client_params),
                    max_round_count=10,
                    max_stall_count=3,
                    max_reset_count=2,
                )
                .build()
            )

            events = workflow.run_stream(prompt)

            logger.info(f"Events: {events}")
            async for event in events:
                logger.info(f"Event: {event}")
                    #st.session_state.messages.append(event.data)
            logger.info("Workflow completed")
                    

    if prompt := st.chat_input("Say something:"):
            # User message - simple dict (not an event)
            #st.session_state.messages.append({"role": "user", "content": prompt})
            
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                # Используем sync-over-async для Streamlit
                #nest_asyncio.apply()
                asyncio.run(run_workflow(prompt))
        

if __name__ == "__main__":
    main()
