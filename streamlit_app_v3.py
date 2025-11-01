"""Data Analyst Chat V3 - Entry Point with WorkflowBuilderV3."""

import streamlit as st
import logging
import asyncio
from src.ui.app import DataAnalystApp

st.set_page_config(page_title="Data Analyst Chat V3", page_icon="🤖")
logging.basicConfig(level=logging.INFO, force=True)

logger = logging.getLogger(__name__)


class DataAnalystAppV3(DataAnalystApp):
    """Main application class for Data Analyst Chat V3 - uses WorkflowBuilderV3."""
    
    async def run_workflow(self, prompt: str) -> None:
        """Run the workflow using WorkflowBuilderV3."""
        self.spinner_manager.start("Creating analysis plan...")
        
        # Get Azure configuration
        try:
            self.azure_endpoint = st.secrets["azure_ai_foundry"]["proj_endpoint"]
            self.model_name = st.secrets["azure_ai_foundry"]["model_deployment_name"]
        except KeyError:
            st.error("❌ Please configure your Azure AI Foundry settings in Streamlit secrets.")
            return
        
        # Use Azure AI Project client
        from azure.identity.aio import DefaultAzureCredential
        from azure.ai.projects.aio import AIProjectClient
        from src.ui.thread_manager import ThreadManager
        from src.workflow.workflow_builder_v3 import WorkflowBuilderV3
        
        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=self.azure_endpoint, credential=credential) as project_client,
        ):
            # Create thread manager
            thread_manager = ThreadManager(project_client)
            
            # Create threads for four agents
            agent_names = ["entity_extractor", "knowledge_base_searcher", "executor", "reviewer"]
            threads = await thread_manager.get_all_threads(agent_names)
            
            # Create event handler
            from src.ui.event_handler import create_streamlit_event_handler
            event_handler = create_streamlit_event_handler(self.streaming_state, self.spinner_manager)
            
            # Create middleware
            middleware = [self._create_tool_calls_middleware(event_handler)]
            
            # Prepare MCP configuration
            mcp_config = None
            try:
                mcp_config = {
                    "url": st.secrets["mcp"]["mcp_server_url"],
                    "client_id": st.secrets["mcp"]["mcp_client_id"],
                    "client_secret": st.secrets["mcp"]["mcp_client_secret"],
                    "tenant_id": st.secrets["env"]["AZURE_TENANT_ID"],
                    "allowed_tools": st.secrets["mcp"].get("allowed_tools", [])
                }
            except KeyError:
                logger.warning("⚠️ MCP configuration not found - MCP tool will not be available")
            
            # Get vector store ID
            vector_store_id = None
            try:
                vector_store_id = st.secrets['vector_store_id']
            except KeyError:
                logger.warning("⚠️ Vector store ID not found - knowledge base tool will not be available")
            
            # Create workflow builder - all tools are created inside builder
            workflow_builder = WorkflowBuilderV3(
                project_client=project_client,
                model=self.model_name,
                threads=threads,
                mcp_config=mcp_config,
                vector_store_id=vector_store_id,
                middleware=middleware,
                event_handler=event_handler
            )
            
            try:
                # Run the workflow
                await workflow_builder.run_workflow(prompt)
                    
            except Exception as e:
                logger.error(f"Error running workflow: {e}", exc_info=True)
                st.error(f"❌ Error running workflow: {str(e)}")
            finally:
                self.spinner_manager.stop()


def main():
    """Main entry point for the application."""
    app = DataAnalystAppV3()
    app.run()


if __name__ == "__main__":
    main()

