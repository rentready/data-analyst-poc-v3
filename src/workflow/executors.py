"""Executor classes for the new orchestrator workflow."""

import logging
import json
import streamlit as st
from typing import Dict, List, Any, Optional, Union

from agent_framework import (
    Executor,
    WorkflowContext,
    handler,
)
from agent_framework.azure import AzureAIAgentClient

from .models import DataExtractionRequest, ExecutionResult, ReviewFeedback, EntityList, generate_request_id, FormattedReportRequest

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10



async def _collect_stream_text(agent, prompt: str, max_retries: int = 5) -> str:
    """
    Run agent with run_stream and collect all text.
    Automatically retries on rate limit errors.
    
    Args:
        agent: Agent to run
        prompt: Prompt to send to agent
        max_retries: Maximum retry attempts on rate limit (default: 5)
        
    Returns:
        Collected text from agent
    """
    from src.utils.retry_helper import retry_on_rate_limit
    
    async def _run_stream():
        full_text = ""
        async for chunk in agent.run_stream(prompt):
            # Check if chunk is a dict with contents (like chat_message)
            if isinstance(chunk, dict):
                if 'contents' in chunk:
                    contents = chunk['contents']
                    if isinstance(contents, list):
                        for item in contents:
                            if isinstance(item, dict) and item.get('type') == 'text':
                                full_text += item.get('text', '')
                            elif isinstance(item, str):
                                full_text += item
                elif 'text' in chunk:
                    full_text += chunk['text']
            elif isinstance(chunk, str):
                full_text += chunk
            elif hasattr(chunk, 'text'):
                text = chunk.text
                if isinstance(text, str):
                    full_text += text
     
        logger.info(f"Collected {len(full_text)} chars")
        return full_text
    
    # Retry wrapper for rate limit handling
    return await retry_on_rate_limit(
        _run_stream,
        max_retries=max_retries,
        initial_delay=2.0,
        max_delay=30.0
    )


class EntityExtractor(Executor):
    """Entity Extractor - Extracts entity names and terms from user query"""
    
    def __init__(self, agent_client: AzureAIAgentClient, thread_id: str, tools: List[Any] = None, middleware: List[Any] = None, event_handler=None):
        super().__init__(id="entity_extractor")
        self._agent_client = agent_client
        self._thread_id = thread_id
        self._tools = tools or []
        self._middleware = middleware or []
        self._event_handler = event_handler
        
        # Create the actual agent
        self._agent = self._create_agent()
    
    def _create_agent(self):
        """Create the Azure AI agent for entity extraction"""
        logger.info(f"Creating entity extractor agent with {len(self._tools)} tools: {[type(t).__name__ for t in self._tools]}")
        return self._agent_client.create_agent(
            model=getattr(self._agent_client, "model_deployment_name", None),
            name="Entity Extractor",
            description="Extracts entity names, terms, and key concepts from user queries.",
            instructions="""You are a helpful assistant that extracts entity names, terms, and key concepts from user queries. 
Return only a simple list of entities, one per line, without explanations.""",
            tools=self._tools,
            middleware=self._middleware,
            conversation_id=self._thread_id,
            temperature=0.1
        )
        
    @handler
    async def extract_entities(
        self, 
        user_query: str, 
        ctx: WorkflowContext[EntityList]
    ) -> None:
        """Extracts entities from user query (handles both initial queries and refined prompts from reviewer)"""
        
        logger.info(f"🔍 EntityExtractor.extract_entities called with query: {user_query[:100]}...")
        
        try:
            prompt = f"Extract entity names, terms, and key concepts from this user query: {user_query}\n\nReturn only a simple list of entities, one per line, without explanations."
            
            # Run agent with run_stream and collect all text
            response_text = await _collect_stream_text(self._agent, prompt)
            
            # Parse entities from response (simple line-by-line extraction)
            entities = [line.strip() for line in response_text.split("\n") if line.strip() and not line.strip().startswith("#")]
            
            # Remove common prefixes/suffixes and filter empty/short entities
            entities = [e for e in entities if e and len(e) > 1]
            
            logger.info(f"Extracted {len(entities)} entities: {entities}")
            
            entity_list = EntityList(
                request_id=generate_request_id(),
                user_prompt=user_query,
                entities=entities
            )
            
            await ctx.send_message(entity_list)
            
        except Exception as e:
            logger.error(f"Error extracting entities: {e}", exc_info=True)
            fallback_entity_list = EntityList(
                request_id=generate_request_id(),
                user_prompt=user_query,
                entities=[]
            )
            await ctx.send_message(fallback_entity_list)


class KnowledgeBaseSearcher(Executor):
    """Knowledge Base Searcher - Searches knowledge base for each entity separately"""
    
    def __init__(self, agent_client: AzureAIAgentClient, thread_id: str, tools: List[Any] = None, middleware: List[Any] = None, event_handler=None):
        super().__init__(id="knowledge_base_searcher")
        self._agent_client = agent_client
        self._thread_id = thread_id
        self._tools = tools or []
        self._middleware = middleware or []
        self._event_handler = event_handler
        
        # Create the actual agent
        self._agent = self._create_agent()
    
    def _create_agent(self):
        """Create the Azure AI agent for knowledge base search"""
        logger.info(f"Creating knowledge base searcher agent with {len(self._tools)} tools: {[type(t).__name__ for t in self._tools]}")
        return self._agent_client.create_agent(
            model=getattr(self._agent_client, "model_deployment_name", None),
            name="Knowledge Base Searcher",
            description="Searches knowledge base for information about entities and terms.",
            instructions="""You are a friendly knowledge base assistant. Use the Knowledge Base Search Tool to find information for each entity. Search for each entity separately and return what you find.""",
            tools=self._tools,
            middleware=self._middleware,
            conversation_id=self._thread_id,
            temperature=0.1
        )
        
    @handler
    async def search_knowledge_base(
        self, 
        entity_list: EntityList, 
        ctx: WorkflowContext[DataExtractionRequest]
    ) -> None:
        """Searches knowledge base for each entity separately"""
        
        logger.info(f"🔍 KnowledgeBaseSearcher.search_knowledge_base called with {len(entity_list.entities)} entities: {entity_list.entities}")
        
        try:
            if not entity_list.entities:
                # No entities to search, create empty request
                request = DataExtractionRequest(
                    request_id=entity_list.request_id,
                    user_prompt=entity_list.user_prompt,
                    knowledge_terms=""
                )
                await ctx.send_message(request)
                return
            
            # Build prompt to search for each entity separately
            entities_text = "\n".join([f"- {entity}" for entity in entity_list.entities])
            prompt = f"For the user query: {entity_list.user_prompt}\n\nSearch the knowledge base for information about each of these entities:\n{entities_text}\n\nUse the Knowledge Base Search Tool to find definitions and information for EACH entity separately. Return what you find for each entity."
            
            # Run the agent with run_stream and collect all text
            knowledge_terms = await _collect_stream_text(self._agent, prompt)
            
            logger.info(f"Knowledge base search completed, found {len(knowledge_terms)} chars")
            
            request = DataExtractionRequest(
                request_id=entity_list.request_id,
                user_prompt=entity_list.user_prompt,
                knowledge_terms=knowledge_terms
            )
            
            await ctx.send_message(request)
            
        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}", exc_info=True)
            fallback_request = DataExtractionRequest(
                request_id=entity_list.request_id if hasattr(entity_list, 'request_id') else generate_request_id(),
                user_prompt=entity_list.user_prompt if hasattr(entity_list, 'user_prompt') else "",
                knowledge_terms=""
            )
            await ctx.send_message(fallback_request)


class DataExecutorAgent(Executor):
    """Executor Agent - Executes user query with tools"""
    
    def __init__(self, agent_client: AzureAIAgentClient, thread_id: str, tools: List[Any] = None, middleware: List[Any] = None, event_handler=None):
        super().__init__(id="executor")
        self._agent_client = agent_client
        self._thread_id = thread_id
        self._tools = tools or []
        self._middleware = middleware or []
        self._event_handler = event_handler
        
        # Create the actual agent
        self._agent = self._create_agent()
    
    def _create_agent(self):
        """Create the Azure AI agent for execution"""
        logger.info(f"Creating executor agent with {len(self._tools)} tools: {[type(t).__name__ for t in self._tools]}")
        return self._agent_client.create_agent(
            model=getattr(self._agent_client, "model_deployment_name", None),
            name="Data Analyst",
            description="Friendly AI assistant with set of tools to query different data and help users with that.",
            instructions="""You are a friendly AI assistant. Use MCP tools to execute SQL queries and get actual data. Don't just explain - actually run the queries and return the results.""",
            tools=self._tools,
            middleware=self._middleware,
            conversation_id=self._thread_id,
            temperature=0.1
        )
        
    @handler
    async def execute_request(
        self,
        request: DataExtractionRequest,
        ctx: WorkflowContext[ExecutionResult]
    ) -> None:
        """Executes user query with knowledge base context"""
        
        logger.info(f"🔍 DataExecutorAgent.execute_request called with request_id: {request.request_id}")
        
        try:
            # Build execution prompt with knowledge base context
            execution_prompt = f"User query: {request.user_prompt}\n\n"
            if request.knowledge_terms:
                execution_prompt += f"Knowledge base information:\n{request.knowledge_terms}\n\n"
            execution_prompt += "Execute the query using MCP tools and return the results."
            
            # Run the agent with run_stream and collect all text
            analysis = await _collect_stream_text(self._agent, execution_prompt)
            
            logger.info(f"Execution completed, collected {len(analysis)} chars")
            
            result = ExecutionResult(
                request_id=request.request_id,
                request=request,
                extracted_data="",
                analysis=analysis
            )
            
            await ctx.send_message(result)
            
        except Exception as e:
            logger.error(f"Error executing query: {e}", exc_info=True)
            fallback_result = ExecutionResult(
                request_id=request.request_id,
                request=request,
                extracted_data="",
                analysis=f"Error: {str(e)}"
            )
            await ctx.send_message(fallback_result)
    
    @handler
    async def retry_execution(
        self,
        refined_prompt: str,
        ctx: WorkflowContext[ExecutionResult]
    ) -> None:
        """Retries execution with refined prompt from reviewer"""
        
        logger.info(f"🔍 DataExecutorAgent.retry_execution called with refined prompt: {refined_prompt[:100]}...")
        
        try:
            # Use refined prompt directly - chat history is preserved
            # The prompt should be something like "all empty, try like this..."
            execution_prompt = refined_prompt
            
            # Run the agent with run_stream and collect all text
            analysis = await _collect_stream_text(self._agent, execution_prompt)
            
            logger.info(f"Retry execution completed, collected {len(analysis)} chars")
            
            # Create result with new analysis
            # We need to preserve original request_id, but we don't have it here
            # For now, generate new one
            result = ExecutionResult(
                request_id=generate_request_id(),
                request=DataExtractionRequest(
                    request_id=generate_request_id(),
                    user_prompt=refined_prompt,
                    knowledge_terms=""
                ),
                extracted_data="",
                analysis=analysis
            )
            
            await ctx.send_message(result)
            
        except Exception as e:
            logger.error(f"Error retrying execution: {e}", exc_info=True)
            fallback_result = ExecutionResult(
                request_id=generate_request_id(),
                request=DataExtractionRequest(
                    request_id=generate_request_id(),
                    user_prompt=refined_prompt,
                    knowledge_terms=""
                ),
                extracted_data="",
                analysis=f"Error: {str(e)}"
            )
            await ctx.send_message(fallback_result)


class ReviewerExecutor(Executor):
    """Reviewer Agent - Reviews results"""
    
    def __init__(self, agent_client: AzureAIAgentClient, thread_id: str, tools: List[Any] = None, middleware: List[Any] = None, event_handler=None):
        super().__init__(id="reviewer")
        self._agent_client = agent_client
        self._thread_id = thread_id
        self._tools = tools or []
        self._middleware = middleware or []
        self._event_handler = event_handler
        
        # Create the actual agent
        self._agent = self._create_agent()
    
    def _create_agent(self):
        """Create the Azure AI agent for review"""
        logger.info(f"Creating reviewer agent with {len(self._tools)} tools: {[type(t).__name__ for t in self._tools]}")
        return self._agent_client.create_agent(
            model=getattr(self._agent_client, "model_deployment_name", None),
            name="Data Reviewer",
            description="Critical reviewer of data analysis results who ensures quality and completeness.",
            instructions="""You are a critical reviewer of data analysis results.

Check:
1. Are all plan steps completed
2. Quality of extracted data
3. Completeness of analysis
4. Presence of errors

Approve only if all criteria are met.

Return your response in JSON format with fields: approved (boolean), feedback (string), missing_steps (list of strings, optional).""",
            tools=self._tools,
            middleware=self._middleware,
            conversation_id=self._thread_id,
            temperature=0.1
        )
        
    @handler
    async def review_results(
        self,
        result: ExecutionResult,
        ctx: WorkflowContext[Union[FormattedReportRequest, str]]
    ) -> None:
        """Reviews the quality of execution results. Returns FormattedReportRequest if approved (to formatter) or str if not approved (to executor)."""
        
        logger.info(f"Reviewing results for request {result.request_id}")
        
        try:
            # Create review prompt
            review_prompt = f"""
Review the following data analysis results:

User Query: {result.request.user_prompt}
Knowledge Base Context: {result.request.knowledge_terms}
Result: {result.analysis}
Data: {result.extracted_data}

Check if the query was answered properly, data quality is good, analysis is complete, and there are no errors.

Return JSON with "approved" (boolean) and "feedback" (string) fields.
"""
            
            # Run the agent with run_stream and collect all text
            review_text = await _collect_stream_text(self._agent, review_prompt)
            
            # Check iteration limit - force approve after MAX_ITERATIONS
            total_iterations = (st.session_state.get("executor_iterations", 0) + 
                               st.session_state.get("reviewer_iterations", 0))
            
            if total_iterations >= MAX_ITERATIONS:
                logger.warning(f"⚠️ Maximum iterations ({MAX_ITERATIONS}) reached. Forcing approval.")
                approved = True
                feedback = "Maximum iterations reached. Approving result."
            else:
                # Try to parse JSON response
                approved = False
                feedback = ""
                try:
                    review_json = json.loads(review_text.strip())
                    approved = review_json.get("approved", False)
                    feedback = review_json.get("feedback", "")
                except (json.JSONDecodeError, ValueError):
                    # Fallback: check for "APPROVED" text
                    if "APPROVED" in review_text.upper() or review_text.strip().upper() == "APPROVED":
                        approved = True
            
            if approved:
                logger.info(f"Review approved for {result.request_id}, sending FormattedReportRequest to formatter")
                # Create FormattedReportRequest and send to formatter
                formatted_request = FormattedReportRequest(
                    request_id=result.request_id,
                    user_prompt=result.request.user_prompt,
                    analysis=result.analysis,
                    extracted_data=result.extracted_data
                )
                await ctx.send_message(formatted_request)
            else:
                # Not approved - send refined prompt string to executor
                logger.info(f"Review not approved for {result.request_id}, sending refined prompt to executor")
                refined_prompt = feedback.strip() if feedback else review_text.strip()
                await ctx.send_message(refined_prompt.strip())
                
        except Exception as e:
            logger.error(f"Error reviewing results: {e}", exc_info=True)
            # On error, send to formatter as fallback
            formatted_request = FormattedReportRequest(
                request_id=result.request_id,
                user_prompt=result.request.user_prompt,
                analysis=result.analysis,
                extracted_data=result.extracted_data
            )
            await ctx.send_message(formatted_request)


class ReportFormatter(Executor):
    """Report Formatter - Formats final report for user"""
    
    def __init__(self, agent_client: AzureAIAgentClient, thread_id: str, tools: List[Any] = None, middleware: List[Any] = None, event_handler=None):
        super().__init__(id="formatter")
        self._agent_client = agent_client
        self._thread_id = thread_id
        self._tools = tools or []
        self._middleware = middleware or []
        self._event_handler = event_handler
        
        # Create the actual agent
        self._agent = self._create_agent()
    
    def _create_agent(self):
        """Create the Azure AI agent for report formatting"""
        logger.info(f"Creating report formatter agent with {len(self._tools)} tools: {[type(t).__name__ for t in self._tools]}")
        return self._agent_client.create_agent(
            model=getattr(self._agent_client, "model_deployment_name", None),
            name="Report Formatter",
            description="Formats final data analysis reports for users.",
            instructions="""You are a helpful assistant that formats data analysis results into clear, readable reports for users.
Format the report in a user-friendly way, making it easy to understand the results and any insights.
Return only the formatted report text, nothing else.""",
            tools=self._tools,
            middleware=self._middleware,
            conversation_id=self._thread_id,
            temperature=0.1
        )
    
    @handler
    async def format_report(
        self,
        request: FormattedReportRequest,
        ctx: WorkflowContext[str]
    ) -> None:
        """Formats the final report for the user."""
        
        logger.info(f"🔍 ReportFormatter.format_report called for request_id: {request.request_id}")
        
        try:
            # Format the report
            format_prompt = f"""Format a report for the user query:

User Query: {request.user_prompt}

Analysis Results:
{request.analysis}

Data:
{request.extracted_data}

Format this into a clear, readable report that answers the user's query. Make it user-friendly and easy to understand."""
            
            # Run the agent with run_stream and collect all text
            formatted_report = await _collect_stream_text(self._agent, format_prompt)
            
            logger.info(f"Report formatted, collected {len(formatted_report)} chars")
            
            # Send formatted report (this will end the workflow)
            await ctx.send_message(formatted_report.strip())
            
        except Exception as e:
            logger.error(f"Error formatting report: {e}", exc_info=True)
            # On error, send the analysis as fallback
            fallback_report = f"Analysis Results:\n\n{request.analysis}"
            await ctx.send_message(fallback_report)
