"""Executor classes for the new orchestrator workflow."""

import logging
from typing import Dict, List, Any, Optional

from agent_framework import (
    Executor,
    WorkflowContext,
    handler,
)
from agent_framework.azure import AzureAIAgentClient

from .models import DataExtractionRequest, ExecutionResult, ReviewFeedback, EntityList, generate_request_id

logger = logging.getLogger(__name__)



async def _collect_stream_text(agent, prompt: str) -> str:
    """Run agent with run_stream and collect all text."""
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
        """Extracts entities from user query"""
        
        logger.info(f"🔍 EntityExtractor.extract_entities called with query: {user_query}")
        
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
    
    @handler
    async def refine_search_with_feedback(
        self,
        feedback: ReviewFeedback,
        ctx: WorkflowContext[DataExtractionRequest]
    ) -> None:
        """Refines knowledge base search based on reviewer feedback"""
        
        logger.info(f"🔍 KnowledgeBaseSearcher.refine_search_with_feedback called with feedback: {feedback.feedback}")
        
        try:
            # Search again with additional context from feedback
            prompt = f"Previous search was not sufficient. The reviewer provided this feedback: {feedback.feedback}\n\nPlease search the knowledge base more thoroughly. Use the Knowledge Base Search Tool to find additional relevant information based on the reviewer's feedback.\n\nIf there are missing entities or terms mentioned in the feedback, search for those specifically."
            
            # Run the agent with run_stream and collect all text
            additional_knowledge = await _collect_stream_text(self._agent, prompt)
            
            logger.info(f"Refined knowledge base search completed, found {len(additional_knowledge)} chars")
            
            # We need to preserve user_prompt from original request
            # For now, we'll use empty string - executor will need to get it from context
            request = DataExtractionRequest(
                request_id=feedback.request_id,
                user_prompt="",  # Should be preserved from original request
                knowledge_terms=additional_knowledge
            )
            
            await ctx.send_message(request)
            
        except Exception as e:
            logger.error(f"Error refining knowledge base search: {e}", exc_info=True)
            fallback_request = DataExtractionRequest(
                request_id=feedback.request_id,
                user_prompt="",
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
            name="AI Assistant",
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
        ctx: WorkflowContext[ReviewFeedback]
    ) -> None:
        """Reviews the quality of execution results"""
        
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
Return JSON with: approved (boolean), feedback (string), missing_steps (list, optional).
"""
            
            # Run the agent with run_stream and collect all text
            review_text = await _collect_stream_text(self._agent, review_prompt)
            
            # Try to parse JSON from review text
            import json
            review_json = {
                "approved": True,
                "feedback": review_text,
                "missing_steps": []
            }
            
            # Try to extract JSON from the text
            try:
                # Look for JSON object in the text
                import re
                json_match = re.search(r'\{[^{}]*"approved"[^{}]*\}', review_text, re.DOTALL)
                if json_match:
                    parsed_json = json.loads(json_match.group())
                    review_json.update(parsed_json)
            except Exception:
                # If JSON parsing fails, use the full text as feedback
                pass
                
            feedback = ReviewFeedback(
                request_id=result.request_id,
                approved=review_json.get("approved", False),
                feedback=review_json.get("feedback", review_text),
                missing_steps=review_json.get("missing_steps")
            )
            
            logger.info(f"Review completed for {result.request_id}, approved: {feedback.approved}")
            
            await ctx.send_message(feedback)
                
        except Exception as e:
            logger.error(f"Error reviewing results: {e}", exc_info=True)
            # Create fallback feedback
            fallback_feedback = ReviewFeedback(
                request_id=result.request_id,
                approved=False,
                feedback=f"Review error: {str(e)}",
                missing_steps=[]
            )
            await ctx.send_message(fallback_feedback)
