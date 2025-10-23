"""Event handlers for decoupling middleware from UI rendering.

Принцип разделения:
- StreamlitEventHandler - обрабатывает события и управляет состоянием
- EventRenderer - отвечает за рендеринг UI
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class StreamlitEventHandler:
    """Обработчик событий - управляет состоянием и делегирует рендеринг в EventRenderer"""
    
    def __init__(self, streaming_state, spinner_manager):
        self.streaming_state = streaming_state
        self.spinner_manager = spinner_manager
    
    async def handle_runstep(self, event: Any) -> None:
        """Обработка RunStep событий (Azure AI)"""
        try:
            from azure.ai.agents.models import RunStepType, RunStepStatus
            from src.event_renderer import EventRenderer
            
            if event.type == RunStepType.MESSAGE_CREATION:
                if event.status == RunStepStatus.IN_PROGRESS:
                    if not self.streaming_state.is_streaming(event.agent_id):
                        # Создаем контейнер и начинаем стриминг
                        container = EventRenderer.create_message_container()
                        self.streaming_state.start_streaming(event.agent_id, container)
                        self.spinner_manager.stop()
                
                elif event.status == RunStepStatus.COMPLETED:
                    if self.streaming_state.is_streaming(event.agent_id):
                        final_text = self.streaming_state.end_streaming(event.agent_id)
                        if final_text:
                            EventRenderer.render_agent_text(final_text, event.agent_id)
                return
            
            if event.type == RunStepType.TOOL_CALLS:
                if (hasattr(event, 'step_details') and 
                    hasattr(event.step_details, 'tool_calls') and 
                    event.step_details.tool_calls):
                    EventRenderer.render_agent_event(event, event.agent_id)
                    self.spinner_manager.stop()
                else:
                    self.spinner_manager.start("Running tool...")
        
        except Exception as e:
            logger.error(f"Error handling RunStep event: {e}")
    
    async def handle_threadrun(self, event: Any) -> None:
        """Обработка ThreadRun событий (Azure AI)"""
        try:
            from azure.ai.agents.models import RunStatus
            from src.event_renderer import EventRenderer
            
            if event.status == RunStatus.QUEUED:
                pass
            elif event.status == RunStatus.COMPLETED:
                EventRenderer.reset_message_container()
                self.spinner_manager.start("Planning next steps...")
            else:
                EventRenderer.render_agent_event(event, event.agent_id)
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
                
                # Update container with accumulated text through EventRenderer
                accumulated_text = self.streaming_state.get_accumulated_text(event.agent_id)
                container = self.streaming_state.get_container(event.agent_id)
                if container:
                    from src.event_renderer import EventRenderer
                    EventRenderer.render_streaming_text(container, accumulated_text)
        
        except Exception as e:
            logger.error(f"Error handling MessageDelta: {e}")
    
    async def handle_orchestrator_message(self, event: Any) -> None:
        """Обработка MagenticOrchestratorMessageEvent событий"""
        try:
            from src.event_renderer import EventRenderer
            
            if event.kind == "user_task":
                self.spinner_manager.start("Analyzing your request...")
                return
            
            EventRenderer.render_orchestrator_event(event)
            self.spinner_manager.start("Delegating to assistants...")
        
        except Exception as e:
            logger.error(f"Error handling OrchestratorMessage: {e}")
    
    async def handle_final_result(self, event: Any) -> None:
        """Обработка MagenticFinalResultEvent событий"""
        try:
            if event.message is not None:
                from src.event_renderer import EventRenderer
                EventRenderer.render_orchestrator_event(event)
        
        except Exception as e:
            logger.error(f"Error handling FinalResult: {e}")


def create_streamlit_event_handler(streaming_state, spinner_manager) -> StreamlitEventHandler:
    """Создать обработчик событий для Streamlit"""
    return StreamlitEventHandler(streaming_state, spinner_manager)
