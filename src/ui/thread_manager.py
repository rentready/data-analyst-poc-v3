"""Thread lifecycle management for agents."""

import streamlit as st
from typing import Dict, Any
import uuid
import logging

logger = logging.getLogger(__name__)


class SimpleThread:
    """Simple thread object with id attribute."""
    def __init__(self, thread_id: str = None):
        # Generate unique thread ID
        # Azure AI requires thread_id to start with 'thread_'
        if thread_id:
            self.id = thread_id
        else:
            # Azure requires thread_ prefix
            self.id = f'thread_{uuid.uuid4()}'


class ThreadManager:
    """Manages thread lifecycle for agents."""
    
    def __init__(self, project_client):
        """
        Initialize thread manager.
        
        Args:
            project_client: Azure AI Project client (not used for thread creation)
        """
        self.project_client = project_client
        self._thread_cache = {}
    
    async def get_or_create_thread(self, agent_name: str):
        """
        Get existing thread or create new one for agent.
        
        Args:
            agent_name: Name of the agent (e.g., 'data_planner', 'data_extractor')
            
        Returns:
            SimpleThread object with id=None (agent framework will create thread automatically)
        """
        session_key = f"{agent_name}_thread"
        
        # Check if thread exists in session state
        if session_key in st.session_state and st.session_state[session_key] is not None:
            logger.info(f"Reusing existing thread for {agent_name}")
            return st.session_state[session_key]
        
        # Create thread object with id=None
        # This tells agent framework to create a new thread automatically
        thread = SimpleThread(thread_id=None)
        thread.id = None  # Explicitly set to None
        logger.info(f"Created thread object for {agent_name} with id=None (framework will create)")
        
        # Store in session state for persistence
        st.session_state[session_key] = thread
        
        return thread
    
    async def get_all_threads(self, agent_names: list[str]) -> Dict[str, Any]:
        """
        Get or create threads for multiple agents.
        
        Args:
            agent_names: List of agent names
            
        Returns:
            Dictionary mapping agent names to thread objects
        """
        threads = {}
        for agent_name in agent_names:
            threads[agent_name] = await self.get_or_create_thread(agent_name)
        return threads
