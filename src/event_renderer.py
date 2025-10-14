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
    MagenticCallbackEvent,
    MagenticOrchestratorMessageEvent,
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
    """Renders run events to Streamlit UI."""
    
    @staticmethod
    def render(event: Union[MagenticCallbackEvent, 'RunStep', 'MessageDeltaChunk', 'ThreadRun']):
        """Render event to UI."""
        # Magentic events
        if isinstance(event, MagenticOrchestratorMessageEvent):
            logger.info(f"**[Orchestrator - {event.message}]**")
            logger.info(f"Role:{event.message.role}")
            logger.info(f"Author Name: {event.message.author_name}")
            logger.info(f"{event.message.message_id}")
            logger.info(f"{event.message.additional_properties}")
            logger.info(f"{event.message.raw_representation}")
            EventRenderer.render_orchestrator_message(event)
        
        elif isinstance(event, MagenticAgentDeltaEvent):
            EventRenderer.render_agent_delta(event)
        
        elif isinstance(event, MagenticAgentMessageEvent):
            EventRenderer.render_agent_message(event)
        
        elif isinstance(event, MagenticFinalResultEvent):
            EventRenderer.render_final_result(event)
        
        elif isinstance(event, ExecutorInvokedEvent):
            EventRenderer.render_executor_invoked(event)
        
        # Azure AI events (ThreadRun, RunStep, MessageDeltaChunk)
        elif isinstance(event, ThreadRun):
            EventRenderer.render_thread_run(event)
        
        elif isinstance(event, (RunStep, MessageDeltaChunk)):
            EventRenderer.render_runstep_event(event)
        
        else:
            logger.warning(f"Unknown event type: {type(event)}")
    
    @staticmethod
    def render_orchestrator_message(event: MagenticOrchestratorMessageEvent):
        """Render orchestrator message."""
        message_text = getattr(event.message, 'text', '')
        
        # Для инструкций - явно показываем, что это команда агентам
        if event.kind == "instruction":
            st.info(f"🎯 Assistants, please help with the following request:", icon=":material/question_mark:")
            st.write(message_text)
        
        # Для task_ledger - сворачиваем внутренний контекст
        elif event.kind == "task_ledger":
            # Извлекаем первую строку как заголовок или используем дефолтный
            first_line = message_text.split('\n')[0] if message_text else "Task context"
            preview = first_line[:80] + "..." if len(first_line) > 80 else first_line
            
            with st.expander(f"📋 **Internal context:** {preview}", expanded=False):
                st.markdown(message_text)
        
        else:
            # Другие типы (plan, facts, progress, etc.)
            st.write(f"**[Orchestrator - {event.kind}]**")
            st.write(message_text)
            st.write("---")
    
    @staticmethod
    def render_agent_delta(event: MagenticAgentDeltaEvent):
        """Render agent delta (streaming text) - requires container management from caller."""
        # This method is meant to be called from a streaming context
        # where the caller manages the text accumulation and container
        logger.debug(f"Agent delta from {event.agent_id}: {event.text}")
    
    @staticmethod
    def render_agent_message(event: MagenticAgentMessageEvent):
        """Render complete agent message."""
        st.write(event.message.text)
    
    @staticmethod
    def render_agent_final_message(agent_id: str, message_text: str):
        """Render agent's final message in collapsible format (auxiliary message)."""
        # Определяем превью (первые 100 символов)
        preview = message_text[:100] + "..." if len(message_text) > 100 else message_text
        
        # Сворачивающийся блок с превью
        with st.expander(f"💬 **{agent_id}** - {preview}", expanded=False):
            st.markdown(message_text)
    
    @staticmethod
    def render_final_result(event: MagenticFinalResultEvent):
        """Render final workflow result."""
        st.write("=" * 50)
        st.write("**FINAL RESULT:**")
        st.write("=" * 50)
        if event.message is not None:
            st.markdown(event.message.text)
        st.write("=" * 50)
    
    @staticmethod
    def render_executor_invoked(event: ExecutorInvokedEvent):
        """Render executor invoked event."""
        st.write(f"**[Executor Invoked - {event.executor_id}]**")
    
    @staticmethod
    def render_thread_run(run: ThreadRun):
        """Render ThreadRun event - agent taking on work."""
        # Получаем информацию о статусе
        status = run.status if hasattr(run, 'status') else None
        agent_id = run.agent_id if hasattr(run, 'agent_id') else "Unknown Agent"
        
        # Рендерим в зависимости от статуса
        if status == RunStatus.IN_PROGRESS or status == "in_progress":
            st.success(f"✅ **{agent_id}** has started working on the task")
        elif status == RunStatus.QUEUED or status == "queued":
            #st.info(f"⏳ **{agent_id}** is queued and waiting to start")
            pass;
        elif status == RunStatus.COMPLETED or status == "completed":
            st.success(f"✅ **{agent_id}** has completed the task")
        elif status == RunStatus.FAILED or status == "failed":
            error_msg = run.last_error.message if hasattr(run, 'last_error') and run.last_error else "Unknown error"
            st.error(f"❌ **{agent_id}** failed: {error_msg}")
    
    @staticmethod
    def render_runstep_event(event):
        """Render Azure AI RunStep or MessageDeltaChunk event."""
        try:
            # Handle MessageDeltaChunk (streaming text) - requires caller to manage containers
            if isinstance(event, MessageDeltaChunk):
                logger.debug("MessageDeltaChunk received - streaming handled externally")
                return
            
            # Handle RunStep
            if isinstance(event, RunStep):
                EventRenderer._render_runstep(event)
        except ImportError:
            logger.warning("Azure AI models not available for RunStep processing")
    
    @staticmethod
    def _render_runstep(run_step):
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
                        EventRenderer._render_tool_call_item(tc)
        except ImportError:
            logger.warning("Azure AI models not available")
    
    @staticmethod
    def _render_tool_call_item(tool_call):
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
                            EventRenderer._render_structured_output(parsed)
                        else:
                            with st.expander("📤 Output", expanded=True):
                                st.text(parsed)
                    else:
                        st.info("⏳ No output yet...")
        except ImportError:
            logger.warning("Azure AI models not available")
    
    @staticmethod
    def _render_structured_output(result):
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
    
    @staticmethod
    def render_approval_request(tool_calls, 
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
    
    @staticmethod
    def render_error(error_message: str, error_code: str = None):
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

