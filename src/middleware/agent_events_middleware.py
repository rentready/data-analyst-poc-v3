"""Middleware for agent-level events (RunStep, ThreadRun, MessageDeltaChunk)."""

from agent_framework import AgentRunContext, AgentRunResponseUpdate
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Any
import streamlit as st
import logging

# Импорты для работы с событиями
try:
    from src.event_renderer import EventRenderer
    from src.middleware.spinner_manager import SpinnerManager
    from src.middleware.streaming_state import StreamingStateManager
except ImportError:
    # Fallback если модули недоступны
    class EventRenderer:
        @staticmethod
        def render(event, auto_start_spinner=None):
            st.write(f"Event: {type(event).__name__}")
    
    class SpinnerManager:
        @staticmethod
        def start(message):
            st.write(f"🔄 {message}")
        
        @staticmethod
        def stop():
            pass
    
    class StreamingStateManager:
        def __init__(self):
            self._containers = {}
            self._accumulated_text = {}
        
        def start_streaming(self, agent_id, container):
            self._containers[agent_id] = container
            self._accumulated_text[agent_id] = ""
        
        def append_text(self, agent_id, text):
            if agent_id in self._accumulated_text:
                self._accumulated_text[agent_id] += text
        
        def get_accumulated_text(self, agent_id):
            return self._accumulated_text.get(agent_id, "")
        
        def get_container(self, agent_id):
            return self._containers.get(agent_id)
        
        def update_container(self, agent_id, content):
            container = self.get_container(agent_id)
            if container:
                container.markdown(content)
        
        def end_streaming(self, agent_id):
            final_text = self._accumulated_text.get(agent_id, "")
            if agent_id in self._containers:
                del self._containers[agent_id]
            if agent_id in self._accumulated_text:
                del self._accumulated_text[agent_id]
            return final_text
        
        def is_streaming(self, agent_id):
            return agent_id in self._containers

async def agent_events_middleware(
    context: AgentRunContext, 
    next: Callable[[AgentRunContext], Awaitable[None]],
    streaming_state: StreamingStateManager,
    spinner_manager: SpinnerManager,
    on_tool_calls: Callable = None
) -> None:
    """
    Middleware that intercepts agent-level events for real-time rendering.
    
    Args:
        context: Agent run context
        next: Next middleware in chain
        streaming_state: Streaming state manager
        spinner_manager: Spinner manager
        on_tool_calls: Optional callback for tool calls
    """
    agent_id = getattr(context.agent, 'id', None)
    agent_name = getattr(context.agent, 'name', None)
    
    # Execute the original agent logic
    await next(context)
    
    # Handle streaming response
    if context.result is not None and context.is_streaming:
        original_stream = context.result
        
        async def tool_calls_wrapper() -> AsyncIterable[AgentRunResponseUpdate]:
            async for chunk in original_stream:
                # Обрабатываем все типы событий
                if chunk.raw_representation:
                    chat_update = chunk.raw_representation
                    
                    if hasattr(chat_update, 'raw_representation'):
                        event = chat_update.raw_representation
                        
                        if hasattr(event, '__class__'):
                            event_class = event.__class__.__name__
                            logging.info(f"📦 Event type: {event_class}")
                            
                            # Обрабатываем RunStep события
                            if event_class == 'RunStep':
                                await handle_runstep_event(agent_id, event, streaming_state, spinner_manager, on_tool_calls)
                            
                            # Обрабатываем ThreadRun события
                            elif event_class == 'ThreadRun':
                                await handle_threadrun_event(agent_name, event, spinner_manager)
                            
                            # Обрабатываем MessageDeltaChunk события
                            elif event_class == 'MessageDeltaChunk':
                                await handle_message_delta_chunk(agent_id, event, streaming_state)
                            
                            # Обрабатываем ThreadMessage события
                            elif event_class == 'ThreadMessage':
                                await handle_thread_message(agent_id, event)
                
                yield chunk
        
        context.result = tool_calls_wrapper()

async def handle_runstep_event(agent_id: str, event, streaming_state: StreamingStateManager, spinner_manager: SpinnerManager, on_tool_calls: Callable = None):
    """Handle RunStep events with streaming state manager."""
    try:
        from azure.ai.agents.models import RunStepType, RunStepStatus
        
        # Handle MESSAGE_CREATION
        if event.type == RunStepType.MESSAGE_CREATION:
            # IN_PROGRESS - create container for streaming
            if event.status == RunStepStatus.IN_PROGRESS:
                if not streaming_state.is_streaming(agent_id):
                    container = st.session_state.current_chat.empty()
                    streaming_state.start_streaming(agent_id, container)
                    logging.info(f"Stopping spinner for agent {agent_id}")
                    spinner_manager.stop()
            
            # COMPLETED - remove container, display through renderer
            elif event.status == RunStepStatus.COMPLETED:
                if streaming_state.is_streaming(agent_id):
                    final_text = streaming_state.end_streaming(agent_id)
                    if final_text != "":
                        with st.session_state.current_chat:
                            EventRenderer.render(final_text)
                        
                        # Save only text content for session persistence
                        st.session_state.messages.append({"role": "🤖", "content": final_text, "agent_id": agent_id})
            return

        # Handle TOOL_CALLS
        if event.type == RunStepType.TOOL_CALLS:
            if (hasattr(event, 'step_details') and 
                hasattr(event.step_details, 'tool_calls') and 
                event.step_details.tool_calls):

                with st.session_state.current_chat:
                    EventRenderer.render(event)
                st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
                spinner_manager.stop()
                
                # Вызываем callback если он передан
                if on_tool_calls:
                    on_tool_calls(event, agent_id)
            else:
                with st.session_state.current_chat:
                    spinner_manager.start("Running tool...")
        
    except Exception as e:
        logging.error(f"Error handling RunStep event: {e}")

async def handle_threadrun_event(agent_id: str, event, spinner_manager: SpinnerManager):
    """Handle ThreadRun events."""
    try:
        from azure.ai.agents.models import RunStatus
        
        event.agent_id = agent_id
        if hasattr(event, 'status'):
            if event.status == RunStatus.QUEUED:
                pass
            elif event.status == RunStatus.COMPLETED:
                st.session_state.current_chat = st.empty()
                spinner_manager.start("Planning next steps...")
            else:
                st.session_state.current_chat = st.chat_message("🤖")
                st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
                with st.session_state.current_chat:
                    EventRenderer.render(event)
                    spinner_manager.start("Processing...")
    except Exception as e:
        logging.error(f"Error handling ThreadRun event: {e}")

async def handle_message_delta_chunk(agent_id: str, event, streaming_state: StreamingStateManager):
    """Handle MessageDeltaChunk events with streaming state manager."""
    try:
        if streaming_state.is_streaming(agent_id):
            # Extract text from delta
            if hasattr(event, 'delta') and hasattr(event.delta, 'content'):
                for content in event.delta.content:
                    if hasattr(content, 'text') and hasattr(content.text, 'value'):
                        streaming_state.append_text(agent_id, content.text.value)
            
            # Update container with accumulated text
            accumulated_text = streaming_state.get_accumulated_text(agent_id)
            streaming_state.update_container(agent_id, accumulated_text)
    except Exception as e:
        logging.error(f"Error handling MessageDeltaChunk: {e}")

async def handle_thread_message(agent_id: str, event):
    """Handle ThreadMessage events."""
    try:
        # ThreadMessage events are usually just passed through
        pass
    except Exception as e:
        logging.error(f"Error handling ThreadMessage: {e}")
