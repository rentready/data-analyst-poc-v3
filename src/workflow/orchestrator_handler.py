"""Workflow-level event handler for orchestrator events - now uses unified event system."""

from agent_framework import (
    MagenticCallbackEvent,
    MagenticOrchestratorMessageEvent,
    MagenticFinalResultEvent
)

async def on_orchestrator_event(event: MagenticCallbackEvent, event_handler) -> None:
    """
    Handle workflow-level events (orchestrator messages, final results) via unified event handler.
    
    Args:
        event: Magentic callback event
        event_handler: Unified event handler instance
    """
    
    if isinstance(event, MagenticOrchestratorMessageEvent):
        await event_handler.handle_orchestrator_message(event)
    
    elif isinstance(event, MagenticFinalResultEvent):
        await event_handler.handle_final_result(event)
