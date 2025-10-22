"""Agent configurations for the data analyst workflow."""

from dataclasses import dataclass
from typing import Optional

@dataclass
class AgentConfig:
    """Configuration for a single agent."""
    name: str
    description: str
    instructions: str
    additional_instructions: str
    temperature: float = 0.1
    user: Optional[str] = None

# Facts Identifier Agent Configuration
FACTS_IDENTIFIER_CONFIG = AgentConfig(
    name="Facts Identifier",
    description="Use MCP Tools to find every entity (IDs, names, values) for the user request which is not covered by the glossary. Search for entities by name using progressive matching: 1) Exact match first, 2) Then partial/LIKE match, 3) Then similar names, 4) Take larger datasets. Execute SELECT TOP XXX to validate found entities.",
    instructions="""for the user request: {prompt}

Identify tables and fields by using MCP Tools. When searching for specific entities (property names, market names, etc.), use progressive matching strategy:
1. Try exact match first (WHERE name = 'value')
2. If not found, try partial match (WHERE name LIKE '%value%')
3. If still not found, try similar names

Refine fields and tables by sampling data using SELECT TOP 1 [fields] FROM [table] and make it return requested values before finishing your response.

You will justify what tools you are going to use before requesting them.""",
    additional_instructions="Annotate what you want before using MCP Tools. Always use MCP Tools before returning response. Use MCP Tools to identify tables and fields. Ensure that you found requested rows by sampling data using SELECT TOP 1 [fields] FROM [table]. Never generate anything on your own.",
    temperature=0.1
)

# SQL Builder Agent Configuration
SQL_BUILDER_CONFIG = AgentConfig(
    name="SQL Builder",
    user="sql_builder",
    description="Use this tool when all data requirements and facts are extracted, all referenced entities are identified, fields and tables are known. Use this tool to pass known table names, fields and filters and ask to construct an SQL query to address user's request and ensure it works as expected by executing MCP Tools with SELECT ....",
    instructions="""You construct SQL queries per user request. You always use MCP Tools to validate your query and never generate anything on your own.
You will justify what tools you are going to use before requesting them.
OUTPUT FORMAT:
** SQL Query **
```sql
{sql_query}
```
** Data Sample **
```
{real_data_sample}
```
** Feedback **
```
{your assumptions, validation notes, or questions}
```
""",
    additional_instructions="Annotate what you want before using MCP Tools. Use MCP tools to validate tables and fields by executing SELECT TOP 1 before building the final query.",
    temperature=0.1
)

# Data Extractor Agent Configuration
DATA_EXTRACTOR_CONFIG = AgentConfig(
    name="Data Extractor",
    description="Use this tool when SQL query is validated and succeeded to extract data.",
    instructions="""Execute SQL queries using MCP tools and return formatted results.

OUTPUT FORMAT:
Present data in tables or structured format.""",
    additional_instructions="Use MCP tools to execute the SQL query. Present results clearly.",
    temperature=0.1
)

# Glossary Agent Configuration
GLOSSARY_CONFIG = AgentConfig(
    name="Glossary",
    description="Business terminology and definitions reference",
    instructions="",  # Will be loaded from secrets.toml
    additional_instructions="Answer concisely and clearly. Focus on practical business context.",
    temperature=0.1
)
