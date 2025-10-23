"""Message history rendering for chat interface."""

import streamlit as st
from src.event_renderer import EventRenderer

def render_chat_history():
    """Render the chat message history."""
    current_chat = st.empty()
    prev_agent_id = None
    prev_role = None
    
    for item in st.session_state.messages:
        if (prev_agent_id != item["agent_id"] or prev_role != item["role"]):
            prev_role = item["role"]
            prev_agent_id = item["agent_id"]
            current_chat = st.chat_message(item["role"])

        content = item["event"] if "event" in item else item.get("content", None)
        if content is None:
            continue
        
        with current_chat:
            EventRenderer.render(content)
