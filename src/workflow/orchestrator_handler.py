"""Workflow-level event handler for orchestrator events."""

import streamlit as st
from agent_framework import (
    MagenticCallbackEvent,
    MagenticOrchestratorMessageEvent,
    MagenticFinalResultEvent
)
from src.event_renderer import EventRenderer
from src.middleware.spinner_manager import SpinnerManager

async def on_orchestrator_event(event: MagenticCallbackEvent, spinner_manager: SpinnerManager) -> None:
    """
    Handle workflow-level events (orchestrator messages, final results).
    
    Args:
        event: Magentic callback event
        spinner_manager: Spinner manager instance
    """
    
    if isinstance(event, MagenticOrchestratorMessageEvent):
        
        if event.kind == "user_task":
            spinner_manager.start("Analyzing your request...")
            return
        
        # Render through EventRenderer
        with st.chat_message("assistant"):
            EventRenderer.render(event)
            spinner_manager.start("Delegating to assistants...")
            st.session_state.messages.append({"role": "assistant", "event": event, "agent_id": None})
    
    elif isinstance(event, MagenticFinalResultEvent):

        if event.message is not None:
            with st.chat_message("assistant"):
                EventRenderer.render(event)
                st.session_state.messages.append({"role": "assistant", "event": event, "agent_id": None})
