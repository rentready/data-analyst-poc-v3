"""Manages streaming state for agent messages without global variables."""

from typing import Dict, Any, Optional

class StreamingStateManager:
    """Manages message containers and accumulated text for streaming without global state."""
    
    def __init__(self):
        """Initialize streaming state manager."""
        self._containers: Dict[str, Any] = {}
        self._accumulated_text: Dict[str, str] = {}
    
    def start_streaming(self, agent_id: str, container) -> None:
        """
        Start streaming for agent.
        
        Args:
            agent_id: Unique identifier for the agent
            container: Streamlit container for displaying streaming text
        """
        self._containers[agent_id] = container
        self._accumulated_text[agent_id] = ""
    
    def append_text(self, agent_id: str, text: str) -> None:
        """
        Append text to streaming buffer.
        
        Args:
            agent_id: Unique identifier for the agent
            text: Text to append
        """
        if agent_id in self._accumulated_text:
            self._accumulated_text[agent_id] += text
    
    def get_accumulated_text(self, agent_id: str) -> str:
        """
        Get accumulated text for agent.
        
        Args:
            agent_id: Unique identifier for the agent
            
        Returns:
            Accumulated text for the agent
        """
        return self._accumulated_text.get(agent_id, "")
    
    def get_container(self, agent_id: str) -> Optional[Any]:
        """
        Get container for agent.
        
        Args:
            agent_id: Unique identifier for the agent
            
        Returns:
            Container for the agent or None if not found
        """
        return self._containers.get(agent_id)
    
    def update_container(self, agent_id: str, content: str) -> None:
        """
        Update container with current content.
        Note: Actual rendering is delegated to EventRenderer.
        
        Args:
            agent_id: Unique identifier for the agent
            content: Content to display in container
        """
        # Just store the content, rendering is handled by EventRenderer
        # This method is kept for compatibility but does not render
        pass
    
    def end_streaming(self, agent_id: str) -> str:
        """
        End streaming and return final text.
        
        Args:
            agent_id: Unique identifier for the agent
            
        Returns:
            Final accumulated text
        """
        final_text = self._accumulated_text.get(agent_id, "")
        
        # Clean up state
        if agent_id in self._containers:
            del self._containers[agent_id]
        if agent_id in self._accumulated_text:
            del self._accumulated_text[agent_id]
            
        return final_text
    
    def is_streaming(self, agent_id: str) -> bool:
        """
        Check if agent is currently streaming.
        
        Args:
            agent_id: Unique identifier for the agent
            
        Returns:
            True if agent is streaming, False otherwise
        """
        return agent_id in self._containers
    
    def clear_all(self) -> None:
        """Clear all streaming state."""
        self._containers.clear()
        self._accumulated_text.clear()
