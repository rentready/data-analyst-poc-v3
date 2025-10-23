"""Event handlers for decoupling middleware from UI rendering."""

import logging
from typing import Any
import streamlit as st

logger = logging.getLogger(__name__)


class StreamlitEventHandler:
    """Обработчик событий для Streamlit UI - использует существующие события из библиотек"""
    
    def __init__(self, streaming_state, spinner_manager):
        self.streaming_state = streaming_state
        self.spinner_manager = spinner_manager
    
    async def handle_runstep(self, event: Any) -> None:
        """Обработка RunStep событий (Azure AI)"""
        try:
            from azure.ai.agents.models import RunStepType, RunStepStatus
            
            if event.type == RunStepType.MESSAGE_CREATION:
                if event.status == RunStepStatus.IN_PROGRESS:
                    if not self.streaming_state.is_streaming(event.agent_id):
                        container = st.session_state.current_chat.empty()
                        self.streaming_state.start_streaming(event.agent_id, container)
                        logger.info(f"Stopping spinner for agent {event.agent_id}")
                        self.spinner_manager.stop()
                
                elif event.status == RunStepStatus.COMPLETED:
                    if self.streaming_state.is_streaming(event.agent_id):
                        final_text = self.streaming_state.end_streaming(event.agent_id)
                        if final_text != "":
                            from src.event_renderer import EventRenderer
                            with st.session_state.current_chat:
                                EventRenderer.render(final_text)
                            
                            # Save to session state
                            st.session_state.messages.append({
                                "role": "🤖", 
                                "content": final_text, 
                                "agent_id": event.agent_id
                            })
                return
            
            if event.type == RunStepType.TOOL_CALLS:
                if (hasattr(event, 'step_details') and 
                    hasattr(event.step_details, 'tool_calls') and 
                    event.step_details.tool_calls):
                    
                    from src.event_renderer import EventRenderer
                    with st.session_state.current_chat:
                        EventRenderer.render(event)
                    st.session_state.messages.append({
                        "role": "🤖", 
                        "event": event, 
                        "agent_id": event.agent_id
                    })
                    self.spinner_manager.stop()
                else:
                    with st.session_state.current_chat:
                        self.spinner_manager.start("Running tool...")
        
        except Exception as e:
            logger.error(f"Error handling RunStep event: {e}")
    
    async def handle_threadrun(self, event: Any) -> None:
        """Обработка ThreadRun событий (Azure AI)"""
        try:
            from azure.ai.agents.models import RunStatus
            
            if event.status == RunStatus.QUEUED:
                pass
            elif event.status == RunStatus.COMPLETED:
                st.session_state.current_chat = st.empty()
                self.spinner_manager.start("Planning next steps...")
            else:
                from src.event_renderer import EventRenderer
                
                st.session_state.current_chat = st.chat_message("🤖")
                st.session_state.messages.append({
                    "role": "🤖", 
                    "event": event, 
                    "agent_id": event.agent_id
                })
                with st.session_state.current_chat:
                    EventRenderer.render(event)
                    self.spinner_manager.start("Processing...")
        
        except Exception as e:
            logger.error(f"Error handling ThreadRun event: {e}")
    
    async def handle_message_delta(self, event: Any) -> None:
        """Обработка MessageDeltaChunk событий (Azure AI)"""
        try:
            if self.streaming_state.is_streaming(event.agent_id):
                # Extract text from delta
                if hasattr(event, 'delta') and hasattr(event.delta, 'content'):
                    for content in event.delta.content:
                        if hasattr(content, 'text') and hasattr(content.text, 'value'):
                            self.streaming_state.append_text(event.agent_id, content.text.value)
                
                # Update container with accumulated text
                accumulated_text = self.streaming_state.get_accumulated_text(event.agent_id)
                self.streaming_state.update_container(event.agent_id, accumulated_text)
        
        except Exception as e:
            logger.error(f"Error handling MessageDelta: {e}")


def create_streamlit_event_handler(streaming_state, spinner_manager) -> StreamlitEventHandler:
    """Создать обработчик событий для Streamlit"""
    return StreamlitEventHandler(streaming_state, spinner_manager)
