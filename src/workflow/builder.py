"""WorkflowBuilder for creating Magentic workflows with all agents."""

from agent_framework import (
    MagenticBuilder,
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
6. USE DIFFERENT FORMULA than what knowledge base provided (e.g., adding coefficients like 1.2x)
7. MODIFY category definitions from knowledge base (0/1/2/3 values have FIXED meanings)

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

STEP 0 - CHECK LOCAL EXAMPLES FIRST (HIGHEST PRIORITY):
════════════════════════════════════════════════════════════
🔴 USE read_example() TOOL BEFORE searching knowledge base!

This tool provides expert-verified templates & data that are 100% accurate.

AVAILABLE CATEGORIES:
- "sql": SQL query templates (pro_load, etc.)
- "definitions": Business metrics, glossary
- "scripts": Python or other scripts
- "data": JSON, CSV reference data

WORKFLOW FOR KNOWN QUERIES/DATA:
1. Call read_example(name="перегрузка про", category="sql")
2. Get complete template/data
3. Pass COMPLETE content to Data Extractor with instruction: "USE THIS EXACTLY"
4. Tell Data Extractor which placeholders to replace (if any)

WHY read_example IS BETTER THAN search_knowledge_base:
✅ 100% accurate - exact content, no risk of incomplete AI search results
✅ Expert-verified - tested against production data
✅ Faster - direct file read, no AI Search API calls
✅ Deterministic - same input always gives same output
✅ Supports any format - SQL, JSON, YAML, markdown, etc.

STEP 1 - SEARCH KNOWLEDGE BASE (IF NO LOCAL EXAMPLE):
═══════════════════════════════════════════════════════
Call: search_knowledge_base(query="<full user request>", search_type="all", top_k=5)
- This finds definitions and context for ANY terms
- Do this if no local SQL template exists
- Example terms to search: "профессионал", "bookable resource", person names, properties

🔴 CRITICAL: IF KNOWLEDGE BASE RETURNS SQL QUERY - USE IT AS IS!
- Do NOT simplify or modify the SQL logic
- Only replace placeholder values (IDs, dates, names)
- Keep ALL JOINs, WHERE conditions, CASE expressions EXACTLY as shown
- The SQL in KB was written by domain experts - trust it completely

🔴 WHEN PASSING SQL TO DATA EXTRACTOR:
- Include the COMPLETE SQL query from KB in your response
- Say: "Use this EXACT SQL from knowledge base: [paste full SQL]"
- Emphasize: "Do NOT modify the CASE expression or WHERE conditions"

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

🔴🔴🔴 ABSOLUTE RULE #0: USE SQL FROM DATA PLANNER EXACTLY! 🔴🔴🔴

If Data Planner provides SQL template (from read_sql_example tool or Knowledge Base):
1. COPY the SQL EXACTLY - character by character
2. ONLY replace placeholders: <PRO_ID>, <START_DATE>, <END_DATE>
3. DO NOT modify anything else - no JOINs, WHERE conditions, CASE expressions
4. Pass complete SQL to mcp_rentready-prod_execute_sql()

STEP 1 - USE MCP TOOLS (CANNOT SKIP):
- mcp_rentready-prod_execute_sql() to run queries
- mcp_rentready-prod_find_accounts() to search entities
- mcp_rentready-prod_find_work_orders() for work orders
- Execute immediately, don't just show SQL

🔴🔴🔴 ABSOLUTE RULE #1: USE SQL FROM SOURCES EXACTLY AS IS! 🔴🔴🔴

When Data Planner or Knowledge Base or Local File provides SQL query, you MUST:
✅ Use ALL JOINs exactly as shown - do NOT remove any JOIN
✅ Use ALL WHERE conditions - do NOT remove any filter
✅ Use CASE expressions character-by-character - do NOT modify logic
✅ Keep ALL GROUP BY, ORDER BY clauses
✅ Only replace placeholder values: IDs, dates, names

❌ FORBIDDEN SIMPLIFICATIONS - NEVER DO THIS:

1️⃣ ❌ Removing JOINs:
   KB gives: `FROM bookableresourcebooking brb LEFT JOIN msdyn_workorder wo ON ...`
   You write: `FROM bookableresourcebooking brb` ← WRONG! Keep the JOIN!

2️⃣ ❌ Removing WHERE conditions:
   KB gives: `WHERE ... AND wo.msdyn_systemstatus IN (690970004, 690970003, 690970002, 690970001) AND wo.statuscode = 1 AND wo.rr_workscheduleddate IS NOT NULL AND brb.bookingstatus = 'c33410b9-1abe-4631-b4e9-6e4a1113af34'`
   You write: `WHERE ...` ← WRONG! Keep ALL filters!

3️⃣ ❌ Simplifying CASE logic:
   KB gives: `CASE WHEN x=0 THEN 0 WHEN x<y THEN 1 WHEN x=y THEN 2 WHEN x>y THEN 3 END`
   You write: `x - y` ← WRONG! Use the CASE!

4️⃣ ❌ Changing category meanings:
   KB says: "0=no load, 1=low, 2=equal, 3=over"
   You interpret: "0=below, 1=at, 2=over 1.2x" ← WRONG!

✅ CORRECT BEHAVIOR - COPY-PASTE APPROACH:
If KB gives this SQL template:
```sql
SELECT CASE WHEN SUM(x) < y THEN 1 END
FROM table1 t1
LEFT JOIN table2 t2 ON t1.id = t2.fk
WHERE t2.status IN (1,2,3) AND t2.date IS NOT NULL
```

You MUST use:
```sql
SELECT CASE WHEN SUM(x) < y THEN 1 END  -- Keep EXACT CASE logic
FROM table1 t1
LEFT JOIN table2 t2 ON t1.id = t2.fk   -- Keep JOIN
WHERE t2.status IN (1,2,3)              -- Keep status filter
  AND t2.date IS NOT NULL               -- Keep date filter
  AND t1.id = '<REPLACE_WITH_ACTUAL_ID>' -- Only add/replace IDs
```

🔴 RULE: If SQL from KB has 5 lines, your SQL should have 5 lines (plus ID replacements).
🔴 RULE: If SQL from KB has 3 JOINs, your SQL must have 3 JOINs.
🔴 RULE: If SQL from KB has 8 WHERE conditions, your SQL must have 8 WHERE conditions.

STEP 2 - HANDLE FAILURES (KEEP TRYING):
- If query fails: check table names, try different conditions
- If no results: try LIKE instead of =, try partial matches
- If error: read error message, fix query, retry
- Don't give up - keep trying until you get data

🔴 CRITICAL: NAME SEARCH STRATEGY (USE THIS ORDER):
When searching for entities by name (people, properties, etc.):

1️⃣ FIRST - Try exact match:
   `WHERE name = 'Magdalena Campos - R'`

2️⃣ SECOND - Try full phrase match:
   `WHERE name LIKE '%Magdalena Campos - R%'`

3️⃣ THIRD - Try ALL words with AND (NOT OR!):
   `WHERE name LIKE '%Magdalena%' AND name LIKE '%Campos%'`
   
   ⚠️ Skip very short words (1-2 letters) like "R" in this step
   ⚠️ For short words, only use if combined with longer words

❌ FORBIDDEN - DO NOT USE:
   `WHERE name LIKE '%R%'` ← Too broad! Returns thousands of records
   `WHERE name LIKE '%Magdalena%' OR name LIKE '%R%'` ← OR with short word = bad!

✅ CORRECT EXAMPLE:
   User asks: "Find Magdalena Campos - R"
   
   Try 1: `SELECT * FROM bookableresource WHERE name = 'Magdalena Campos - R'`
   ↓ If no results
   Try 2: `SELECT * FROM bookableresource WHERE name LIKE '%Magdalena Campos - R%'`
   ↓ If no results  
   Try 3: `SELECT * FROM bookableresource WHERE name LIKE '%Magdalena%' AND name LIKE '%Campos%'`
   ✅ Found: "Magdalena Campos - R"

❌ WRONG EXAMPLE:
   `SELECT * FROM bookableresource 
    WHERE name LIKE '%Magdalena%' 
       OR name LIKE '%Campos%' 
       OR name LIKE '%R%'` ← Returns 10,000+ records including "Robert", "Richard", etc.

STEP 3 - SHOW ACTUAL DATA (MANDATORY):
- Present results in clear tables
- Include all relevant columns
- Calculate totals, averages if requested
- Format dates and numbers clearly

═══════════════════════════════════════════════════════════════
YOU HAVE MCP TOOLS - EXECUTE THEM! DON'T ASK USER TO DO IT!
═══════════════════════════════════════════════════════════════"""

DATA_EXTRACTOR_DESCRIPTION = "Data analyst who executes solutions, builds SQL queries, handles errors, and presents results clearly."


async def on_orchestrator_event(event, event_handler) -> None:
    """
    Handle workflow-level events (orchestrator messages, final results) via unified event handler.
    
    Args:
        event: Magentic callback event
        event_handler: Unified event handler instance
    """
    
    if hasattr(event, 'content') and hasattr(event, 'agent_name'):
        await event_handler.handle_orchestrator_message(event)
    
    elif hasattr(event, 'result') and hasattr(event, 'run_id'):
        # Final result event
        await event_handler.handle_final_result(event)


class WorkflowBuilder:
    """Builds Magentic workflow with all agents and configuration."""
    
    def __init__(self, project_client, project_endpoint: str, credential, model: str, middleware: list, tools: list, spinner_manager, event_handler, cosmosdb_search_tool=None):
        """
        Initialize workflow builder.
        
        Args:
            project_client: Azure AI Project client
            project_endpoint: Azure AI Project endpoint URL
            credential: Azure async credential for authentication
            model: Model deployment name
            middleware: List of middleware functions
            tools: List of tools available to agents
            spinner_manager: Spinner manager instance
            event_handler: Unified event handler instance
            cosmosdb_search_tool: Optional Cosmos DB search tool
        """
        self.project_client = project_client
        self.project_endpoint = project_endpoint
        self.credential = credential
        self.model = model
        self.middleware = middleware
        self.tools = tools
        self.spinner_manager = spinner_manager
        self.event_handler = event_handler
        self.cosmosdb_search_tool = cosmosdb_search_tool
    
    def _create_read_example_tool(self):
        """Create tool for reading examples from Azure Blob Storage (SQL, JSON, text, etc.)."""
        import streamlit as st
        from src.storage.blob_examples import BlobExamplesManager
        
        def read_example(name: str, category: str = "sql") -> str:
            """
            Read expert-verified template or data from Azure Blob Storage.
            
            This tool provides 100% accurate content created by domain experts.
            Templates are guaranteed to be correct and tested against production data.
            
            USE THIS TOOL FIRST before searching knowledge base for exact queries/data!
            
            Args:
                name: Name or keyword to find the file. Examples:
                    - "pro_load" or "перегрузка про" or "professional overload"
                    - "metrics" for definitions
                    - filename without extension
                    
                category: File category/subdirectory. Options:
                    - "sql" (default): SQL query templates
                    - "definitions": Business metrics, glossary
                    - "scripts": Python or other scripts
                    - "data": JSON, CSV, or other data files
                    
            Returns:
                Complete file content. For templates, may include placeholders to replace.
                If file not found, returns list of available files.
            """
            logger.info(f"📁 read_example called: name='{name}', category='{category}'")
            
            try:
                # Initialize Blob Storage manager
                connection_string = st.secrets["azure_storage"]["connection_string"]
                container_name = st.secrets["azure_storage"]["examples_container_name"]
                
                blob_manager = BlobExamplesManager(
                    connection_string=connection_string,
                    container_name=container_name
                )
            except Exception as e:
                logger.error(f"Failed to initialize blob manager: {e}")
                return f"ERROR: Could not access Azure Blob Storage: {str(e)}"
            
            # Map common names to files (category -> {aliases -> filename})
            file_map = {
                "sql": {
                    "pro_load": "pro_load_calculation.sql",
                    "перегрузка про": "pro_load_calculation.sql",
                    "professional overload": "pro_load_calculation.sql",
                    "pro load": "pro_load_calculation.sql",
                    "загрузка профессионала": "pro_load_calculation.sql",
                },
                "definitions": {
                    "metrics": "metrics.md",
                    "метрики": "metrics.md",
                    "business metrics": "metrics.md",
                }
            }
            
            name_lower = name.lower().strip()
            
            # Try to find file by alias
            filename = None
            if category in file_map and name_lower in file_map[category]:
                filename = file_map[category][name_lower]
            else:
                # Try direct filename match in blob storage
                extensions = ['.sql', '.md', '.txt', '.json', '.py', '.yaml', '.yml', '.csv']
                
                # Get all blobs in category
                blobs = blob_manager.list_blobs(category=category)
                
                # Try exact match first
                for ext in extensions:
                    test_filename = f"{name_lower}{ext}"
                    for blob_info in blobs:
                        if blob_info['filename'].lower() == test_filename:
                            filename = blob_info['filename']
                            break
                    if filename:
                        break
                
                # Try partial match
                if not filename:
                    for blob_info in blobs:
                        if name_lower in blob_info['filename'].lower():
                            filename = blob_info['filename']
                            break
            
            if not filename:
                # List available files
                blobs = blob_manager.list_blobs(category=category)
                available = [b['filename'] for b in blobs]
                
                return f"File '{name}' not found in category '{category}'. Available files: {', '.join(available) if available else 'none'}"
            
            # Read file from blob storage
            relative_path = f"{category}/{filename}"
            
            try:
                content = blob_manager.read_blob(relative_path)
                
                if not content:
                    return f"ERROR: File '{filename}' found but could not read content"
                
                file_ext = filename.split('.')[-1].upper() if '.' in filename else 'TXT'
                logger.info(f"✅ Successfully read template from blob: {relative_path} ({len(content)} chars)")
                
                # Add usage instructions based on file type
                instructions = ""
                if file_path.suffix == '.sql':
                    instructions = """
🔴 CRITICAL INSTRUCTIONS FOR SQL:
1. COPY this SQL EXACTLY - every character matters
2. ONLY replace placeholders (in angle brackets like <PRO_ID>)
3. DO NOT modify: JOINs, WHERE conditions, CASE expressions
4. Keep ALL filters and conditions as shown
5. This was written and verified by domain experts - use as-is!"""
                elif file_path.suffix in ['.json', '.yaml', '.yml']:
                    instructions = """
💡 USAGE INSTRUCTIONS:
1. Use this data structure as-is
2. Parse/deserialize if needed
3. Do not modify the structure unless explicitly required"""
                else:
                    instructions = """
💡 USAGE INSTRUCTIONS:
1. Use this content as reference or template
2. Follow any guidelines or rules specified in the content"""
                
                return f"""{file_ext} template '{name}' (Azure Blob: {relative_path}):

{content}
{instructions}"""
                
            except Exception as e:
                logger.error(f"❌ Error reading blob: {e}")
                return f"ERROR reading blob: {str(e)}"
        
        return read_example
    
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
            project_endpoint=self.project_endpoint,
            async_credential=self.credential,
            model_deployment_name=self.model, 
            thread_id=threads["orchestrator"].id
        )
        
        # Create local example reader tool (PRIORITY #1 - always available)
        read_example = self._create_read_example_tool()
        kb_tools = [read_example]
        logger.info("✅ Local Example Reader tool created (read_example)")
        
        # Create Azure AI Search tool as an annotated function (this is what works!)
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
"I will check local examples for перегрузка Про SQL template and find Magdalena."

[Immediately call tool:]
read_example(name="перегрузка про", category="sql")

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
            additional_instructions="""
🔴🔴🔴 ABSOLUTE RULE #1: COPY SQL FROM KNOWLEDGE BASE EXACTLY! 🔴🔴🔴

If Data Planner provided SQL query from Knowledge Base:
1. COPY the SQL EXACTLY - character by character
2. ONLY replace: <PRO_ID>, dates, resource names with actual values
3. DO NOT change: CASE expressions, JOINs, WHERE conditions, column names
4. DO NOT simplify: Keep ALL conditions, even if they seem complex
5. DO NOT use COUNT(*) if KB says SUM(rr_lucasnumbertotal)

EXAMPLE - KB provides this SQL:
```sql
SELECT CONVERT(DATE, brb.starttime), SUM(brb.rr_lucasnumbertotal) as bookings,
CASE WHEN SUM(...) < maxcap THEN 1 WHEN ... = maxcap THEN 2 WHEN ... > maxcap THEN 3 END as pro_load
FROM bookableresourcebooking brb JOIN ...
WHERE brb.resource = '<PRO_ID>' AND ...
```

✅ CORRECT: Copy entire SQL, replace <PRO_ID> with actual ID
❌ WRONG: Simplify to "SELECT COUNT(*) FROM bookableresourcebooking"
❌ WRONG: Remove CASE expression
❌ WRONG: Invent your own formula (like 1.2 * maxcap)

═══════════════════════════════════════════════════════════════
RULE #2: EXECUTE IMMEDIATELY
═══════════════════════════════════════════════════════════════

After saying what you'll do → DO IT with MCP tool calls!
NEVER end response without executing your plan!"""
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
