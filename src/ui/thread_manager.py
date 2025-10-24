"""Thread lifecycle management for agents."""

import streamlit as st
from typing import Dict, Any, Optional

class ThreadManager:
    """Manages thread lifecycle for agents."""
    
    def __init__(self, project_client, vector_store_id: Optional[str] = None):
        """
        Initialize thread manager.
        
        Args:
            project_client: Azure AI Project client
            vector_store_id: Optional Vector Store ID for Knowledge Base agent
        """
        self.project_client = project_client
        self.vector_store_id = vector_store_id
        self._thread_cache = {}
    
    async def get_or_create_thread(self, agent_name: str):
        """
        Get existing thread or create new one for agent.
        
        Args:
            agent_name: Name of the agent (e.g., 'facts_identifier', 'sql_builder')
            
        Returns:
            Thread object
        """
        session_key = f"{agent_name}_thread"
        
        # Check if thread exists in session state
        if session_key in st.session_state and st.session_state[session_key] is not None:
            return st.session_state[session_key]
        
        # Create new thread with Vector Store for Knowledge Base agent
        if agent_name == "knowledge_base" and self.vector_store_id:
            thread = await self.project_client.agents.threads.create(
                tool_resources={
                    "file_search": {
                        "vector_store_ids": [self.vector_store_id]
                    }
                }
            )
        else:
            thread = await self.project_client.agents.threads.create()
        
        # Store in session state for persistence
        st.session_state[session_key] = thread
        
        return thread
    
    async def get_all_threads(self, agent_names: list[str]) -> Dict[str, Any]:
        """
        Get or create threads for multiple agents.
        
        Args:
            agent_names: List of agent names
            
        Returns:
            Dictionary mapping agent names to threads
        """
        threads = {}
        for agent_name in agent_names:
            threads[agent_name] = await self.get_or_create_thread(agent_name)
        return threads
