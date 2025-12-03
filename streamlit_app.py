"""Data Analyst Chat V3 - Entry Point with WorkflowBuilderV3."""

import streamlit as st
import logging
import asyncio
import time
from typing import Optional
from src.ui.app import DataAnalystApp

st.set_page_config(page_title="Data Analyst Chat V3", page_icon="🤖")
logging.basicConfig(level=logging.INFO, force=True)

logger = logging.getLogger(__name__)

# DEBUG: Confirm this file is loaded
logger.info('🔴🔴🔴 streamlit_app.py V3 LOADED - with quick path 🔴🔴🔴')

# Keywords that indicate a clarifying question
CLARIFYING_KEYWORDS = [
    'как ты', 'как вы', 'покажи', 'повтори', 'еще раз', 'снова',
    'формул', 'запрос', 'sql', 'какой запрос', 'какая формула',
    'таблиц', 'посчитал', 'получил', 'нашел', 'использовал',
    'какой id', 'какое id', 'id было', 'какой был', 'какая была', 'какое было',
    'что ты', 'что вы', 'откуда', 'почему', 'объясни', 'расскажи как',
    'how did you', 'show me', 'what was', 'which', 'repeat', 'again',
    'formula', 'query', 'table', 'calculated', 'found', 'used',
    'what id', 'explain', 'why'
]


class DataAnalystAppV3(DataAnalystApp):
    """Main application class for Data Analyst Chat V3 - uses WorkflowBuilderV3."""
    
    def _is_clarifying_question(self, prompt: str) -> bool:
        """Check if the prompt is a clarifying question about previous work."""
        prompt_lower = prompt.lower()
        has_keyword = any(keyword in prompt_lower for keyword in CLARIFYING_KEYWORDS)
        word_count = len(prompt.split())
        is_short = word_count <= 15
        has_question_mark = '?' in prompt
        return has_keyword or (is_short and has_question_mark)
    
    async def _quick_answer_from_context(self, prompt: str) -> Optional[str]:
        """Try to answer from conversation context using a simple LLM call."""
        if 'messages' not in st.session_state or len(st.session_state.messages) < 2:
            return None
        
        # Get ALL messages from conversation history (assistant + tool results)
        # Filter to assistant messages - check 'assistant' and '🤖' roles
        assistant_msgs = []
        for msg in st.session_state.messages:
            role = msg.get('role', '')
            if role in ('assistant', '🤖'):
                # Get content from 'content' or 'event' field
                content = msg.get('content')
                event = msg.get('event')
                
                # If we have event object, try to extract text from it
                if event and not content:
                    # Magentic events have message.text structure
                    if hasattr(event, 'message') and hasattr(event.message, 'text'):
                        content = event.message.text
                    elif hasattr(event, 'text'):
                        content = event.text
                    # Also try contents for agent messages
                    elif hasattr(event, 'message') and hasattr(event.message, 'contents'):
                        # Extract text from contents list
                        texts = []
                        for c in event.message.contents:
                            if hasattr(c, 'text'):
                                texts.append(c.text)
                            elif hasattr(c, 'result'):
                                texts.append(str(c.result)[:2000])  # Limit tool results
                        content = '\n'.join(texts)
                    else:
                        # Fallback: convert to string
                        content = str(event)[:3000]
                
                if content and isinstance(content, str) and len(content) > 50:
                    assistant_msgs.append({'role': 'assistant', 'content': content})
        
        # Build context from ALL assistant messages, but limit total size to ~30K chars
        # (roughly 7500 tokens, leaving room for system prompt and response)
        MAX_CONTEXT_SIZE = 30000
        context_parts = []
        total_size = 0
        
        # Start from most recent messages (reverse order)
        for msg in reversed(assistant_msgs):
            content = msg.get('content', '')[:5000]  # Max 5K per message
            if total_size + len(content) > MAX_CONTEXT_SIZE:
                break
            context_parts.append(content)
            total_size += len(content)
        
        # Reverse back to chronological order
        context_parts.reverse()
        context_text = '\n\n---\n\n'.join(context_parts)
        
        if not context_text:
            logger.warning(f'⚠️ Quick answer: No context_text found (assistant_msgs count: {len(assistant_msgs)})')
            return None
        
        logger.info(f'📝 Quick answer: Found {len(assistant_msgs)} assistant messages, context_text length: {len(context_text)}')
        
        try:
            from openai import AzureOpenAI
            
            client = AzureOpenAI(
                api_key=st.secrets['open_ai']['api_key'],
                api_version='2024-02-01',
                azure_endpoint=st.secrets['open_ai']['base_url']
            )
            
            # More permissive system prompt
            system_prompt = """You are a helpful assistant answering follow-up questions about previous data analysis.

CONTEXT FROM PREVIOUS ANALYSIS:
{context}

RULES:
1. Answer the user's question based on the context above
2. If the context contains relevant information (formulas, queries, IDs, calculations), summarize it
3. If you can partially answer, do so and mention what's missing
4. ONLY say "I need to run new queries" if the context has ZERO relevant information
5. Be concise and direct. Use Russian for responses.""".format(context=context_text[:12000])
            
            model_name = st.secrets['open_ai'].get('model', 'gpt-4o')
            
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            
            answer = response.choices[0].message.content
            logger.info(f'Quick answer LLM response (first 200 chars): {answer[:200]}...')
            
            # Check if LLM says it cannot answer from context (in Russian or English)
            no_answer_phrases = [
                'need to run new queries',
                'нет информации',
                'нет данных', 
                'отсутствует',
                'не содержит',
                'нет ответа',
                'не могу ответить',
                'недостаточно информации',
                'нужно выполнить',
                'требуется дополнительный',
                'нужен новый запрос',
                'нужно получить',
                'уточните'
            ]
            
            answer_lower = answer.lower()
            if any(phrase in answer_lower for phrase in no_answer_phrases):
                logger.info(f'⚠️ Quick answer: LLM says info not in context, falling back to full workflow')
                return None
            
            return answer
            
        except Exception as e:
            logger.error(f'Error in quick answer: {e}')
            return None
    
    async def run_workflow(self, prompt: str) -> None:
        """Run the workflow using WorkflowBuilderV3."""
        # MARKER: This is DataAnalystAppV3.run_workflow
        logger.info('!!!!!!!!!! DataAnalystAppV3.run_workflow CALLED !!!!!!!!!!')
        print('!!!!!!!!!! DataAnalystAppV3.run_workflow CALLED !!!!!!!!!!', flush=True)
        
        start_time = time.time()
        
        # Debug: check quick path conditions (logger only - no print to avoid encoding issues)
        is_clarifying = self._is_clarifying_question(prompt)
        has_messages = 'messages' in st.session_state
        msg_count = len(st.session_state.messages) if has_messages else 0
        logger.info('=== QUICK PATH DEBUG ===')
        logger.info(f'is_clarifying: {is_clarifying}')
        logger.info(f'has_messages: {has_messages}')
        logger.info(f'msg_count: {msg_count}')
        logger.info('========================')
        
        # Check for quick path (clarifying questions)
        if is_clarifying and has_messages and msg_count >= 2:
            logger.info(f'⚡ Attempting quick answer from context for: {prompt}')
            self.spinner_manager.start('Checking context...')
            
            quick_answer = await self._quick_answer_from_context(prompt)
            
            if quick_answer:
                elapsed_time = time.time() - start_time
                logger.info(f'✅ Quick answer provided in {elapsed_time:.2f}s')
                
                # Add to messages with time tracking
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': quick_answer,
                    'agent_id': 'quick_answer',
                    'elapsed_time': elapsed_time
                })
                self.spinner_manager.stop()
                st.rerun()  # Force UI update
                return
            else:
                logger.info('⚠️ Quick path failed (LLM said needs new queries), falling back to full workflow')
        
        self.spinner_manager.start("Creating analysis plan...")
        
        # Initialize user messages collection if not exists
        if "user_messages" not in st.session_state:
            st.session_state.user_messages = []
        
        # Reset iteration counters for new conversation (if this is first message)
        if not st.session_state.user_messages:
            st.session_state.executor_iterations = 0
            st.session_state.reviewer_iterations = 0
            logger.info("Starting new conversation - resetting iteration counters")
        
        # Add current prompt to collection if it's new
        if not st.session_state.user_messages or st.session_state.user_messages[-1] != prompt:
            st.session_state.user_messages.append(prompt)
        
        # Combine all user messages
        if len(st.session_state.user_messages) > 1:
            messages_text = "\n\n".join([
                f"User message {i+1}: {msg}" 
                for i, msg in enumerate(st.session_state.user_messages)
            ])
            combined_prompt = f"User conversation history:\n{messages_text}"
            logger.info(f"Combining {len(st.session_state.user_messages)} user messages")
        else:
            combined_prompt = prompt
            logger.info(f"Using single message only")
        
        # Get Azure configuration
        try:
            self.azure_endpoint = st.secrets["azure_ai_foundry"]["proj_endpoint"]
            self.model_name = st.secrets["azure_ai_foundry"]["model_deployment_name"]
        except KeyError:
            st.error("❌ Please configure your Azure AI Foundry settings in Streamlit secrets.")
            return
        
        # Initialize Cosmos DB search tool
        cosmosdb_search_tool = None
        try:
            from src.search_config import get_cosmosdb_search_client
            from src.tools.search_cosmosdb_knowledge_base import CosmosDBKnowledgeBaseSearchTool
            
            cosmosdb_client = get_cosmosdb_search_client()
            cosmosdb_search_tool = CosmosDBKnowledgeBaseSearchTool(cosmosdb_client)
            logger.info("✅ Cosmos DB search tool initialized")
        except Exception as e:
            logger.warning(f"⚠️ Cosmos DB search tool not available: {e}")
        
        # Use Azure AI Project client
        from azure.identity.aio import DefaultAzureCredential
        from azure.ai.projects.aio import AIProjectClient
        from src.ui.thread_manager import ThreadManager
        from src.workflow.builder import WorkflowBuilder

        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=self.azure_endpoint, credential=credential) as project_client,
        ):
            # Create thread manager
            thread_manager = ThreadManager(project_client)
            
            # Create threads for agents (orchestrator, data_planner, data_extractor)
            agent_names = ["orchestrator", "data_planner", "data_extractor"]
            threads = await thread_manager.get_all_threads(agent_names)
            
            # Create event handler
            from src.ui.event_handler import create_streamlit_event_handler
            event_handler = create_streamlit_event_handler(self.streaming_state, self.spinner_manager)
            
            # Create middleware
            middleware = [self._create_tool_calls_middleware(event_handler)]
            
            # Prepare MCP configuration
            mcp_config = None
            try:
                mcp_config = {
                    "url": st.secrets["mcp"]["mcp_server_url"],
                    "client_id": st.secrets["mcp"]["mcp_client_id"],
                    "client_secret": st.secrets["mcp"]["mcp_client_secret"],
                    "tenant_id": st.secrets["env"]["AZURE_TENANT_ID"],
                    "allowed_tools": st.secrets["mcp"].get("allowed_tools", [])
                }
            except KeyError:
                logger.warning("⚠️ MCP configuration not found - MCP tool will not be available")
            
            # Get vector store ID
            vector_store_id = None
            try:
                vector_store_id = st.secrets['vector_store_id']
            except KeyError:
                logger.warning("⚠️ Vector store ID not found - knowledge base tool will not be available")
            
            # Create MCP tools
            mcp_tools = []
            if mcp_config:
                try:
                    from src.credentials import get_mcp_token_sync
                    from agent_framework import HostedMCPTool
                    
                    mcp_token = get_mcp_token_sync({
                        "mcp_client_id": mcp_config["client_id"],
                        "mcp_client_secret": mcp_config["client_secret"],
                        "AZURE_TENANT_ID": mcp_config["tenant_id"]
                    })
                    
                    mcp_tool = HostedMCPTool(
                        name="rentready_mcp",
                        description="Rent Ready MCP tool",
                        url=mcp_config["url"],
                        approval_mode="never_require",
                        allowed_tools=mcp_config.get("allowed_tools", []),
                        headers={"Authorization": f"Bearer {mcp_token}"} if mcp_token else {},
                    )
                    
                    mcp_tools.append(mcp_tool)
                    logger.info(f"✅ MCP tool created successfully")
                    
                except Exception as e:
                    logger.error(f"❌ Error creating MCP tool: {e}")
            
            # Create workflow builder
            workflow_builder = WorkflowBuilder(
                project_client=project_client,
                project_endpoint=self.azure_endpoint,
                credential=credential,
                model=self.model_name,
                middleware=middleware,
                tools=mcp_tools,
                spinner_manager=self.spinner_manager,
                event_handler=event_handler,
                cosmosdb_search_tool=cosmosdb_search_tool
            )
            
            try:
                # Build and run the workflow with combined prompt
                workflow = await workflow_builder.build_workflow(threads, combined_prompt)
                
                # Run workflow with the prompt (not lambda)
                result = await workflow.run(combined_prompt)
                
                # Track elapsed time for full workflow
                elapsed_time = time.time() - start_time
                logger.info(f'Full workflow completed in {elapsed_time:.2f}s')
                
                # Update last message with time tracking
                if st.session_state.messages:
                    last_msg = st.session_state.messages[-1]
                    if last_msg.get('role') == 'assistant':
                        last_msg['agent_id'] = 'workflow'
                        last_msg['elapsed_time'] = elapsed_time
                    
            except Exception as e:
                logger.error(f"Error running workflow: {e}", exc_info=True)
                st.error(f"❌ Error running workflow: {str(e)}")
            finally:
                self.spinner_manager.stop()


def main():
    """Main entry point for the application."""
    app = DataAnalystAppV3()
    app.run()
        

if __name__ == "__main__":
    main()

