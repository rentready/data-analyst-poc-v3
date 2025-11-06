"""Test script to reproduce the workflow and search for 'прошник'."""
import asyncio
import sys
import os
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_search_tools():
    """Test the search tools directly."""
    print("\n" + "="*80)
    print("STEP 1: Testing Search Tools Directly")
    print("="*80 + "\n")
    
    try:
        # Load secrets
        import tomli
        with open('.streamlit/secrets.toml', 'rb') as f:
            secrets = tomli.load(f)
        
        print("✅ Secrets loaded successfully\n")
        
        # Test file-based KB search
        print("-" * 80)
        print("Testing File-Based Knowledge Base Search")
        print("-" * 80)
        
        from search_config import get_file_search_client, get_embeddings_generator
        from tools.search_knowledge_base import KnowledgeBaseSearchTool
        
        file_client = get_file_search_client()
        embeddings = get_embeddings_generator()
        kb_tool = KnowledgeBaseSearchTool(file_client, embeddings)
        
        query = "прошник"
        print(f"\nSearching for: '{query}'")
        results = await kb_tool.search_and_format(query, top_k=5)
        
        print(f"\nResults (length: {len(results)}):")
        print(results[:500] if len(results) > 500 else results)
        print("\n")
        
        # Test Cosmos DB search
        print("-" * 80)
        print("Testing Cosmos DB Knowledge Base Search")
        print("-" * 80)
        
        from search_config import get_cosmosdb_search_client
        from tools.search_cosmosdb_knowledge_base import CosmosDBKnowledgeBaseSearchTool
        
        cosmosdb_client = get_cosmosdb_search_client()
        if cosmosdb_client:
            cosmosdb_tool = CosmosDBKnowledgeBaseSearchTool(cosmosdb_client)
            
            query = "Vest"
            print(f"\nSearching for: '{query}'")
            results = await cosmosdb_tool.search_and_format(query, top_k=5)
            
            print(f"\nResults (length: {len(results)}):")
            print(results[:500] if len(results) > 500 else results)
        else:
            print("⚠️ Cosmos DB search client not available")
        
        print("\n")
        
    except Exception as e:
        logger.error(f"❌ Error testing search tools: {e}", exc_info=True)
        return False
    
    return True


async def test_agent_with_kb():
    """Test the Data Planner agent with KB tools."""
    print("\n" + "="*80)
    print("STEP 2: Testing Data Planner Agent with KB Tools")
    print("="*80 + "\n")
    
    try:
        # Load secrets and initialize
        import tomli
        with open('.streamlit/secrets.toml', 'rb') as f:
            secrets = tomli.load(f)
        
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential
        from agent_framework import AzureAIAgentClient
        
        # Initialize project client
        project_client = AIProjectClient.from_connection_string(
            credential=DefaultAzureCredential(),
            conn_str=secrets['azure_ai_foundry']['project_connection_string']
        )
        
        model_name = secrets['azure_ai_foundry']['model_deployment_name']
        
        # Create thread
        thread = await project_client.agents.create_thread()
        print(f"✅ Thread created: {thread.id}\n")
        
        # Initialize agent client
        agent_client = AzureAIAgentClient(
            project_client=project_client,
            model_deployment_name=model_name,
            thread_id=thread.id
        )
        
        # Create search tools (synchronous wrappers)
        from search_config import get_file_search_client, get_embeddings_generator, get_cosmosdb_search_client
        from tools.search_knowledge_base import KnowledgeBaseSearchTool
        from tools.search_cosmosdb_knowledge_base import CosmosDBKnowledgeBaseSearchTool
        
        file_client = get_file_search_client()
        embeddings = get_embeddings_generator()
        kb_tool = KnowledgeBaseSearchTool(file_client, embeddings)
        
        cosmosdb_client = get_cosmosdb_search_client()
        cosmosdb_tool = CosmosDBKnowledgeBaseSearchTool(cosmosdb_client) if cosmosdb_client else None
        
        # Define synchronous wrapper for file search
        def search_knowledge_base(query: str, top_k: int = 5) -> str:
            """Search knowledge base (uploaded documents) using hybrid search."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    logger.info(f"🔍 KB File Search called: query='{query}', top_k={top_k}")
                    results = loop.run_until_complete(kb_tool.search_and_format(query, top_k))
                    logger.info(f"✅ KB File Search successful: {len(results)} characters")
                    print(f"\n📄 File Search Results for '{query}':")
                    print(results[:300])
                    print("...\n")
                    return results
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"❌ Error in search_knowledge_base: {e}", exc_info=True)
                return f"Error: {str(e)}"
        
        # Define synchronous wrapper for Cosmos DB search
        def search_cosmosdb_accounts(query: str, top_k: int = 10) -> str:
            """Search for company and property names in Cosmos DB."""
            if not cosmosdb_tool:
                return "Cosmos DB search not available"
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    logger.info(f"🔍 Cosmos DB Search called: query='{query}', top_k={top_k}")
                    results = loop.run_until_complete(cosmosdb_tool.search_and_format(query, top_k))
                    logger.info(f"✅ Cosmos DB Search successful: {len(results)} characters")
                    print(f"\n🏢 Cosmos DB Results for '{query}':")
                    print(results[:300])
                    print("...\n")
                    return results
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"❌ Error in search_cosmosdb_accounts: {e}", exc_info=True)
                return f"Error: {str(e)}"
        
        # Create Data Planner agent
        tools = [search_knowledge_base, search_cosmosdb_accounts]
        
        instructions = """You are the Data Research specialist. Your job is to investigate the data:

1. Analyze the user request
2. **ALWAYS use search_knowledge_base() to search for business terms in uploaded documentation**
3. **ALWAYS use search_cosmosdb_accounts() to find company/property names**
4. Provide clear information based on search results

CRITICAL: You MUST call both search tools for any query about terms or company names!"""

        data_planner = agent_client.create_agent(
            model=model_name,
            name="Data Planner",
            instructions=instructions,
            tools=tools
        )
        
        print(f"✅ Data Planner agent created with {len(tools)} tools\n")
        
        # Test query
        question = "Что такое прошник?"
        print(f"❓ Question: {question}\n")
        print("-" * 80)
        
        # Send message
        await agent_client.create_message(
            thread_id=thread.id,
            role="user",
            content=question
        )
        
        # Run agent
        print("Running agent...\n")
        run = await agent_client.create_run(
            thread_id=thread.id,
            agent_id=data_planner.id
        )
        
        # Wait for completion
        while run.status in ["queued", "in_progress", "requires_action"]:
            await asyncio.sleep(1)
            run = await agent_client.get_run(thread_id=thread.id, run_id=run.id)
            print(f"Status: {run.status}")
        
        print(f"\n✅ Run completed with status: {run.status}\n")
        
        # Get messages
        messages = await agent_client.list_messages(thread_id=thread.id)
        
        print("-" * 80)
        print("Agent Response:")
        print("-" * 80)
        for msg in messages.data:
            if msg.role == "assistant":
                for content in msg.content:
                    if hasattr(content, 'text'):
                        print(content.text.value)
        print("-" * 80)
        
        # Cleanup
        await project_client.close()
        
    except Exception as e:
        logger.error(f"❌ Error testing agent: {e}", exc_info=True)
        return False
    
    return True


async def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("Testing 'proshnik' Workflow")
    print("="*80)
    
    # Test 1: Direct search tools
    success1 = await test_search_tools()
    
    if not success1:
        print("\n❌ Search tools test FAILED - stopping here")
        return
    
    print("\n✅ Search tools test PASSED")
    
    # Test 2: Agent with KB tools
    success2 = await test_agent_with_kb()
    
    if success2:
        print("\n✅ All tests PASSED!")
    else:
        print("\n❌ Agent test FAILED")


if __name__ == "__main__":
    asyncio.run(main())

