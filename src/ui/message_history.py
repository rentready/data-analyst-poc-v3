"""Message history rendering for chat interface."""

import streamlit as st
from src.ui.event_renderer import EventRenderer

def render_chat_history():
    """Render the chat message history."""
    # Create EventRenderer instance for rendering
    event_renderer = EventRenderer()
    
    current_chat = st.empty()
    prev_agent_id = None
    prev_role = None
    
    for item in st.session_state.messages:
        # Only merge messages for agents (agent_id is not None), not for orchestrator (agent_id is None)
        should_create_new_chat = False
        
        if item["agent_id"] is not None:
            # For agents: merge if same agent_id and role
            if (prev_agent_id != item["agent_id"] or prev_role != item["role"]):
                should_create_new_chat = True
        else:
            # For orchestrator: always create new chat message (never merge)
            should_create_new_chat = True
        
        if should_create_new_chat:
            prev_role = item["role"]
            prev_agent_id = item["agent_id"]
            current_chat = st.chat_message(item["role"])

        content = item["event"] if "event" in item else item.get("content", None)
        if content is None:
            continue
        
        with current_chat:
            event_renderer.render(content)
            
            # Show elapsed time for assistant messages
            if item.get('role') == 'assistant' and 'elapsed_time' in item:
                elapsed = item['elapsed_time']
                agent_type = item.get('agent_id', 'workflow')
                if agent_type == 'quick_answer':
                    st.caption(f'⚡ Answered from context in {elapsed:.2f}s')
                else:
                    st.caption(f'🤖 Agent workflow completed in {elapsed:.2f}s')