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
        from src.ui.event_renderer import EventRenderer
        self.event_renderer = EventRenderer()
    
    async def handle_runstep(self, event: Any) -> None:
        """Обработка RunStep событий (Azure AI)"""
        try:
            from azure.ai.agents.models import RunStepType, RunStepStatus
            from src.ui.event_renderer import EventRenderer
            
            if event.type == RunStepType.MESSAGE_CREATION:
                if event.status == RunStepStatus.IN_PROGRESS:
                    if not self.streaming_state.is_streaming(event.agent_id):
                        # Создаем контейнер и начинаем стриминг
                        container = self.event_renderer.create_message_container()
                        self.streaming_state.start_streaming(event.agent_id, container)
                        self.spinner_manager.stop()
                
                elif event.status == RunStepStatus.COMPLETED:
                    if self.streaming_state.is_streaming(event.agent_id):
                        final_text = self.streaming_state.end_streaming(event.agent_id)
                        if final_text:
                            self.event_renderer.render_agent_text(final_text, event.agent_id)
                return
            
            if event.type == RunStepType.TOOL_CALLS:
                if (hasattr(event, 'step_details') and 
                    hasattr(event.step_details, 'tool_calls') and 
                    event.step_details.tool_calls):
                    self.event_renderer.render_agent_event(event, event.agent_id)
                    self.spinner_manager.stop()
                else:
                    self.spinner_manager.start("Running tool...")
        
        except Exception as e:
            logger.error(f"Error handling RunStep event: {e}")
    
    async def handle_threadrun(self, event: Any) -> None:
        """Обработка ThreadRun событий (Azure AI)"""
        try:
            from azure.ai.agents.models import RunStatus
            from src.ui.event_renderer import EventRenderer
            
            if event.status == RunStatus.QUEUED:
                pass
            elif event.status == RunStatus.COMPLETED:
                self.event_renderer.reset_message_container()
                self.spinner_manager.start("Planning next steps...")
            else:
                self.event_renderer.render_agent_event(event, event.agent_id)
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
                    from src.ui.event_renderer import EventRenderer
                    self.event_renderer.render_streaming_text(container, accumulated_text)
        
        except Exception as e:
            logger.error(f"Error handling MessageDelta: {e}")
    
    async def handle_orchestrator_message(self, event: Any) -> None:
        """Обработка MagenticOrchestratorMessageEvent событий"""
        try:
            from src.ui.event_renderer import EventRenderer
            
            if event.kind == "user_task":
                self.spinner_manager.start("Analyzing your request...")
                return
            
            self.event_renderer.render_orchestrator_event(event)
            self.spinner_manager.start("Delegating to assistants...")
        
        except Exception as e:
            logger.error(f"Error handling OrchestratorMessage: {e}")
    
    async def handle_final_result(self, event: Any) -> None:
        """Обработка MagenticFinalResultEvent событий"""
        try:
            if event.message is not None:
                from src.ui.event_renderer import EventRenderer
                self.event_renderer.render_orchestrator_event(event)
        
        except Exception as e:
            logger.error(f"Error handling FinalResult: {e}")
    
    async def handle_workflow_event(self, event: Any) -> None:
        """Обработка событий нового workflow"""
        try:
            event_type = type(event).__name__
            logger.info(f"Handling workflow event: {event_type}")
            
            if event_type == "ExecutorInvokedEvent":
                await self._handle_executor_invoked(event)
            elif event_type == "ExecutorCompletedEvent":
                await self._handle_executor_completed(event)
            elif event_type == "WorkflowOutputEvent":
                await self._handle_workflow_output(event)
            elif event_type == "WorkflowStatusEvent":
                await self._handle_workflow_status(event)
            else:
                logger.info(f"Unhandled workflow event type: {event_type}")
        
        except Exception as e:
            logger.error(f"Error handling workflow event: {e}")
    
    async def _handle_executor_invoked(self, event: Any) -> None:
        """Handle ExecutorInvokedEvent"""
        try:
            executor_id = getattr(event, 'executor_id', 'unknown')
            logger.info(f"Executor invoked: {executor_id}")
            
            self.spinner_manager.stop()
            
            # Create container for message
            container = self.event_renderer.create_message_container()
            self.streaming_state.start_streaming(executor_id, container)
            
        except Exception as e:
            logger.error(f"Error handling executor invoked: {e}")
    
    async def _handle_executor_completed(self, event: Any) -> None:
        """Handle ExecutorCompletedEvent"""
        try:
            executor_id = getattr(event, 'executor_id', 'unknown')
            logger.info(f"Executor completed: {executor_id}")
            
            if self.streaming_state.is_streaming(executor_id):
                self.streaming_state.end_streaming(executor_id)
            
            self.spinner_manager.start("Processing result...")
            
        except Exception as e:
            logger.error(f"Error handling executor completed: {e}")
    
    async def _handle_workflow_output(self, event: Any) -> None:
        """Handle WorkflowOutputEvent"""
        try:
            logger.info("Workflow output received")
            
            if hasattr(event, 'data'):
                result = event.data
                logger.info(f"Output data type: {type(result).__name__}")
                
                # Handle result based on type
                if hasattr(result, 'analysis'):
                    # This is ExecutionResult
                    analysis = result.analysis
                    logger.info(f"Analysis length: {len(analysis) if analysis else 0}")
                    
                    self.spinner_manager.stop()
                    
                    # Create container for final result
                    container = self.event_renderer.create_message_container()
                    self.streaming_state.start_streaming("final", container)
                    
                    # Display result
                    result_text = f"""
## ✅ Analysis Complete

{analysis}
                    """
                    
                    self.event_renderer.render_agent_text(result_text, "final")
                    self.streaming_state.end_streaming("final")
                else:
                    logger.warning(f"Unknown result type: {type(result)}")
            
        except Exception as e:
            logger.error(f"Error handling workflow output: {e}")
    
    async def _handle_workflow_status(self, event: Any) -> None:
        """Handle WorkflowStatusEvent"""
        try:
            status = getattr(event, 'status', 'unknown')
            logger.info(f"Workflow status: {status}")
            
            if status == "completed":
                self.spinner_manager.stop()
                logger.info("Workflow completed successfully")
            
        except Exception as e:
            logger.error(f"Error handling workflow status: {e}")


def create_streamlit_event_handler(streaming_state, spinner_manager) -> StreamlitEventHandler:
    """Create event handler for Streamlit"""
    return StreamlitEventHandler(streaming_state, spinner_manager)
