"""WorkflowBuilder for creating Magentic workflows with all agents."""

from agent_framework import (
    MagenticBuilder,
    MagenticCallbackMode,
    AgentRunContext
)
from src.agents.factory import AgentFactory
from src.agents.configs import FACTS_IDENTIFIER_CONFIG, SQL_BUILDER_CONFIG, DATA_EXTRACTOR_CONFIG, GLOSSARY_CONFIG
from src.agent_instructions import ORCHESTRATOR_INSTRUCTIONS
from src.workflow.orchestrator_handler import on_orchestrator_event
import streamlit as st
import logging

logger = logging.getLogger(__name__)

class WorkflowBuilder:
    """Builds Magentic workflow with all agents and configuration."""
    
    def __init__(self, agent_factory: AgentFactory, spinner_manager):
        """
        Initialize workflow builder.
        
        Args:
            agent_factory: Factory for creating agents
            spinner_manager: Spinner manager instance
        """
        self.agent_factory = agent_factory
        self.spinner_manager = spinner_manager
    
    async def build_workflow(self, agent_client, threads: dict, prompt: str):
        """
        Build complete Magentic workflow with all agents.
        
        Args:
            agent_client: Azure AI agent client
            threads: Dictionary of thread objects
            prompt: User prompt for facts identifier
            
        Returns:
            Built Magentic workflow
        """
        # Create all agents using factory
        facts_identifier_agent = self.agent_factory.create_agent(
            FACTS_IDENTIFIER_CONFIG, 
            threads["facts_identifier"].id, 
            prompt
        )
        
        sql_builder_agent = self.agent_factory.create_agent(
            SQL_BUILDER_CONFIG, 
            threads["sql_builder"].id
        )
        
        data_extractor_agent = self.agent_factory.create_agent(
            DATA_EXTRACTOR_CONFIG, 
            threads["data_extractor"].id
        )
        
        # Glossary agent needs custom instructions from secrets
        glossary_agent = self.agent_factory.create_agent(
            GLOSSARY_CONFIG, 
            threads["glossary"].id,
            custom_instructions=st.secrets["glossary"]["instructions"]
        )

        logger.info(f"Created agent {sql_builder_agent}")

        # Store threads in session state for persistence
        st.session_state.facts_identifier_thread = threads["facts_identifier"]
        st.session_state.sql_builder_thread = threads["sql_builder"]
        st.session_state.data_extractor_thread = threads["data_extractor"]
        st.session_state.glossary_thread = threads["glossary"]
        st.session_state.orchestrator_thread = threads["orchestrator"]

        # Build workflow
        workflow = (
            MagenticBuilder()
            .participants(
                glossary=glossary_agent,
                facts_identifier=facts_identifier_agent,
                sql_builder=sql_builder_agent,
                data_extractor=data_extractor_agent
            )
            .on_event(
                lambda event: on_orchestrator_event(event, self.spinner_manager), 
                mode=MagenticCallbackMode.STREAMING
            )
            .with_standard_manager(
                chat_client=agent_client,
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                max_round_count=15,
                max_stall_count=4,
                max_reset_count=2,
            )
            .build()
        )
        
        return workflow
