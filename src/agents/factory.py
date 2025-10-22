"""Factory for creating agents with consistent configuration."""

from typing import List, Callable, Any
from .configs import AgentConfig

class AgentFactory:
    """Factory for creating agents with consistent configuration."""
    
    def __init__(self, agent_client, model: str, middleware: List[Callable], tools: List[Any]):
        """
        Initialize factory with common agent parameters.
        
        Args:
            agent_client: Azure AI agent client
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of tools available to agents
        """
        self.agent_client = agent_client
        self.model = model
        self.middleware = middleware
        self.tools = tools
    
    def create_agent(self, config: AgentConfig, thread_id: str, prompt: str = None, custom_instructions: str = None):
        """
        Create agent with given configuration.
        
        Args:
            config: Agent configuration
            thread_id: Thread ID for conversation
            prompt: Optional prompt to format into instructions
            custom_instructions: Optional custom instructions (overrides config)
            
        Returns:
            Created agent instance
        """
        # Use custom instructions if provided, otherwise use config instructions
        instructions = custom_instructions if custom_instructions else config.instructions
        
        # Format instructions with prompt if needed
        if prompt and "{prompt}" in instructions:
            instructions = instructions.format(prompt=prompt)
        
        # Create agent with configuration
        agent = self.agent_client.create_agent(
            model=self.model,
            name=config.name,
            description=config.description,
            instructions=instructions,
            middleware=self.middleware,
            tools=self.tools,
            conversation_id=thread_id,
            temperature=config.temperature,
            additional_instructions=config.additional_instructions
        )
        
        # Add user field if specified in config
        if config.user:
            agent.user = config.user
            
        return agent
