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
        # Reset search config singletons to reload configuration
        from src.search_config import reset_singletons
        reset_singletons()
        
        # Log embeddings configuration for debugging
        try:
            emb_config = st.secrets.get("embeddings", {})
            logger.info("=" * 80)
            logger.info("EMBEDDINGS CONFIGURATION LOADED:")
            logger.info(f"  Model: {emb_config.get('model', 'NOT SET')}")
            logger.info(f"  API Base: {emb_config.get('api_base', 'NOT SET')}")
            logger.info(f"  Dimensions: {emb_config.get('dimensions', 'NOT SET')}")
            logger.info("=" * 80)
        except Exception as e:
            logger.warning(f"Could not log embeddings config: {e}")
        
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
        
        # Render Knowledge Base UI in sidebar
        with st.sidebar:
            st.markdown("---")
            try:
                from src.ui.search_kb_ui import render_knowledge_base_sidebar
                from src.search.indexer import DocumentIndexer
                from src.search_config import get_embeddings_generator
                
                # Get configuration from secrets
                search_endpoint = st.secrets["azure_search"]["endpoint"]
                index_name = st.secrets["azure_search"]["index_name"]
                api_key = st.secrets["azure_search"]["admin_key"]
                
                # Initialize embeddings and indexer
                embeddings = get_embeddings_generator()
                indexer = DocumentIndexer(
                    search_endpoint=search_endpoint,
                    index_name=index_name,
                    api_key=api_key,
                    embeddings_generator=embeddings
                )
                
                # Render KB UI
                render_knowledge_base_sidebar(indexer)
            except Exception as e:
                logger.warning(f"⚠️ Knowledge Base UI not available: {e}")
            
            # Conversation controls
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Clear", use_container_width=True, help="Clear conversation"):
                    st.session_state.messages = []
                    st.session_state.user_messages = []
                    st.session_state.workflow_cancelled = False
                    if 'executor_iterations' in st.session_state:
                        del st.session_state.executor_iterations
                    if 'reviewer_iterations' in st.session_state:
                        del st.session_state.reviewer_iterations
                    st.rerun()
            with col2:
                if st.button("🛑 Stop", use_container_width=True, type="primary", help="Stop current workflow"):
                    st.session_state.workflow_cancelled = True
                    logger.info("🛑 Workflow stop requested by user")
                    st.toast("⏹️ Stopping workflow...")
                    st.rerun()
        
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
    
    def _is_clarifying_question(self, prompt: str) -> bool:
        """Detect if the question is clarifying (asking about previous work)."""
        clarifying_keywords = [
            'как ты', 'как вы', 'покажи', 'повтори', 'еще раз', 'снова',
            'формул', 'запрос', 'sql', 'какой запрос', 'какая формула',
            'таблиц', 'посчитал', 'получил', 'нашел', 'использовал',
            'какой id', 'какое id', 'id было', 'какой был', 'какая была', 'какое было',
            'что ты', 'что вы', 'откуда', 'почему', 'объясни', 'расскажи как',
            'how did you', 'show me', 'what was', 'which', 'repeat', 'again',
            'formula', 'query', 'table', 'calculated', 'found', 'used',
            'what id', 'explain', 'why'
        ]
        prompt_lower = prompt.lower()
        has_keyword = any(keyword in prompt_lower for keyword in clarifying_keywords)
        word_count = len(prompt.split())
        is_short = word_count <= 10
        has_question_mark = '?' in prompt
        return has_keyword or (is_short and has_question_mark)
    
    async def _quick_answer_from_context(self, prompt: str) -> str:
        """Answer clarifying questions directly from conversation history."""
        if 'messages' not in st.session_state or len(st.session_state.messages) < 2:
            return None
        
        # Build context from last assistant messages
        assistant_msgs = [
            msg for msg in st.session_state.messages 
            if msg.get('role') == 'assistant' and msg.get('content')
        ]
        recent_assistant = assistant_msgs[-3:] if len(assistant_msgs) >= 3 else assistant_msgs
        context_text = '\n\n---\n\n'.join([msg.get('content', '')[:6000] for msg in recent_assistant])
        
        if not context_text:
            return None
        
        try:
            import openai
            client = openai.AzureOpenAI(
                api_key=self.openai_api_key,
                api_version='2024-02-01',
                azure_endpoint=self.openai_base_url
            )
            
            system_prompt = f"""You are a helpful assistant answering follow-up questions about previous data analysis.

CONTEXT FROM PREVIOUS ANALYSIS:
{context_text[:12000]}

RULES:
1. Answer the user's question based on the context above
2. If the context contains relevant information (formulas, queries, IDs, calculations), summarize it
3. If you can partially answer, do so and mention what's missing
4. ONLY say "Мне нужно выполнить новый анализ" if the context has ZERO relevant information
5. Be concise and direct. Use Russian for responses."""
            
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            
            answer = response.choices[0].message.content
            logger.info(f'Quick answer LLM response (first 100 chars): {answer[:100]}...')
            
            if 'нужно выполнить новый анализ' in answer.lower():
                return None
            
            return answer
            
        except Exception as e:
            logger.error(f'Error in quick answer: {e}')
            return None
    
    async def run_workflow(self, prompt: str) -> None:
        """Run the complete workflow for a user prompt."""
        import time
        start_time = time.time()
        
        # Check if this is a clarifying question
        if self._is_clarifying_question(prompt):
            logger.info(f'🔍 Detected clarifying question, attempting quick answer')
            self.spinner_manager.start('⚡ Analyzing conversation history...')
            
            quick_answer = await self._quick_answer_from_context(prompt)
            
            if quick_answer:
                elapsed = time.time() - start_time
                logger.info(f'✅ Quick answer in {elapsed:.1f}s')
                self.spinner_manager.stop()
                
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': quick_answer,
                    'agent_id': 'quick_context',
                    'elapsed_time': elapsed
                })
                
                with st.chat_message('assistant'):
                    st.markdown(quick_answer)
                    st.caption(f'⚡ Answered from context in **{elapsed:.1f}s**')
                
                return
            else:
                logger.info(f'⚠️ Quick answer not possible, using full workflow')
        
        self.spinner_manager.start('🤖 Planning your request...')
        
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
            
            # Create threads for two streamlined agents
            agent_names = ["data_planner", "data_extractor", "orchestrator"]
            threads = await thread_manager.get_all_threads(agent_names)
            
            # Create event handler (один раз для всех)
            event_handler = create_streamlit_event_handler(self.streaming_state, self.spinner_manager)
            
            # Create workflow builder
            workflow_builder = WorkflowBuilder(
                project_client=project_client,
                project_endpoint=self.azure_endpoint,
                credential=credential,
                model=self.model_name,
                middleware=[self._create_tool_calls_middleware(event_handler)],
                tools=[mcp_tool_with_approval, self.get_time],
                spinner_manager=self.spinner_manager,
                event_handler=event_handler
            )
            
            # Build workflow with all agents
            workflow = await workflow_builder.build_workflow(threads, prompt)
            
            # Run workflow with automatic retry on rate limit
            from src.utils.retry_helper import retry_on_rate_limit
            
            # Initialize cancellation flag
            st.session_state.workflow_cancelled = False
            
            async def _run_workflow_stream():
                async for event in workflow.run_stream(prompt):
                    # Check for cancellation
                    if st.session_state.get('workflow_cancelled', False):
                        logger.info("🛑 Workflow cancelled by user")
                        st.warning("⏹️ Workflow stopped by user request.")
                        return
                    await event_handler.handle_orchestrator_message(event)
            
            try:
                await retry_on_rate_limit(
                    _run_workflow_stream,
                    max_retries=5,
                    initial_delay=2.0,
                    max_delay=30.0
                )
            except Exception as e:
                logger.error(f"Workflow failed after retries: {e}")
                st.error(f"❌ Произошла ошибка: {str(e)[:200]}")
                st.info("💡 Попробуйте повторить запрос через несколько секунд.")
            finally:
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
