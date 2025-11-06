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
        
        # Initialize user messages collection if not exists
        if "user_messages" not in st.session_state:
            st.session_state.user_messages = []
        
        # Reset iteration counters for new conversation (if this is first message)
        if not st.session_state.user_messages:
            st.session_state.executor_iterations = 0
            st.session_state.reviewer_iterations = 0
            logger.info("Starting new conversation - resetting iteration counters")
        
        # Add current prompt to collection if it's new
        if not st.session_state.user_messages or st.session_state.user_messages[-1] != prompt:
            st.session_state.user_messages.append(prompt)
        
        # Combine all user messages
        if len(st.session_state.user_messages) > 1:
            messages_text = "\n\n".join([
                f"User message {i+1}: {msg}" 
                for i, msg in enumerate(st.session_state.user_messages)
            ])
            combined_prompt = f"User conversation history:\n{messages_text}"
            logger.info(f"Combining {len(st.session_state.user_messages)} user messages")
        else:
            combined_prompt = prompt
            logger.info(f"Using single message only")
        
        # Get Azure configuration
        try:
            self.azure_endpoint = st.secrets["azure_ai_foundry"]["proj_endpoint"]
            self.model_name = st.secrets["azure_ai_foundry"]["model_deployment_name"]
        except KeyError:
            st.error("❌ Please configure your Azure AI Foundry settings in Streamlit secrets.")
            return
        
        # Initialize Cosmos DB search tool
        cosmosdb_search_tool = None
        try:
            from src.search_config import get_cosmosdb_search_client
            from src.tools.search_cosmosdb_knowledge_base import CosmosDBKnowledgeBaseSearchTool
            
            cosmosdb_client = get_cosmosdb_search_client()
            cosmosdb_search_tool = CosmosDBKnowledgeBaseSearchTool(cosmosdb_client)
            logger.info("✅ Cosmos DB search tool initialized")
        except Exception as e:
            logger.warning(f"⚠️ Cosmos DB search tool not available: {e}")
        
        # Use Azure AI Project client
        from azure.identity.aio import DefaultAzureCredential
        from azure.ai.projects.aio import AIProjectClient
        from src.ui.thread_manager import ThreadManager
        from src.workflow.builder import WorkflowBuilder
        
        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=self.azure_endpoint, credential=credential) as project_client,
        ):
            # Create thread manager
            thread_manager = ThreadManager(project_client)
            
            # Create threads for agents (orchestrator, data_planner, data_extractor)
            agent_names = ["orchestrator", "data_planner", "data_extractor"]
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
            
            # Create MCP tools
            mcp_tools = []
            if mcp_config:
                try:
                    from src.credentials import get_mcp_token_sync
                    from agent_framework import HostedMCPTool
                    
                    mcp_token = get_mcp_token_sync({
                        "mcp_client_id": mcp_config["client_id"],
                        "mcp_client_secret": mcp_config["client_secret"],
                        "AZURE_TENANT_ID": mcp_config["tenant_id"]
                    })
                    
                    mcp_tool = HostedMCPTool(
                        name="rentready_mcp",
                        description="Rent Ready MCP tool",
                        url=mcp_config["url"],
                        approval_mode="never_require",
                        allowed_tools=mcp_config.get("allowed_tools", []),
                        headers={"Authorization": f"Bearer {mcp_token}"} if mcp_token else {},
                    )
                    
                    mcp_tools.append(mcp_tool)
                    logger.info(f"✅ MCP tool created successfully")
                    
                except Exception as e:
                    logger.error(f"❌ Error creating MCP tool: {e}")
            
            # Create workflow builder
            workflow_builder = WorkflowBuilder(
                project_client=project_client,
                model=self.model_name,
                middleware=middleware,
                tools=mcp_tools,
                spinner_manager=self.spinner_manager,
                event_handler=event_handler,
                cosmosdb_search_tool=cosmosdb_search_tool
            )
            
            try:
                # Build and run the workflow with combined prompt
                workflow = await workflow_builder.build_workflow(threads, combined_prompt)
                
                # Run workflow with the prompt (not lambda)
                result = await workflow.run(combined_prompt)
                    
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

