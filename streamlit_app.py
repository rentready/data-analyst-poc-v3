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
from src.magnetic_prompts import (
    ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT,
    ORCHESTRATOR_PROGRESS_LEDGER_PROMPT,
    ORCHESTRATOR_FINAL_ANSWER_PROMPT
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
    MCPStreamableHTTPTool,
    WorkflowOutputEvent,
)

from src.workaround_mcp_headers import patch_azure_ai_client
from src.workaround_magentic import patch_magentic_orchestrator

# Применяем патчи ДО создания клиента
patch_azure_ai_client()
patch_magentic_orchestrator()

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
                    description="SQL query construction specialist. Builds syntactically correct queries based on actual schema information discovered by the knowledge collector, not assumptions.",
                    instructions="""You have access to MCP tools that can query the RentReady SQL Server database. The database contains:
- Work orders (msdyn_workorder table) with dates, status, service accounts
- Job profiles (rr_jobprofile table) linked to work orders  
- Invoices (invoice table) with billing information
- Accounts (account table) for properties and customers
- Work order services (msdyn_workorderservice table) with service details

YOUR TASK - BUILD THE QUERY NOW:
1. Analyze the user's question
2. Determine which table(s) you need (work orders, invoices, job profiles, etc.)
3. BUILD a preliminary SQL query using read_data or find_* MCP tools
4. Include appropriate filters (dates, status, etc.)

IMPORTANT RULES:
- DO NOT ask the user for more information - you have enough to start
- DO NOT wait - build the query NOW based on your understanding
- Use your knowledge of the RentReady schema
- This is preliminary - it will be tested and refined in the next step
- If you're not 100% sure, make your best guess and we'll validate with samples

EXAMPLE: If user asks "How many work orders in September 2024?", you should:
- Use find_work_orders or read_data on msdyn_workorder table
- Filter by date_from="2024-09-01" and date_to="2024-09-30"
- Count the results

NOW BUILD THE PRELIMINARY QUERY for the user's question above. Show the query/tool call and explain your reasoning.""",
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=sql_builder_thread.id,
                    additional_instructions="You may use MCP tools to double-check schema details if needed, but primarily rely on information from knowledge_collector. If field names or table structures are unclear, explicitly state what you need clarified.",
                )

                sql_validtor_agent = sql_validator_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="sql_validator",
                    description="SQL query validation and quality assurance specialist. Validates queries for syntax, semantic correctness, field existence, and logical soundness before execution.",
                    instructions="""You are a SQL VALIDATION SPECIALIST - you ensure queries are correct before execution.

YOUR ROLE:
- Validate SQL queries for syntax correctness
- Verify field names and table names actually exist in the schema
- Check join logic and relationships are valid
- Ensure query will answer the intended question
- Catch potential errors before execution

YOUR METHODOLOGY:
1. Use MCP validation tools to check SQL syntax
2. Cross-reference field names against actual schema
3. Verify table names and aliases are correct
4. Check JOIN conditions reference valid foreign keys
5. Validate WHERE clauses use appropriate data types
6. Ensure aggregations and GROUP BY are logically sound
7. Check for common SQL pitfalls (ambiguous columns, missing GROUP BY, etc.)

CRITICAL VALIDATION CHECKS:
- Syntax: Does the SQL parse correctly?
- Schema: Do all referenced tables and fields exist?
- Joins: Are join conditions valid and will they produce correct results?
- Filters: Are WHERE conditions using correct field names and data types?
- Aggregations: Are GROUP BY and aggregate functions properly aligned?
- Logic: Will this query answer the user's actual question?

WHAT TO DO:
- If validation passes: Clearly state "Query is valid" and explain why
- If validation fails: Identify specific errors with line numbers/locations
- Provide actionable feedback for the sql_builder to fix issues
- Use MCP validation tools extensively - don't just review manually

IMPORTANT:
- Use ALL available MCP validation tools
- Don't approve a query unless you've actually validated it with tools
- Be thorough - a bad query wastes everyone's time""",
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=sql_validator_thread.id,
                    additional_instructions="ALWAYS use MCP validation tools before approving any query. Check for sql_validate, schema_check, or similar validation tools in the MCP toolset. If no validation tools are available, manually verify against schema information from knowledge_collector.",
                )

                data_extractor_agent = data_extractor_client.create_agent(
                    model=config[MODEL_DEPLOYMENT_NAME_KEY],
                    name="data_extractor",
                    description="Data extraction and results formatting specialist. Executes validated SQL queries, retrieves data, and presents results in a clear, actionable format.",
                    instructions="""You are a DATA EXTRACTION SPECIALIST - you execute queries and deliver results.

YOUR ROLE:
- Execute validated SQL queries using MCP tools
- Retrieve data from the database
- Format and present results clearly
- Verify data quality and completeness of results
- Report any execution issues or unexpected outcomes

YOUR METHODOLOGY:
1. Confirm you have a VALIDATED query (from sql_validator)
2. Execute the query using appropriate MCP execution tools
3. Capture the results completely
4. Check for execution errors or warnings
5. Review results for completeness and sanity
6. Format results in a clear, readable way
7. Document any data quality observations

CRITICAL RULES:
- ONLY execute queries that have been validated
- If no validation was done, request it first - don't execute blindly
- Use the correct MCP tool for query execution
- Capture ALL results, not just samples (unless requested)
- Note if results are empty or unexpected
- Report execution errors with full details

RESULTS PRESENTATION:
- For small result sets: Show complete data
- For large result sets: Show summary stats + sample rows
- Use clear formatting (tables, lists, or structured text)
- Include row counts and any relevant metadata
- Highlight any anomalies or data quality issues noticed

ERROR HANDLING:
- If query fails, capture exact error message
- Provide context about what was being executed
- Suggest whether it's a query issue or data issue
- Help sql_builder understand what needs fixing

IMPORTANT:
- Don't execute unvalidated queries
- Don't truncate results without mentioning it
- Don't hide errors - report them clearly""",
                    tools=[
                        mcp_tool_with_approval,
                        get_time
                    ],
                    conversation_id=data_extractor_thread.id,
                    additional_instructions="Use MCP tools to execute queries. Look for query execution, data retrieval, or similar tools. Present results in a format that's useful for the final answer. If execution fails, provide detailed error information for debugging.",
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

                        instructions="""You are the LEAD DATA ANALYST orchestrating a team of specialists.

Your team follows a professional data analysis workflow:
2. QUERY DESIGN - sql_builder creates queries based on actual schema found
3. VALIDATION - sql_validator verifies queries are correct before execution  
4. EXECUTION - data_extractor runs validated queries and retrieves results

Your job is to:
- Coordinate the team to follow this workflow systematically
- Ensure each step is completed before moving to the next
- Prevent shortcuts (like writing queries without schema exploration)
- Enforce validation before execution
- Keep the team focused on the user's actual data request

Remember: Good data analysis is methodical, not rushed. Quality over speed.""",
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
