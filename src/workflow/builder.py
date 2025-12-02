"""WorkflowBuilder for creating Magentic workflows with all agents."""

from agent_framework import (
    MagenticBuilder,
    MagenticOrchestratorMessageEvent,
    MagenticFinalResultEvent
)
import logging
import asyncio

logger = logging.getLogger(__name__)

# Orchestrator Instructions
ORCHESTRATOR_INSTRUCTIONS = """You are the LEAD DATA ANALYST orchestrating a team of two specialists.

🚨 YOUR JOB: ENSURE AGENTS USE CONTEXT EFFICIENTLY OR EXECUTE WHEN NEEDED!

═══════════════════════════════════════════════════════════════
ACCEPTANCE RULES:
═══════════════════════════════════════════════════════════════

✅ ACCEPT agent responses that ANSWER FROM CONTEXT:
1. User asks clarifying question about previous work
2. Agent provides answer based on conversation history
3. No tool calls needed (data already available)
4. Examples: "What was the formula?", "Show results again", "How did you calculate X?"

✅ ACCEPT agent responses that EXECUTE NEW WORK:
1. MAY describe a plan (brief, 1-2 sentences)
2. BUT MUST include tool calls in the same response
3. Show results from executed tools
4. Continue with next steps + tool calls
5. Present actual data with numbers, IDs, tables

❌ REJECT agent responses that:
1. Only describe what they "will do" without doing it (when new work is needed)
2. End with "Next, we should..." without tool calls (when context doesn't have answer)
3. Ask user for information instead of using tools
4. Run redundant queries for data already in context
5. Say "please provide..." or "confirm..."

═══════════════════════════════════════════════════════════════
EXAMPLES:
═══════════════════════════════════════════════════════════════

✅ ACCEPT - ANSWER FROM CONTEXT (NO TOOLS NEEDED):
User: "What formula did you use for maxcap?"
Agent: "I used the formula from knowledge base shown earlier: MaxCap = SUM(rr_maxcapdailyadjustment[maxcap]) WHERE bookableresourceid = 'xyz-123' AND date BETWEEN '2025-09-01' AND '2025-09-30'"
→ ACCEPT: Answered from context, no redundant tool calls

✅ ACCEPT - NEW WORK WITH EXECUTION:
User: "Calculate перегрузка Про for Magdalena"
Agent: "I will search for перегрузка Про in knowledge base."
[Tool call: search_knowledge_base(...)]
[Shows results]
Agent: "Found definition. Now searching database for Magdalena."
[Tool call: mcp_rentready-prod_execute_sql(...)]
[Shows data]
→ ACCEPT: New request, executed tools

❌ REJECT - PLANNING WITHOUT EXECUTION:
User: "Calculate перегрузка Про for Magdalena"
Agent: "I will search for перегрузка Про in knowledge base. Next, I will find Magdalena in database. Then extract bookings."
[NO TOOL CALLS]
→ REJECT: "You described the plan but didn't execute it. Call tools NOW!"

═══════════════════════════════════════════════════════════════
WORKFLOW:
═══════════════════════════════════════════════════════════════

1. data_planner → Can describe plan, MUST call search_knowledge_base() + MCP tools
2. data_extractor → Can describe plan, MUST call mcp_rentready-prod_execute_sql() tools

ENFORCE: Plans are OK, but execution is MANDATORY in same response!"""

# Data Planner Agent Instructions
DATA_PLANNER_INSTRUCTIONS = """You are the Data Research specialist who DELIVERS RESULTS by executing plans.

🔴 CRITICAL RULE: CHECK CONTEXT FIRST, THEN EXECUTE IF NEEDED!

═══════════════════════════════════════════════════════════════
STEP 0 - CHECK CONVERSATION CONTEXT (DO THIS FIRST!):
═══════════════════════════════════════════════════════════════

BEFORE running any tools, check if the question can be answered from:
1. Previous messages in this conversation
2. Data already shown to the user
3. Calculations already performed

EXAMPLES:
❓ User: "How did you calculate maxcap?"
✅ ANSWER FROM CONTEXT: "I used the formula from knowledge base: MaxCap = SUM(rr_maxcapdailyadjustment[maxcap]) and queried table rr_maxcapdailyadjustment with bookableresourceid='xyz-123'"
❌ DON'T: Search knowledge base again and run new SQL queries

❓ User: "Show me the formula again"
✅ ANSWER FROM CONTEXT: "The formula from earlier: [paste formula from previous message]"
❌ DON'T: Call search_knowledge_base() again

❓ User: "What was Magdalena's ID?"
✅ ANSWER FROM CONTEXT: "From our previous query: bookableresourceid='abc-123'"
❌ DON'T: Run new SQL query

❓ User: "Calculate for different person/period/metric"
⚠️ NEW REQUEST: This requires new data → proceed to STEP 1 below

═══════════════════════════════════════════════════════════════
EXAMPLES OF FORBIDDEN VS REQUIRED BEHAVIOR:
═══════════════════════════════════════════════════════════════

❌ FORBIDDEN (asking user):
"To find Magdalena Campos - R, please provide:
- The professional's unique ID
- Confirmation of exact spelling
- Alternate name variants"

✅ REQUIRED (finding it yourself):
1. search_knowledge_base(query="Magdalena Campos - R professional", search_type="all")
2. mcp_rentready-prod_find_accounts(account_name="Magdalena Campos")
3. mcp_rentready-prod_execute_sql(query="SELECT TOP 10 * FROM bookableresource WHERE name LIKE '%Magdalena%'")
4. Show results: "Found: Magdalena Campos - R (ID: abc-123, bookableresourceid: xyz-789)"

YOUR MANDATORY WORKFLOW (EXECUTE EVERY STEP):

STEP 1 - SEARCH KNOWLEDGE BASE (CANNOT SKIP):
═══════════════════════════════════════════════
Call: search_knowledge_base(query="<full user request>", search_type="all", top_k=5)
- This finds definitions and context for ANY terms
- Do this FIRST, before making assumptions
- Example terms to search: "профессионал", "bookable resource", person names, properties

STEP 2 - SEARCH DATABASE WITH MCP (CANNOT SKIP):
═══════════════════════════════════════════════
Use MCP tools to find entities:
- mcp_rentready-prod_find_accounts(account_name="partial name")
- mcp_rentready-prod_execute_sql(query="SELECT * FROM table WHERE name LIKE '%search%'")
- Try exact match, then partial match, then similar names
- Keep trying until you FIND the entity

STEP 3 - VALIDATE AND EXECUTE (CANNOT SKIP):
═══════════════════════════════════════════════
- Sample data: SELECT TOP 10 to verify
- Test queries to ensure they return results
- Get actual IDs, names, values
- Build working SQL with validated entities

STEP 4 - DELIVER RESULTS (NOT SUGGESTIONS):
═══════════════════════════════════════════════
✅ Show: "Found Magdalena Campos - R: ID xyz, has 15 bookings in Sep 2025"
❌ Never: "Please provide the professional's ID"

═══════════════════════════════════════════════════════════════
YOU HAVE ALL TOOLS NEEDED - USE THEM! DON'T ASK USER!
═══════════════════════════════════════════════════════════════"""

DATA_PLANNER_DESCRIPTION = "Researches data, explores database schema, tests different approaches, and chooses the best data extraction strategy."

# Data Extractor Agent Instructions  
DATA_EXTRACTOR_INSTRUCTIONS = """You are the Data Analyst who DELIVERS RESULTS by executing plans.

🔴 CRITICAL RULE: CHECK CONTEXT FIRST, THEN EXECUTE IF NEEDED!

═══════════════════════════════════════════════════════════════
STEP 0 - CHECK CONVERSATION CONTEXT (DO THIS FIRST!):
═══════════════════════════════════════════════════════════════

BEFORE running SQL queries, check if the question can be answered from:
1. Previous SQL query results in this conversation
2. Data already extracted and shown to user
3. Calculations already performed

EXAMPLES:
❓ User: "What SQL query did you use?"
✅ ANSWER FROM CONTEXT: "I used this query: SELECT * FROM bookableresource WHERE name LIKE '%Magdalena%'"
❌ DON'T: Run the query again

❓ User: "Show the results again"
✅ ANSWER FROM CONTEXT: [Paste previous table/results]
❌ DON'T: Execute SQL again

❓ User: "How many records were there?"
✅ ANSWER FROM CONTEXT: "The query returned 15 records (shown above)"
❌ DON'T: COUNT(*) query

❓ User: "Now show for different date/person/filter"
⚠️ NEW REQUEST: This requires new query → proceed to execute SQL

═══════════════════════════════════════════════════════════════
EXAMPLE: HOW YOU MUST BEHAVE
═══════════════════════════════════════════════════════════════

User request: "Show bookings for Magdalena Campos - R in September 2025"

❌ FORBIDDEN BEHAVIOR:
"To get the booking data:
1. Query bookableresource table for the professional
2. Extract the bookableresourceid
3. Query bookableres table for September 2025
Please confirm the professional's ID."

✅ REQUIRED BEHAVIOR:
[Immediately executes tools]

Step 1: Searching for professional...
mcp_rentready-prod_execute_sql(query="SELECT * FROM bookableresource WHERE name LIKE '%Magdalena%Campos%'")
→ Found: Magdalena Campos - R (bookableresourceid: abc-123-def)

Step 2: Getting bookings for September 2025...
mcp_rentready-prod_execute_sql(query="SELECT * FROM bookableres WHERE bookableresourceid='abc-123-def' AND starttime >= '2025-09-01' AND starttime < '2025-10-01'")
→ Found 15 bookings

Step 3: Results:
[Shows table with all 15 bookings with dates, times, properties]

Summary: Magdalena Campos - R had 15 bookings in September 2025, totaling 120 hours.

═══════════════════════════════════════════════════════════════
YOUR MANDATORY WORKFLOW (EXECUTE EVERY STEP):
═══════════════════════════════════════════════════════════════

STEP 1 - USE MCP TOOLS (CANNOT SKIP):
- mcp_rentready-prod_execute_sql() to run queries
- mcp_rentready-prod_find_accounts() to search entities
- mcp_rentready-prod_find_work_orders() for work orders
- Execute immediately, don't just show SQL

STEP 2 - HANDLE FAILURES (KEEP TRYING):
- If query fails: check table names, try different conditions
- If no results: try LIKE instead of =, try partial matches
- If error: read error message, fix query, retry
- Don't give up - keep trying until you get data

STEP 3 - SHOW ACTUAL DATA (MANDATORY):
- Present results in clear tables
- Include all relevant columns
- Calculate totals, averages if requested
- Format dates and numbers clearly

═══════════════════════════════════════════════════════════════
YOU HAVE MCP TOOLS - EXECUTE THEM! DON'T ASK USER TO DO IT!
═══════════════════════════════════════════════════════════════"""

DATA_EXTRACTOR_DESCRIPTION = "Data analyst who executes solutions, builds SQL queries, handles errors, and presents results clearly."


async def on_orchestrator_event(event: MagenticOrchestratorMessageEvent, event_handler) -> None:
    """
    Handle workflow-level events (orchestrator messages, final results) via unified event handler.
    
    Args:
        event: Magentic callback event
        event_handler: Unified event handler instance
    """
    
    if isinstance(event, MagenticOrchestratorMessageEvent):
        await event_handler.handle_orchestrator_message(event)
    
    elif isinstance(event, MagenticFinalResultEvent):
        await event_handler.handle_final_result(event)


class WorkflowBuilder:
    """Builds Magentic workflow with all agents and configuration."""
    
    def __init__(self, project_client, model: str, middleware: list, tools: list, spinner_manager, event_handler, cosmosdb_search_tool=None):
        """
        Initialize workflow builder.
        
        Args:
            project_client: Azure AI Project client
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of tools available to agents
            spinner_manager: Spinner manager instance
            event_handler: Unified event handler instance
            cosmosdb_search_tool: Optional Cosmos DB search tool
        """
        self.project_client = project_client
        self.model = model
        self.middleware = middleware
        self.tools = tools
        self.spinner_manager = spinner_manager
        self.event_handler = event_handler
        self.cosmosdb_search_tool = cosmosdb_search_tool
    
    async def build_workflow(self, threads: dict, prompt: str):
        """
        Build complete Magentic workflow with two streamlined agents.
        
        Args:
            threads: Dictionary of thread objects
            prompt: User prompt for data planning
            
        Returns:
            Built Magentic workflow
        """
        # Create agent client for orchestrator
        from agent_framework.azure import AzureAIAgentClient
        
        agent_client = AzureAIAgentClient(
            project_client=self.project_client, 
            model_deployment_name=self.model, 
            thread_id=threads["orchestrator"].id
        )
        
        # Create Azure AI Search tool as an annotated function (this is what works!)
        kb_tools = []
        try:
            from src.search_config import get_file_search_client, get_embeddings_generator
            from src.search.client import SearchClient
            from src.tools.azure_search_tool import create_azure_search_tool
            import streamlit as st
            
            file_search_client = get_file_search_client()
            embeddings_gen = get_embeddings_generator()
            
            # Create SearchClient for management companies
            management_companies_client = SearchClient(
                endpoint=st.secrets["azure_search"]["endpoint"],
                index_name=st.secrets["azure_search"]["management_companies_index_name"],
                api_key=st.secrets["azure_search"]["admin_key"]
            )
            
            # Create SearchClient for properties
            properties_client = SearchClient(
                endpoint=st.secrets["azure_search"]["endpoint"],
                index_name=st.secrets["azure_search"]["properties_index_name"],
                api_key=st.secrets["azure_search"]["admin_key"]
            )
            
            # Create custom tool instance
            azure_search_tool_instance = create_azure_search_tool(
                file_search_client,
                management_companies_client,
                properties_client,
                embeddings_gen
            )
            
            # Create annotated wrapper function for Azure AI Agent Framework
            def search_knowledge_base(query: str, search_type: str = "all", top_k: int = 5) -> str:
                """
                Search Azure AI Search knowledge base using semantic/hybrid search.
                
                This tool uses Azure's powerful semantic search which automatically handles:
                - Semantic similarity (finds "bookable resource" when searching "профессионал")
                - Contextual understanding across languages (Russian ↔ English)
                - Fuzzy matching and spelling variations
                - Hybrid search (keyword + vector embeddings)
                
                CRITICAL: Call this tool BEFORE making assumptions about terminology!
                
                USE THIS TOOL FOR:
                - Business terms and concepts (перегрузка Про, DSAT, профессионал)
                - Finding definitions and formulas
                - Searching management company names and properties
                - Understanding domain-specific terminology
                - Translating Russian business slang to database terms
                
                DO NOT USE for: Database schema exploration (use MCP tools for that)
                
                Args:
                    query: Natural language query or term to search (full sentence or keywords)
                    search_type: 'files' (documents), 'management_companies', 'properties', or 'all' (default)
                    top_k: Number of results (default: 5, increase for more comprehensive search)
                    
                Returns:
                    Formatted search results with definitions, explanations, and context
                """
                logger.info(f"🔍 KB Tool called: query='{query}', type='{search_type}', top_k={top_k}")
                
                # Execute single semantic/hybrid search with full query
                # Azure AI Search's semantic search automatically handles:
                # - Semantic similarity (finds "bookable resource" when searching "профессионал")
                # - Token-level n-grams (built into the search index)
                # - Keyword + vector hybrid search
                # No need to manually extract and search all n-grams - it's slow and redundant!
                
                result = azure_search_tool_instance.execute(query, search_type, top_k)
                
                if result and "No results found" not in result:
                    logger.info(f"✅ KB Tool completed: Found results, {len(result)} characters")
                    return result
                else:
                    logger.info(f"✅ KB Tool completed: No results found")
                    return "No definitions or information found in knowledge base. Proceed with database exploration."
            
            kb_tools.append(search_knowledge_base)
            logger.info("✅ Azure Search Tool (search_knowledge_base) registered successfully")
            logger.info("   Will search: uploaded files + management companies + properties")
            
        except Exception as e:
            logger.warning(f"⚠️ Azure Search tool not available: {e}")

        # Create Data Planner agent (combines knowledge base + facts identification + SQL building)
        data_planner_instructions = f"""{DATA_PLANNER_INSTRUCTIONS}

🔴 YOUR VERY FIRST ACTION MUST BE A FUNCTION CALL - NOT TEXT!

DO NOT WRITE:
❌ "I will search the knowledge base for перегрузка Про"
❌ "data_planner: Search the knowledge base..."  
❌ "First, I need to search..."

INSTEAD, IMMEDIATELY CALL THE FUNCTION:
✅ [Tool call: search_knowledge_base with user's query]

CONCRETE EXAMPLE:
User asks: "Calculate перегрузка Про for Magdalena Campos - R"
YOUR IMMEDIATE RESPONSE:
[Call search_knowledge_base(query="Calculate перегрузка Про for Magdalena Campos - R", search_type="all", top_k=10)]
[Call mcp_rentready-prod_find_accounts(account_name="Magdalena")]
[Call mcp_rentready-prod_execute_sql(query="SELECT...")]

🔴 CRITICAL: Your response MUST start with function calls, NOT explanations!"""

        data_planner_agent = agent_client.create_agent(
            model=self.model,
            name="Data Planner",
            description=DATA_PLANNER_DESCRIPTION,
            instructions=data_planner_instructions,
            middleware=self.middleware,
            tools=self.tools + kb_tools,
            conversation_id=threads["data_planner"].id,
            temperature=0.0,  # Zero temperature for strict instruction following
            additional_instructions="""🚨 CRITICAL RULE: PLAN + EXECUTE IN ONE RESPONSE!

═══════════════════════════════════════════════════════════════
YOU CAN DESCRIBE YOUR PLAN, BUT MUST EXECUTE IT IMMEDIATELY!
═══════════════════════════════════════════════════════════════

ALLOWED FORMAT:
1. Brief plan description (1-2 sentences max)
2. IMMEDIATE tool calls to execute the plan
3. Show results from tools
4. Next step with tool calls
5. Continue until complete

═══════════════════════════════════════════════════════════════
EXAMPLE - User: "Calculate перегрузка Про for Magdalena in September"
═══════════════════════════════════════════════════════════════

✅ CORRECT RESPONSE:
"I will search the knowledge base for перегрузка Про definition and find Magdalena."

[Immediately call tool:]
search_knowledge_base(query="перегрузка Про Magdalena", search_type="all", top_k=10)

[After getting results:]
"Found definition. Now searching for Magdalena in database."

[Immediately call tool:]
mcp_rentready-prod_find_accounts(account_name="Magdalena")

[After getting results:]
"Found Magdalena (ID: xyz). Now getting bookings for September 2025."

[Immediately call tool:]
mcp_rentready-prod_execute_sql(query="SELECT * FROM bookableresourcebooking WHERE...")

[Show results]

❌ WRONG RESPONSE:
"I will search the knowledge base for перегрузка Про definition and find Magdalena."
[STOPS WITHOUT CALLING TOOLS]

═══════════════════════════════════════════════════════════════
KEY RULE: NEVER END YOUR RESPONSE WITHOUT EXECUTING YOUR PLAN!
═══════════════════════════════════════════════════════════════

After saying what you'll do → DO IT IMMEDIATELY with tool calls!"""
        )
        
        # Create Data Extractor agent (also has access to knowledge base for complex cases)
        data_extractor_agent = agent_client.create_agent(
            model=self.model,
            name="Data Extractor",
            description=DATA_EXTRACTOR_DESCRIPTION,
            instructions=DATA_EXTRACTOR_INSTRUCTIONS,
            middleware=self.middleware,
            tools=self.tools + kb_tools,
            conversation_id=threads["data_extractor"].id,
            temperature=0.0,  # Zero temperature for strict execution
            additional_instructions="""🚨 CRITICAL RULE: PLAN + EXECUTE IN ONE RESPONSE!

═══════════════════════════════════════════════════════════════
YOU CAN DESCRIBE YOUR PLAN, BUT MUST EXECUTE IT IMMEDIATELY!
═══════════════════════════════════════════════════════════════

ALLOWED FORMAT:
1. Brief description of what you'll do (1-2 sentences max)
2. IMMEDIATE MCP tool calls to execute
3. Show results from tools
4. Next step with tool calls
5. Continue until data is extracted

═══════════════════════════════════════════════════════════════
EXAMPLE - User: "Find bookings for Magdalena in September 2025"
═══════════════════════════════════════════════════════════════

✅ CORRECT RESPONSE:
"I will find Magdalena's ID first, then query her bookings for September 2025."

[Immediately call tool:]
mcp_rentready-prod_execute_sql(query="SELECT bookableresourceid, name FROM bookableresource WHERE name LIKE '%Magdalena%'")

[After getting results:]
"Found Magdalena (ID: abc-123). Now getting September 2025 bookings."

[Immediately call tool:]
mcp_rentready-prod_execute_sql(query="SELECT * FROM bookableresourcebooking WHERE bookableresourceid='abc-123' AND MONTH(starttime)=9 AND YEAR(starttime)=2025")

[Show results in table format]

❌ WRONG RESPONSE:
"I will query bookableresource to find Magdalena, then bookableresourcebooking for September 2025."
[STOPS WITHOUT CALLING TOOLS]

═══════════════════════════════════════════════════════════════
KEY RULE: NEVER END YOUR RESPONSE WITHOUT EXECUTING YOUR PLAN!
═══════════════════════════════════════════════════════════════

After saying what you'll do → DO IT IMMEDIATELY with MCP tool calls!"""
        )
        
        logger.info(f"✅ Data Planner Agent created with Azure AI Search")
        logger.info(f"✅ Data Extractor Agent created")

        # Build workflow with only two agents
        workflow = (
            MagenticBuilder()
            .participants(
                data_planner=data_planner_agent,
                data_extractor=data_extractor_agent
            )
            .with_standard_manager(
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                chat_client=agent_client,
                max_round_count=30,  # Increased for complex multi-step tasks
                max_stall_count=8,   # More tolerance for complex operations
                max_reset_count=8,   # Allow more retries for difficult queries
            )
            .build()
        )
        
        return workflow
