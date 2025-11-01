"""Workflow Builder V3 - Creates 4 agents with tools initialization inside builder."""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from agent_framework import WorkflowBuilder, Executor, HostedMCPTool, HostedFileSearchTool, HostedVectorStoreContent
from agent_framework.azure import AzureAIAgentClient

from .executors import EntityExtractor, KnowledgeBaseSearcher, DataExecutorAgent, ReviewerExecutor, ReportFormatter
from .models import DataExtractionRequest, ExecutionResult, ReviewFeedback

logger = logging.getLogger(__name__)


class WorkflowBuilderV3:
    """Workflow builder that creates 4 agents and their tools inside the builder."""
    
    def __init__(
        self,
        project_client: Any,
        model: str,
        threads: Dict[str, Any],
        mcp_config: Optional[Dict[str, Any]] = None,
        vector_store_id: Optional[str] = None,
        middleware: Optional[List[Any]] = None,
        event_handler: Optional[Any] = None,
    ):
        """
        Initialize workflow builder.
        
        Args:
            project_client: Azure AI Project client
            model: Model deployment name
            threads: Dictionary of thread objects for each agent
            mcp_config: Dict with MCP configuration:
                - url: MCP server URL
                - client_id: MCP client ID
                - client_secret: MCP client secret
                - tenant_id: Azure tenant ID
                - allowed_tools: List of allowed MCP tools
            vector_store_id: Vector store ID for knowledge base tool
            middleware: List of middleware to apply to agents
            event_handler: Event handler for agent events
        """
        self.project_client = project_client
        self.model = model
        self.threads = threads
        self.mcp_config = mcp_config
        self.vector_store_id = vector_store_id
        self.middleware = middleware or []
        self.event_handler = event_handler
        
        # Create agent client (will be reused for all agents)
        self.agent_client = AzureAIAgentClient(
            project_client=self.project_client,
            model_deployment_name=self.model,
            thread_id=None  # Will be set per agent
        )
        
        # Tools will be created in create_workflow
        self._mcp_tool = None
        self._knowledge_base_tool = None
        self._time_tool = None
    
    def _create_mcp_tool(self) -> Optional[HostedMCPTool]:
        """Create MCP tool from configuration."""
        if not self.mcp_config or not self.mcp_config.get("url"):
            logger.warning("⚠️ MCP config not provided - MCP tool will not be created")
            return None
        
        try:
            from src.credentials import get_mcp_token_sync
            
            mcp_token = get_mcp_token_sync({
                "mcp_client_id": self.mcp_config["client_id"],
                "mcp_client_secret": self.mcp_config["client_secret"],
                "AZURE_TENANT_ID": self.mcp_config["tenant_id"]
            })
            
            mcp_tool = HostedMCPTool(
                name="rentready_mcp",
                description="Rent Ready MCP tool",
                url=self.mcp_config["url"],
                approval_mode="never_require",
                allowed_tools=self.mcp_config.get("allowed_tools", []),
                headers={"Authorization": f"Bearer {mcp_token}"} if mcp_token else {},
            )
            
            logger.info(f"✅ MCP tool created successfully: {mcp_tool}")
            return mcp_tool
            
        except Exception as e:
            logger.error(f"❌ Error creating MCP tool: {e}")
            return None
    
    def _create_knowledge_base_tool(self) -> Optional[HostedFileSearchTool]:
        """Create knowledge base tool from configuration."""
        if not self.vector_store_id:
            logger.warning("⚠️ Vector store ID not provided - knowledge base tool will not be created")
            return None
        
        try:
            knowledge_base_tool = HostedFileSearchTool(
                inputs=[HostedVectorStoreContent(vector_store_id=self.vector_store_id)]
            )
            logger.info(f"✅ Knowledge base tool created with vector_store_id: {self.vector_store_id[:20]}...")
            return knowledge_base_tool
        except Exception as e:
            logger.error(f"❌ Error creating knowledge base tool: {e}")
            return None
    
    def _create_time_tool(self):
        """Create time tool."""
        def get_time() -> str:
            """Get the current UTC time."""
            current_time = datetime.now(timezone.utc)
            return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
        
        return get_time
    
    def create_workflow(self):
        """
        Create workflow with 4 agents and their tools.
        All tools are created inside this method.
        
        Returns:
            Built workflow
        """
        logger.info("Creating workflow with 4 agents")
        
        # Create all tools inside builder
        self._mcp_tool = self._create_mcp_tool()
        self._knowledge_base_tool = self._create_knowledge_base_tool()
        self._time_tool = self._create_time_tool()
        
        # 1. Entity Extractor - no tools needed (only extracts entities)
        entity_extractor_tools = []
        logger.info(f"Entity extractor tools: {[type(t).__name__ for t in entity_extractor_tools]}")
        
        entity_extractor = EntityExtractor(
            agent_client=self.agent_client,
            thread_id=self.threads["entity_extractor"].id,
            tools=entity_extractor_tools,
            middleware=self.middleware,
            event_handler=self.event_handler
        )
        
        # 2. Knowledge Base Searcher - has knowledge base tool
        knowledge_base_tools = []
        if self._knowledge_base_tool:
            knowledge_base_tools.append(self._knowledge_base_tool)
        else:
            logger.warning("⚠️ Knowledge base tool is None - knowledge_base_searcher won't have access to knowledge base!")
        
        logger.info(f"Knowledge base searcher tools: {[type(t).__name__ for t in knowledge_base_tools]}")
        
        knowledge_base_searcher = KnowledgeBaseSearcher(
            agent_client=self.agent_client,
            thread_id=self.threads["knowledge_base_searcher"].id,
            tools=knowledge_base_tools,
            middleware=self.middleware,
            event_handler=self.event_handler
        )
        
        # 3. Data Executor Agent - has MCP tools and time tool
        executor_tools = []
        if self._time_tool:
            executor_tools.append(self._time_tool)
        if self._mcp_tool:
            executor_tools.append(self._mcp_tool)
        else:
            logger.warning("⚠️ MCP tool is None - executor won't have access to MCP!")
        
        logger.info(f"Executor agent tools: {[type(t).__name__ for t in executor_tools]}")
        
        executor = DataExecutorAgent(
            agent_client=self.agent_client,
            thread_id=self.threads["executor"].id,
            tools=executor_tools,
            middleware=self.middleware,
            event_handler=self.event_handler
        )
        
        # 4. Reviewer - no tools needed
        reviewer_tools = []
        logger.info(f"Reviewer executor tools: {[type(t).__name__ for t in reviewer_tools]}")
        
        reviewer = ReviewerExecutor(
            agent_client=self.agent_client,
            thread_id=self.threads["reviewer"].id,
            tools=reviewer_tools,
            middleware=self.middleware,
            event_handler=self.event_handler
        )
        
        # 5. Report Formatter - no tools needed
        formatter_tools = []
        logger.info(f"Report formatter tools: {[type(t).__name__ for t in formatter_tools]}")
        
        formatter = ReportFormatter(
            agent_client=self.agent_client,
            thread_id=self.threads["formatter"].id,
            tools=formatter_tools,
            middleware=self.middleware,
            event_handler=self.event_handler
        )
        
        # Build workflow: entity_extractor -> knowledge_base_searcher -> executor -> reviewer
        # Reviewer routes to either executor (if not approved, sends str) or formatter (if approved, sends ExecutionResult)
        try:
            logger.info("Creating workflow: entity_extractor -> knowledge_base_searcher -> executor -> reviewer -> (executor | formatter)")
            workflow = WorkflowBuilder()
            workflow.set_start_executor(entity_extractor)
            workflow.add_edge(entity_extractor, knowledge_base_searcher)
            workflow.add_edge(knowledge_base_searcher, executor)
            workflow.add_edge(executor, reviewer)
            # Reviewer can send either str (to executor) or ExecutionResult (to formatter)
            # WorkflowBuilder will route based on message type
            workflow.add_edge(reviewer, executor)  # For str messages (not approved)
            workflow.add_edge(reviewer, formatter)  # For ExecutionResult messages (approved)
            workflow = workflow.build()
            logger.info("✅ Workflow built successfully with conditional routing from reviewer")
        except Exception as e:
            logger.error(f"❌ Workflow build failed: {e}")
            raise e
        
        logger.info("✅ Workflow created with entity_extractor, knowledge_base_searcher, executor, reviewer, and formatter")
        return workflow
    
    async def run_workflow(self, user_query: str):
        """
        Run the workflow with a user query.
        
        Args:
            user_query: User's query
        """
        workflow = self.create_workflow()
        
        logger.info(f"Running workflow for query: {user_query}")
        
        # Run workflow and handle events
        async for event in workflow.run_stream(user_query):
            logger.info(f"Workflow event: {type(event).__name__}")
            
            # Handle workflow events if event handler is provided
            if self.event_handler and hasattr(self.event_handler, 'handle_workflow_event'):
                await self.event_handler.handle_workflow_event(event)
        
        logger.info("✅ Workflow completed")

