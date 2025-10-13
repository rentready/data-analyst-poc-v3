"""Ultra simple chat - refactored with event stream architecture."""

from tracemalloc import stop
import streamlit as st
import logging
import os
import asyncio
from src.config import get_config, get_mcp_config, setup_environment_variables, get_auth_config, get_openai_config
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

# Применяем патчи ДО создания клиента
patch_azure_ai_client()
patch_magentic_orchestrator()
patch_magentic_for_event_interception()

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

def get_time() -> str:
    """Get the current UTC time."""
    current_time = datetime.now(timezone.utc)
    return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."

async def on_runstep_event(agent_id: str, run_step) -> None:
    """
    Handle RunStep events from Azure AI agents.
    
    Args:
        agent_id: ID of the agent that generated the step
        run_step: RunStep object from Azure AI
    """
    import json
    
    try:
        from azure.ai.agents.models import (
            RequiredMcpToolCall,
            RequiredFunctionToolCall,
            RunStepMcpToolCall,
            RunStepType,
            RunStepStatus
        )

        if run_step.type != RunStepType.TOOL_CALLS or run_step.status == RunStepStatus.IN_PROGRESS:
            return

        st.write(f"**[{agent_id} - Step]** type={run_step.type}, status={run_step.status}")
        
        if hasattr(run_step, 'step_details'):
            details = run_step.step_details
            
            if hasattr(details, 'tool_calls') and details.tool_calls:
                st.write(f"  🔧 **Tool calls:** {len(details.tool_calls)} call(s)")
                
                for i, tc in enumerate(details.tool_calls):
                    if isinstance(tc, RequiredMcpToolCall):
                        st.write(f"  #{i+1} **MCP:** `{tc.mcp.server_name}.{tc.mcp.name}`")
                        # Arguments могут быть строкой или объектом
                        try:
                            if isinstance(tc.mcp.arguments, str):
                                st.json(json.loads(tc.mcp.arguments))
                            else:
                                st.json(tc.mcp.arguments)
                        except (json.JSONDecodeError, TypeError, AttributeError):
                            st.code(str(tc.mcp.arguments))
                    elif isinstance(tc, RequiredFunctionToolCall):
                        pass;
                    elif isinstance(tc, RunStepMcpToolCall):
                        st.write(f"  #{i+1} **MCP Result:** `{tc.server_label}.{tc.name}`")
                        if hasattr(tc, 'output') and tc.output:
                            # Пытаемся отобразить как JSON, если не получается - как текст
                            try:
                                if isinstance(tc.output, str):
                                    parsed = json.loads(tc.output)
                                    st.json(parsed)
                                else:
                                    st.json(tc.output)
                            except (json.JSONDecodeError, TypeError):
                                st.code(str(tc.output))
                    else:
                        pass;
                        #st.write(f"  #{i+1} **Tool:** {type(tc).__name__}")
        
        st.write("---")
    except ImportError:
        logger.warning("Azure AI models not available for RunStep processing")
    except Exception as e:
        logger.error(f"Error processing RunStep: {e}", exc_info=True)

def create_event_handler(agent_containers: dict, agent_accumulated_text: dict):
    """
    Create event handler for workflow events with agent-specific state tracking.
    
    Args:
        agent_containers: Dictionary to store Streamlit containers for each agent
        agent_accumulated_text: Dictionary to accumulate streaming text for each agent
    
    Returns:
        Async function that handles MagenticCallbackEvent instances
    """
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

        elif isinstance(event, ExecutorInvokedEvent):
            st.write(f"**[Executor Invoked - {event.executor_id}]**")
        
        # Только логируем события, не выводим пользователю
        logger.debug(f"Event: {type(event).__name__}")
    
    return on_event

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
        allowed_tools=mcp_config.get(MCP_ALLOWED_TOOLS_KEY, []),
        headers={"Authorization": f"Bearer {mcp_token}"},
    )

    async def run_workflow(prompt: str):
        # Prepare common client parameters
        client_params = {"model_id": model_name, "api_key": api_key}
        if base_url:
            client_params["base_url"] = base_url

        logger.info(f"MODEL: {config[MODEL_DEPLOYMENT_NAME_KEY]}")
        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=config[PROJ_ENDPOINT_KEY], credential=credential) as project_client,
        ):
            # Создаем отдельные threads для каждого агента
            sql_builder_thread = await project_client.agents.threads.create()
            sql_validator_thread = await project_client.agents.threads.create()
            data_extractor_thread = await project_client.agents.threads.create()
            
            logger.info(f"Created threads:")
            logger.info(f"  sql_builder: {sql_builder_thread.id}")
            logger.info(f"  sql_validator: {sql_validator_thread.id}")
            logger.info(f"  data_extractor: {data_extractor_thread.id}")
            
            # Создаем отдельные клиенты для каждого агента
            async with (
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=sql_builder_thread.id) as sql_builder_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=sql_validator_thread.id) as sql_validator_client,
                AzureAIAgentClient(project_client=project_client, model_deployment_name=config[MODEL_DEPLOYMENT_NAME_KEY], thread_id=data_extractor_thread.id) as data_extractor_client,
            ):
                sql_builder_agent = sql_builder_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="sql_builder",
                    description=SQL_BUILDER_DESCRIPTION,
                    instructions=SQL_BUILDER_INSTRUCTIONS,
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=sql_builder_thread.id,
                    additional_instructions=SQL_BUILDER_ADDITIONAL_INSTRUCTIONS,
                )

                sql_validtor_agent = sql_validator_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="sql_validator",
                    description=SQL_VALIDATOR_DESCRIPTION,
                    instructions=SQL_VALIDATOR_INSTRUCTIONS,
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=sql_validator_thread.id,
                    additional_instructions=SQL_VALIDATOR_ADDITIONAL_INSTRUCTIONS,
                )

                data_extractor_agent = data_extractor_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="data_extractor",
                    description=DATA_EXTRACTOR_DESCRIPTION,
                    instructions=DATA_EXTRACTOR_INSTRUCTIONS,
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=data_extractor_thread.id,
                    additional_instructions=DATA_EXTRACTOR_ADDITIONAL_INSTRUCTIONS,
                )

                # Словари для хранения контейнеров и накопленного текста для каждого агента
                agent_containers = {}
                agent_accumulated_text = {}
                
                # Создаем обработчик событий
                on_event = create_event_handler(agent_containers, agent_accumulated_text)
                
                # Устанавливаем глобальные callbacks для workaround модуля
                agent_executor_workaround.global_unified_callback = on_event
                agent_executor_workaround.global_runstep_callback = on_runstep_event

                workflow = (
                    MagenticBuilder()
                    .participants(sql_builder = sql_builder_agent, sql_validator = sql_validtor_agent, data_extractor = data_extractor_agent,)
                    .on_event(on_event, mode=MagenticCallbackMode.STREAMING)
                    .with_standard_manager(
                        chat_client=OpenAIChatClient(**client_params),
                        instructions=ORCHESTRATOR_INSTRUCTIONS,
                        task_ledger_facts_prompt=ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT,
                        task_ledger_plan_prompt=ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT,
                        task_ledger_full_prompt=ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT,
                        task_ledger_facts_update_prompt=ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT,
                        task_ledger_plan_update_prompt=ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT,
                        progress_ledger_prompt=ORCHESTRATOR_PROGRESS_LEDGER_PROMPT,
                        final_answer_prompt=ORCHESTRATOR_FINAL_ANSWER_PROMPT,

                        max_round_count=15,
                        max_stall_count=4,
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
