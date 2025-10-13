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

Based on the requirements analysis, create a step-by-step plan.

WORKFLOW ORDER:
1. START with glossary - get term definitions and table/field locations
2. THEN proceed with data analysis: facts_identifier → sql_builder → sql_validator → data_extractor

Your plan should:
- Start with glossary to clarify business terms and get table/field names
- Include specific table and field names from glossary in agent instructions
- Specify which agents are needed and in what order
- Be specific about what each agent will do

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
"""

ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT = """REQUEST: {task}

Update the requirements analysis based on what we've learned.

Current analysis:
{old_facts}

Provide UPDATED analysis using the same headings:
    1. DATA REQUIREMENTS
    2. TECHNICAL CONSTRAINTS
"""

ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT = """We need to adjust our approach.

Briefly explain what went wrong and create a NEW PLAN.

Available team: {team}

Provide a concise bullet-point plan.
"""

ORCHESTRATOR_PROGRESS_LEDGER_PROMPT = """
REQUEST: {task}
TEAM: {team}

ANSWER THESE QUESTIONS:

1. **Is the request fully satisfied?** (True only if we have final data results)

2. **Are we in a loop?** (Repeating same actions without progress)

3. **Are we making forward progress?**

4. **Who should speak next?** (select from: {names})
   - START with glossary to get term definitions and table/field info
   - THEN proceed: facts_identifier → sql_builder → sql_validator → data_extractor
   
5. **What specific instruction?**
   - For glossary: Ask about business terms in the request
   - For other agents: 
     * INCLUDE table names and field names from glossary's response
     * Include relevant context from previous agent's output
   - Be specific about what the next agent should do

Output ONLY valid JSON:

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
REQUEST: {task}

Based on the data analysis above, provide the final results.

Format data clearly (use tables, lists, or structured text).
"""