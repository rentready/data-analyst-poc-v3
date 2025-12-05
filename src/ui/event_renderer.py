"""Event renderer - handles UI display for run events."""

import streamlit as st
import json
import logging
from typing import Optional, Callable, Union

from azure.ai.agents.models import (
    RunStepType, RunStepStatus, RunStep, MessageDeltaChunk,
    RequiredMcpToolCall, RequiredFunctionToolCall, RunStepMcpToolCall,
    ThreadRun, RunStatus
)

# Magentic events from agent_framework
from agent_framework import (
    MagenticAgentDeltaEvent,
    MagenticAgentMessageEvent,
    MagenticFinalResultEvent,
    ExecutorInvokedEvent,
)

logger = logging.getLogger(__name__)


def parse_tool_output(output: Optional[str]) -> tuple[bool, any]:
    """
    Parse tool output - try JSON first, fallback to text.
    Returns: (is_json, parsed_data)
    """
    if not output:
        return False, None
    
    try:
        # Try to extract JSON after "TOOL RESULT:" marker
        if 'TOOL RESULT:' in output:
            json_part = output.split('TOOL RESULT:')[1].strip()
            result = json.loads(json_part)
            return True, result
        else:
            # Try direct JSON parse
            result = json.loads(output)
            return True, result
    except:
        # Return as text
        return False, output


class EventRenderer:
    """Renders run events to Streamlit UI - единая точка рендеринга."""
    
    def __init__(self):
        """Initialize event renderer with chat state tracking."""
        self._current_agent_id: Optional[str] = None
        self._current_role: Optional[str] = None
    
    def get_or_create_chat_message(self, role: str, agent_id: Optional[str] = None):
        """
        Get existing chat message or create new one.
        
        Args:
            role: Role of the message (e.g., "🤖", "assistant", "user")
            agent_id: Agent ID for agent messages (None for orchestrator)
            
        Returns:
            Chat message container
        """
        # For agents: reuse if same agent_id and role
        # For orchestrator: always create new (agent_id is None)
        should_create_new = False
        
        if agent_id is not None:
            # For agents: merge if same agent_id and role
            if (self._current_agent_id != agent_id or self._current_role != role):
                should_create_new = True
        else:
            # For orchestrator: always create new chat message
            should_create_new = True
        
        if should_create_new:
            self._current_role = role
            self._current_agent_id = agent_id
            st.session_state.current_chat = st.chat_message(role)
        
        return st.session_state.current_chat
    
    def reset(self):
        """Reset the event renderer state."""
        self._current_agent_id = None
        self._current_role = None
        st.session_state.current_chat = st.empty()
    
    # ===== Вспомогательные методы для управления контейнерами =====
    
    def create_message_container(self):
        """Создать новый контейнер для сообщения"""
        return st.session_state.current_chat.empty()
    
    def reset_message_container(self):
        """Сбросить контейнер сообщения"""
        self.reset()
    
    def render_agent_text(self, text: str, agent_id: str):
        """Отрендерить текст агента и сохранить в историю"""
        chat_container = self.get_or_create_chat_message("🤖", agent_id)
        with chat_container:
            self.render(text)
        st.session_state.messages.append({
            "role": "🤖",
            "content": text,
            "agent_id": agent_id
        })
    
    def render_agent_event(self, event, agent_id: str):
        """Отрендерить событие агента и сохранить в историю"""
        chat_container = self.get_or_create_chat_message("🤖", agent_id)
        with chat_container:
            self.render(event)
        st.session_state.messages.append({
            "role": "🤖",
            "event": event,
            "agent_id": agent_id
        })
    
    def render_orchestrator_event(self, event):
        """Отрендерить событие оркестратора и сохранить в историю"""
        chat_container = self.get_or_create_chat_message("assistant", None)
        with chat_container:
            self.render(event)
            st.session_state.messages.append({
                "role": "assistant",
                "event": event,
                "agent_id": None
            })
    
    @staticmethod
    def render_streaming_text(container, text: str):
        """Отрендерить потоковый текст в контейнер"""
        # Check if text looks like JSON and render it nicely
        if (text.strip().startswith('{') and text.strip().endswith('}')) or (text.strip().startswith('[') and text.strip().endswith(']')):
            try:
                parsed_json = json.loads(text.strip())
                container.json(parsed_json)
            except (json.JSONDecodeError, ValueError):
                # If JSON parsing fails, render as regular text
                container.write(text)
        else:
            container.write(text)
    
    # ===== Основной метод рендеринга =====
    
    def render(self, event: Union[MagenticAgentMessageEvent, 'RunStep', 'MessageDeltaChunk', 'ThreadRun']):
        """
        Render event to UI.
        
        Args:
            event: Event to render
        """
        
        # Magentic events
        if isinstance(event, MagenticAgentMessageEvent) and getattr(event, 'agent_name', '') == 'orchestrator':
            logger.info(f"**[Orchestrator - {event.message}]**")
            logger.info(f"Role:{event.message.role}")
            logger.info(f"Author Name: {event.message.author_name}")
            logger.info(f"{event.message.message_id}")
            logger.info(f"{event.message.additional_properties}")
            logger.info(f"{event.message.raw_representation}")
            self.render_orchestrator_message(event)
        
        elif isinstance(event, MagenticAgentDeltaEvent):
            self.render_agent_delta(event)
        
        elif isinstance(event, MagenticAgentMessageEvent):
            self.render_agent_message(event)
        
        elif isinstance(event, MagenticFinalResultEvent):
            self.render_final_result(event)
        
        elif isinstance(event, ExecutorInvokedEvent):
            self.render_executor_invoked(event)
        
        # Azure AI events (ThreadRun, RunStep, MessageDeltaChunk)
        elif isinstance(event, ThreadRun):
            self.render_thread_run(event)
        
        elif isinstance(event, (RunStep, MessageDeltaChunk)):
            self.render_runstep_event(event)
        elif isinstance(event, str):
            # Check if string looks like JSON and render it nicely
            text = event.strip()
            if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
                try:
                    parsed_json = json.loads(text)
                    st.json(parsed_json)
                except (json.JSONDecodeError, ValueError):
                    # If JSON parsing fails, render as regular text
                    st.write(event)
            else:
                st.write(event)
        else:
            logger.warning(f"Unknown event type: {type(event)}")
        
    
    def render_orchestrator_message(self, event: MagenticAgentMessageEvent):
        """Render orchestrator message."""
        message_text = getattr(event.message, 'text', '')
        
        # For instructions - explicitly show this is a command to agents
        if event.kind == "instruction":
            st.info(f"🎯 Assistants, please help with the following request:", icon=":material/question_mark:")
            st.write(message_text)
        
        # For task_ledger - collapse internal context
        elif event.kind == "task_ledger":
            st.info(f"📋 **Context**")
            st.markdown(message_text)
        
        else:
            # Other types (plan, facts, progress, etc.)
            st.write(f"**[Orchestrator - {event.kind}]**")
            st.write(message_text)
            st.write("---")
    
    def render_agent_delta(self, event: MagenticAgentDeltaEvent):
        """Render agent delta (streaming text) - requires container management from caller."""
        # This method is meant to be called from a streaming context
        # where the caller manages the text accumulation and container
        logger.debug(f"Agent delta from {event.agent_id}: {event.text}")
    
    def render_agent_message(self, event: MagenticAgentMessageEvent):
        """Render complete agent message."""
        st.write(event.message.text)
    
    def render_agent_final_message(self, agent_id: str, message_text: str):
        """Render agent's final message in collapsible format (auxiliary message)."""
        # Define preview (first 100 characters)
        preview = message_text[:100] + "..." if len(message_text) > 100 else message_text
        
        # Collapsible block with preview
        with st.expander(f"{preview}", expanded=False):
            st.markdown(message_text)
    
    def render_final_result(self, event: MagenticFinalResultEvent):
        """Render final workflow result."""
        st.info("**FINAL RESULT:**")
        if event.message is not None:
            st.markdown(event.message.text)
    
    def render_executor_invoked(self, event: ExecutorInvokedEvent):
        """Render executor invoked event."""
        st.write(f"**[Executor Invoked - {event.executor_id}]**")
    
    def render_thread_run(self, run: ThreadRun):
        """Render ThreadRun event - agent taking on work."""
        # Get status information
        status = run.status if hasattr(run, 'status') else None
        agent_id = run.agent_id if hasattr(run, 'agent_id') else "Unknown Agent"
        agent_name = run.agent_name if hasattr(run, 'agent_name') else agent_id
        # Render based on status
        if status == RunStatus.IN_PROGRESS or status == "in_progress":
            st.success(f"**{agent_name}** has started working on the task")
        elif status == RunStatus.QUEUED or status == "queued":
            #st.info(f"⏳ **{agent_id}** is queued and waiting to start")
            pass;
        elif status == RunStatus.COMPLETED or status == "completed":
            st.success(f"✅ **{agent_name}** has completed the task")
        elif status == RunStatus.FAILED or status == "failed":
            error_msg = run.last_error.message if hasattr(run, 'last_error') and run.last_error else "Unknown error"
            st.error(f"❌ **{agent_name}** failed: {error_msg}")
    
    def render_runstep_event(self, event):
        """Render Azure AI RunStep or MessageDeltaChunk event."""
        try:
            # Handle MessageDeltaChunk (streaming text) - requires caller to manage containers
            if isinstance(event, MessageDeltaChunk):
                logger.debug("MessageDeltaChunk received - streaming handled externally")
                return
            
            # Handle RunStep
            if isinstance(event, RunStep):
                self._render_runstep(event)
        except ImportError:
            logger.warning("Azure AI models not available for RunStep processing")
    
    def _render_runstep(self, run_step):
        """Render Azure AI RunStep."""
        try:
            # Skip MESSAGE_CREATION steps (handled separately by streaming)
            if run_step.type == RunStepType.MESSAGE_CREATION:
                return
            
            # Handle TOOL_CALLS
            if run_step.type != RunStepType.TOOL_CALLS:
                return
            
            if run_step.status == RunStepStatus.FAILED:
                st.error(f"{run_step}")
                return
            
            if hasattr(run_step, 'step_details'):
                details = run_step.step_details
                
                if hasattr(details, 'tool_calls') and details.tool_calls:
                    # Render each tool call with original design
                    for tc in details.tool_calls:
                        self._render_tool_call_item(tc)
        except ImportError:
            logger.warning("Azure AI models not available")
    
    def _render_tool_call_item(self, tool_call):
        """Render a single tool call from Azure AI RunStep with ORIGINAL design."""
        try:
            # Required MCP Tool Call (needs approval) - skip UI rendering here
            if isinstance(tool_call, RequiredMcpToolCall):
                return
            
            # Required Function Tool Call
            elif isinstance(tool_call, RequiredFunctionToolCall):
                return  # Not used in current implementation
            
            # Completed MCP Tool Call - USE ORIGINAL DESIGN
            elif isinstance(tool_call, RunStepMcpToolCall):
                # Determine status
                status = "completed"  # RunStepMcpToolCall means it's already completed
                
                # Tool header with status (ORIGINAL DESIGN)
                status_emoji = {
                    "in_progress": "🔄",
                    "completed": "✅",
                    "failed": "❌"
                }
                emoji = status_emoji.get(status, "❓")
                
                tool_label = tool_call.name
                if hasattr(tool_call, 'server_label') and tool_call.server_label:
                    tool_label = f"{tool_call.name} ({tool_call.server_label})"
                
                # USE st.status() - ORIGINAL DESIGN!
                with st.status(f"{emoji} {tool_label}"):
                    # Arguments (ORIGINAL DESIGN with expander)
                    if hasattr(tool_call, 'arguments') and tool_call.arguments:
                        with st.expander("📝 Arguments", expanded=False):
                            try:
                                if isinstance(tool_call.arguments, str):
                                    st.json(json.loads(tool_call.arguments))
                                else:
                                    st.json(tool_call.arguments)
                            except (json.JSONDecodeError, TypeError, AttributeError):
                                st.json(tool_call.arguments)
                    
                    # Output/Result (ORIGINAL DESIGN)
                    if hasattr(tool_call, 'output') and tool_call.output:
                        is_json, parsed = parse_tool_output(tool_call.output)
                        
                        if is_json:
                            self._render_structured_output(parsed)
                        else:
                            with st.expander("📤 Output", expanded=True):
                                st.text(parsed)
                    else:
                        st.info("⏳ No output yet...")
        except ImportError:
            logger.warning("Azure AI models not available")
    
    def _render_structured_output(self, result):
        """Render structured JSON output."""
        # Show success/error status
        if isinstance(result, dict):
            if result.get('success') is True:
                st.success("✅ Tool executed successfully")
                if 'count' in result:
                    st.info(f"📊 Found {result['count']} results")
            elif result.get('success') is False:
                st.error("❌ Tool execution failed")
                if 'error' in result:
                    st.error(f"**Error:** {result['error']}")
        
        # Always show raw data
        with st.expander("📊 Result Data", expanded=True):
            if isinstance(result, dict):
                st.json(result)
            else:
                st.markdown(str(result))
    
    def render_approval_request(self, tool_calls, 
                               on_approve: Callable = None, 
                               on_deny: Callable = None,
                               request_id: str = None):
        """Render tool approval UI with buttons."""
        st.warning("🔧 MCP Tool requires approval")
        
        try:
            for i, tool_call in enumerate(tool_calls):
                if isinstance(tool_call, RequiredMcpToolCall):
                    server_name = tool_call.mcp.server_name
                    tool_name = tool_call.mcp.name
                    
                    with st.expander(f"Tool: {tool_name} ({server_name})", expanded=True):
                        st.write(f"**Tool ID:** {tool_call.id}")
                        st.write(f"**Server:** {server_name}")
                        
                        if tool_call.mcp.arguments:
                            st.write("**Arguments:**")
                            try:
                                if isinstance(tool_call.mcp.arguments, str):
                                    st.json(json.loads(tool_call.mcp.arguments))
                                else:
                                    st.json(tool_call.mcp.arguments)
                            except (json.JSONDecodeError, TypeError):
                                st.code(str(tool_call.mcp.arguments))
            
            # Render approval buttons if callbacks provided
            if on_approve and on_deny and request_id:
                render_approval_buttons(request_id, on_approve, on_deny)
        except ImportError:
            logger.warning("Azure AI models not available for approval rendering")
    
    def render_error(self, error_message: str, error_code: str = None):
        """Render error event with helpful context."""
        st.error(f"❌ **Error occurred:** {error_message}")
        
        if error_code:
            st.caption(f"Error code: `{error_code}`")
        
        # Add helpful suggestions based on error type
        with st.expander("🔧 What can you do?", expanded=True):
            st.markdown("""
            **Options:**
            - **🔄 Retry**: Continue from where it failed (recommended)
            - **❌ Cancel**: Return to input mode to try a different approach
            
            **How retry works:**
            - The agent will continue from the previous context
            - No need to repeat your original request
            - The agent knows the full conversation history
            
            **Tips:**
            - If this is a temporary network issue, retry should work
            - For authentication errors, check your sign-in status
            - For tool errors, the issue might be with external services
            """)


def render_approval_buttons(request_id: str, 
                           on_approve: Callable, 
                           on_deny: Callable):
    """Render approval buttons separately (for callback handling)."""
    col1, col2 = st.columns(2)
    
    with col1:
        st.button(
            "✅ Approve",
            key=f"approve_{request_id}",
            on_click=on_approve,
            args=(request_id,)
        )
    
    with col2:
        st.button(
            "❌ Deny", 
            key=f"deny_{request_id}",
            on_click=on_deny,
            args=(request_id,)
        )


def render_error_buttons(on_retry: Callable, on_cancel: Callable):
    """Render error retry/cancel buttons."""
    col1, col2 = st.columns(2)
    
    with col1:
        st.button(
            "🔄 Retry",
            key="retry_button",
            on_click=on_retry
        )
    
    with col2:
        st.button(
            "❌ Cancel",
            key="cancel_button", 
            on_click=on_cancel
        )

