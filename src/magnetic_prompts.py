# region Data Analyst Specialized Prompts

ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT = """You are a professional data analyst working on a data request.

Below is the user's request:

{task}

Before we begin, let's understand what we know and what we need to find out. Please analyze the request and provide:

    1. DATA REQUIREMENTS - What specific data points, metrics, or insights are being requested?
       List any explicit requirements mentioned in the request.
    
    2. TECHNICAL CONSTRAINTS - What constraints or requirements are there?
       - Time periods, filters, aggregations mentioned
       - Specific entities (IDs, names, categories) referenced
       - Any performance or format requirements

Your answer MUST use EXACTLY these headings:

    1. DATA REQUIREMENTS
    2. TECHNICAL CONSTRAINTS

DO NOT include any other headings or sections. DO NOT suggest plans or next steps yet.
"""

ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT = """Good. Now let's create a data analysis plan.

We have assembled the following team:

{team}

Based on the requirements analysis, create a step-by-step plan following professional data analyst methodology:

TYPICAL DATA ANALYST WORKFLOW:
1. **Query Design** - Sql Builder builds query, validates presense of every field and table by queries TOP 1 using MCP Tools.
2. **Validation** - Sql Validator receives the SQL, validates it, and returns IMPROVED SQL with feedback/comments
3. **Execution** - Data Extractor receives the validated SQL and executes it

CRITICAL SQL HANDOFF REQUIREMENTS:
- Sql Builder MUST output pure SQL (no explanations) as final message
- Sql Validator MUST receive that SQL, validate it, and return improved SQL with comments
- Data Extractor MUST receive the validated SQL to execute
- Each agent receives SQL from previous agent and outputs improved version

Your plan should:
- Be specific about what each team member will do
- Explicitly mention SQL handoff between agents
- Reference actual tools available (MCP tools for database access)
- Include validation steps before executing queries
- Emphasize examining real data before making assumptions
- Only involve team members whose expertise is actually needed

Provide a concise bullet-point plan.
"""

# Added to render the ledger in a single assistant message, mirroring the original behavior.
ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT = """
We are working on the following DATA ANALYSIS REQUEST:

{task}


Our DATA ANALYST TEAM:

{team}


REQUIREMENTS ANALYSIS:

{facts}


DATA ANALYSIS PLAN:

{plan}


IMPORTANT REMINDERS:
- Validate all queries before execution
- Use MCP tools to explore data sources and validate assumptions
- Don't guess field names or table structures - look them up

CRITICAL SQL HANDOFF PROTOCOL:
- sql_builder outputs ONLY pure SQL (no explanations)
- sql_validator receives SQL, validates, returns IMPROVED SQL with feedback
- data_extractor receives validated SQL and executes it
- Always pass SQL explicitly between agents in your instructions
"""

ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT = """As a reminder, we are working on this DATA ANALYSIS REQUEST:

{task}

We've made some progress but need to update our understanding based on what we've learned.

Please update the requirements analysis with any new information we've discovered:

WHAT TO UPDATE:
- Move database exploration findings to verified requirements
- Update field names, table structures we've confirmed
- Add any data quality issues or constraints discovered
- Refine assumptions based on actual data samples seen
- Add technical details learned from MCP tools

Here is the current requirements analysis:

{old_facts}

Provide the UPDATED requirements analysis using the same headings:
    1. DATA REQUIREMENTS
    2. TECHNICAL CONSTRAINTS
"""

ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT = """We need to adjust our data analysis approach.

First, briefly explain what went wrong:
- What was the root cause of the issue?
- Was it a query error, missing data exploration, incorrect assumptions, or validation failure?

Then create a NEW PLAN that:
- Addresses the specific problem identified
- Includes more thorough data exploration if assumptions were wrong
- Adds validation steps if queries failed
- Emphasizes using MCP tools to verify before proceeding
- Avoids repeating the same mistakes

Available team:

{team}

Common data analyst mistakes to avoid:
- Writing queries without checking actual schema first
- Assuming field names instead of looking them up
- Skipping validation before execution
- Not sampling data to understand structure

Provide a concise bullet-point plan.
"""

ORCHESTRATOR_PROGRESS_LEDGER_PROMPT = """
We are working on this DATA ANALYSIS REQUEST:

{task}

Our DATA ANALYST TEAM:

{team}

Evaluate our progress following professional data analyst methodology:

ANSWER THESE QUESTIONS:

1. **Is the request fully satisfied?**
   - Have we successfully extracted and returned the requested data?
   - True only if we have actual data results that answer the user's question
   - False if we're still exploring, building queries, or validating

2. **Are we in a loop?**
   - Are we repeating the same actions without new information?
   - Are we making the same errors repeatedly?
   - Are we stuck trying the same approach that keeps failing?

3. **Are we making forward progress?**
   - True if: exploring new data sources, validating queries, fixing errors based on feedback
   - False if: repeating same mistakes, not using validation tools, ignoring error messages
   - Consider the data analyst workflow: Discovery → Query Design → Validation → Execution

4. **Who should speak next?** (select from: {names})
   TYPICAL PROGRESSION & SQL HANDOFF:
   - **sql_builder** creates query → outputs ONLY pure SQL (no explanations)
   - **sql_validator** receives that SQL → validates and returns IMPROVED SQL with feedback/comments
   - **data_extractor** receives validated SQL → executes it and returns results
   
   CRITICAL: When calling the next agent, always reference the SQL from the previous agent!
   
5. **What specific instruction?**
   - Be explicit about what to do and what tools to use
   - **ALWAYS include the SQL** from previous agent's output in your instruction
   - For sql_builder: "Build a query and return ONLY the SQL"
   - For sql_validator: "Here is the SQL: [paste SQL]. Validate it and return improved SQL with comments"
   - For data_extractor: "Here is the validated SQL: [paste SQL]. Execute it and return results"
   - Reference specific findings from previous steps
   - Emphasize examining actual data before making assumptions

Output ONLY valid JSON following this schema exactly:

{{
    "is_request_satisfied": {{
        "reason": string,
        "answer": boolean
    }},
    "is_in_loop": {{
        "reason": string,
        "answer": boolean
    }},
    "is_progress_being_made": {{
        "reason": string,
        "answer": boolean
    }},
    "next_speaker": {{
        "reason": string,
        "answer": string (must be one of: {names})
    }},
    "instruction_or_question": {{
        "reason": string,
        "answer": string
    }}
}}
"""

ORCHESTRATOR_FINAL_ANSWER_PROMPT = """
DATA ANALYSIS REQUEST:
{task}

The data analysis is complete.

The above conversation shows the work performed by the data analyst team:
- SQL query development
- Query validation
- Data extraction

Based on the data gathered and analyzed, provide the data extracted results.

Format data in a clear, readable way (use tables, lists, or structured text as appropriate).
"""