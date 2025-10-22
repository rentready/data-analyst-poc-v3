from agent_framework import AgentRunContext, AgentRunResponseUpdate
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Any
import streamlit as st
import logging

# Импорты для работы с событиями
try:
    from src.event_renderer import EventRenderer, SpinnerManager
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

async def run_step_tool_calls_middleware(
    context: AgentRunContext, 
    next: Callable[[AgentRunContext], Awaitable[None]],
    on_tool_calls: Callable = None
) -> None:
    """Middleware that intercepts RunStep tool_calls events."""

    agent_id = getattr(context.agent, 'id', None)
    agent_name = getattr(context.agent, 'name', None)
    
    # Execute the original agent logic
    await next(context)
    
    # Handle streaming response
    if context.result is not None and context.is_streaming:
        original_stream = context.result
        
        async def tool_calls_wrapper() -> AsyncIterable[AgentRunResponseUpdate]:
            async for chunk in original_stream:
                # Обрабатываем все типы событий как в старом методе
                if chunk.raw_representation:
                    chat_update = chunk.raw_representation
                    
                    if hasattr(chat_update, 'raw_representation'):
                        event = chat_update.raw_representation
                        
                        if hasattr(event, '__class__'):
                            event_class = event.__class__.__name__
                            logging.info(f"📦 Event type: {event_class}")
                            
                            # Обрабатываем RunStep события
                            if event_class == 'RunStep':
                                await handle_runstep_event(agent_id, event, on_tool_calls)
                            
                            # Обрабатываем ThreadRun события
                            elif event_class == 'ThreadRun':
                                await handle_threadrun_event(agent_name, event)
                            
                            # Обрабатываем MessageDeltaChunk события
                            elif event_class == 'MessageDeltaChunk':
                                await handle_message_delta_chunk(agent_id, event)
                            
                            # Обрабатываем ThreadMessage события
                            elif event_class == 'ThreadMessage':
                                await handle_thread_message(agent_id, event)
                
                yield chunk
        
        context.result = tool_calls_wrapper()

# Глобальные переменные для накопления текста (как в старом методе)
_message_containers = {}
_message_accumulated_text = {}

async def handle_runstep_event(agent_id: str, event, on_tool_calls: Callable = None):
    """Handle RunStep events - перенесено из старого метода."""
    try:
        from azure.ai.agents.models import RunStepType, RunStepStatus
        
        # Handle MESSAGE_CREATION
        if event.type == RunStepType.MESSAGE_CREATION:
            # IN_PROGRESS - create container for streaming
            if event.status == RunStepStatus.IN_PROGRESS:
                if agent_id not in _message_containers:
                    _message_containers[agent_id] = st.session_state.current_chat.empty()
                    _message_accumulated_text[agent_id] = ""
                    SpinnerManager.stop()
            
            # COMPLETED - remove container, display through renderer
            elif event.status == RunStepStatus.COMPLETED:
                if agent_id in _message_containers:
                    final_text = _message_accumulated_text.get(agent_id, "")
                    # Remove streaming container
                    _message_containers[agent_id].empty()
                    del _message_containers[agent_id]
                    del _message_accumulated_text[agent_id]
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
                SpinnerManager.stop()
                
                # Вызываем callback если он передан
                if on_tool_calls:
                    on_tool_calls(event, agent_id)
            else:
                with st.session_state.current_chat:
                    SpinnerManager.start("Running tool...")
        
    except Exception as e:
        logging.error(f"Error handling RunStep event: {e}")

async def handle_threadrun_event(agent_id: str, event):
    """Handle ThreadRun events - перенесено из старого метода."""
    try:
        from azure.ai.agents.models import RunStatus
        
        event.agent_id = agent_id
        if hasattr(event, 'status'):
            if event.status == RunStatus.QUEUED:
                pass
            elif event.status == RunStatus.COMPLETED:
                st.session_state.current_chat = st.empty()
                SpinnerManager.start("Planning next steps...")
            else:
                st.session_state.current_chat = st.chat_message("🤖")
                st.session_state.messages.append({"role": "🤖", "event": event, "agent_id": agent_id})
                with st.session_state.current_chat:
                    EventRenderer.render(event, auto_start_spinner="Processing...")
    except Exception as e:
        logging.error(f"Error handling ThreadRun event: {e}")

async def handle_message_delta_chunk(agent_id: str, event):
    """Handle MessageDeltaChunk events - перенесено из старого метода."""
    try:
        if agent_id in _message_containers:
            # Extract text from delta
            if hasattr(event, 'delta') and hasattr(event.delta, 'content'):
                for content in event.delta.content:
                    if hasattr(content, 'text') and hasattr(content.text, 'value'):
                        _message_accumulated_text[agent_id] += content.text.value
            
            # Update container
            _message_containers[agent_id].markdown(_message_accumulated_text[agent_id])
    except Exception as e:
        logging.error(f"Error handling MessageDeltaChunk: {e}")

async def handle_thread_message(agent_id: str, event):
    """Handle ThreadMessage events - перенесено из старого метода."""
    try:
        # ThreadMessage events are usually just passed through
        pass
    except Exception as e:
        logging.error(f"Error handling ThreadMessage: {e}")