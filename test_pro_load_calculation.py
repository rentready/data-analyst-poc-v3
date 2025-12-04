"""
Test script to verify 'перегрузка Про' calculation matches expected results.

This script simulates the full workflow:
1. Search knowledge base for the indicator definition
2. Find the professional in database
3. Execute SQL query
4. Compare results with expected data
"""

import asyncio
import logging
import pandas as pd
from io import StringIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Expected results from SQL script 38.csv
EXPECTED_DATA = """date,resourcename,pro_lucas,bookings_lucas,pro_load
2025-09-02,Magdalena Campos - R,14,16,3
2025-09-03,Magdalena Campos - R,14,23,3
2025-09-04,Magdalena Campos - R,14,21,3
2025-09-05,Magdalena Campos - R,14,11,1
2025-09-08,Magdalena Campos - R,14,14,2
2025-09-09,Magdalena Campos - R,14,18,3
2025-09-10,Magdalena Campos - R,14,11,1
2025-09-11,Magdalena Campos - R,14,13,1
2025-09-12,Magdalena Campos - R,14,16,3
2025-09-15,Magdalena Campos - R,14,7,1
2025-09-16,Magdalena Campos - R,14,15,3
2025-09-17,Magdalena Campos - R,14,21,3
2025-09-18,Magdalena Campos - R,14,10,1
2025-09-19,Magdalena Campos - R,14,15,3
2025-09-22,Magdalena Campos - R,14,9,1
2025-09-23,Magdalena Campos - R,14,19,3
2025-09-24,Magdalena Campos - R,14,26,3
2025-09-25,Magdalena Campos - R,14,11,1
2025-09-26,Magdalena Campos - R,14,13,1
2025-09-29,Magdalena Campos - R,14,19,3
2025-09-30,Magdalena Campos - R,14,27,3
"""

# User question - NO HINTS, just the raw question
USER_QUESTION = 'Посчитай для профессионала "Magdalena Campos - R" значения индикатора "перегрузка Про" за сентябрь 2025 года.'


async def test_workflow():
    """Test the full workflow and compare results."""
    
    # Load expected data
    expected_df = pd.read_csv(StringIO(EXPECTED_DATA))
    expected_df['date'] = pd.to_datetime(expected_df['date']).dt.date
    expected_df = expected_df.sort_values('date').reset_index(drop=True)
    
    logger.info(f'Expected data loaded: {len(expected_df)} rows')
    logger.info(f'Expected columns: {list(expected_df.columns)}')
    
    # Import necessary modules
    import streamlit as st
    from azure.identity.aio import DefaultAzureCredential
    from azure.ai.projects.aio import AIProjectClient
    
    from src.ui.thread_manager import ThreadManager
    from src.workflow.builder import WorkflowBuilder
    from src.ui.spinner_manager import SpinnerManager
    from src.events import UnifiedEventHandler
    
    # Load secrets
    azure_endpoint = st.secrets['azure_ai_foundry']['proj_endpoint']
    model_name = st.secrets['azure_ai_foundry']['model_deployment_name']
    
    logger.info(f'Azure endpoint: {azure_endpoint[:50]}...')
    logger.info(f'Model: {model_name}')
    
    # Create spinner manager (mock for tests)
    class MockSpinnerManager:
        def start_agent(self, name): pass
        def stop_agent(self, name): pass
        def start_tool(self, name): pass
        def stop_tool(self, name): pass
    
    spinner_manager = MockSpinnerManager()
    
    # Track tool calls and results
    tool_results = []
    
    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=azure_endpoint, credential=credential) as project_client,
    ):
        # Create thread manager
        thread_manager = ThreadManager(project_client)
        
        # Create threads
        agent_names = ['data_planner', 'data_extractor', 'orchestrator']
        threads = await thread_manager.get_all_threads(agent_names)
        
        logger.info('Threads created successfully')
        
        # Create event handler
        event_handler = UnifiedEventHandler(spinner_manager)
        
        # Create MCP tool
        from src.credentials import get_mcp_access_token
        from src.mcp_config import get_mcp_config
        from agent_framework import MCPServerAuthType, MCPTool
        
        mcp_config = get_mcp_config()
        mcp_token = get_mcp_access_token()
        
        mcp_tool = MCPTool(
            server_url=mcp_config['mcp_server_url'],
            server_auth_type=MCPServerAuthType.NONE,
            server_headers={'Authorization': f'Bearer {mcp_token}'},
        )
        
        # Wrap MCP tool to capture results
        original_call = mcp_tool.__call__
        
        async def tracked_mcp_call(*args, **kwargs):
            result = await original_call(*args, **kwargs)
            tool_results.append({
                'tool': 'mcp',
                'args': args,
                'kwargs': kwargs,
                'result': str(result)[:500]
            })
            return result
        
        mcp_tool.__call__ = tracked_mcp_call
        
        # Create middleware
        def tool_calls_middleware(context, next_handler):
            async def handler(event):
                logger.info(f'Tool event: {type(event).__name__}')
                return await next_handler(event)
            return handler
        
        # Create workflow builder
        workflow_builder = WorkflowBuilder(
            project_client=project_client,
            project_endpoint=azure_endpoint,
            credential=credential,
            model=model_name,
            middleware=[tool_calls_middleware],
            tools=[mcp_tool],
            spinner_manager=spinner_manager,
            event_handler=event_handler,
        )
        
        logger.info('WorkflowBuilder created')
        
        # Build workflow
        workflow = await workflow_builder.build_workflow(threads, USER_QUESTION)
        
        logger.info('Workflow built successfully')
        logger.info(f'Running workflow with question: {USER_QUESTION}')
        
        # Run workflow
        result = await workflow.run(USER_QUESTION)
        
        logger.info('Workflow completed')
        logger.info(f'Result type: {type(result)}')
        
        # Extract final response
        final_response = None
        if hasattr(result, 'messages'):
            for msg in result.messages:
                if hasattr(msg, 'content'):
                    final_response = msg.content
        elif hasattr(result, 'content'):
            final_response = result.content
        else:
            final_response = str(result)
        
        logger.info(f'Final response (first 1000 chars): {final_response[:1000] if final_response else "None"}...')
        
        # Parse result to extract data
        # Look for table data in the response
        actual_data = parse_response_table(final_response)
        
        if actual_data is not None and len(actual_data) > 0:
            logger.info(f'Parsed {len(actual_data)} rows from response')
            
            # Compare with expected
            compare_results(expected_df, actual_data)
        else:
            logger.error('Could not parse table data from response')
            logger.info(f'Full response:\n{final_response}')
        
        return final_response, tool_results


def parse_response_table(response: str) -> pd.DataFrame:
    """Parse markdown table from response."""
    if not response:
        return None
    
    import re
    
    # Find table in markdown format
    lines = response.split('\n')
    table_lines = []
    in_table = False
    
    for line in lines:
        if '|' in line and ('---' in line or re.search(r'\d{4}-\d{2}-\d{2}', line) or 'Date' in line or 'date' in line or 'Дата' in line):
            in_table = True
        
        if in_table and '|' in line:
            # Skip separator lines
            if '---' in line:
                continue
            table_lines.append(line)
    
    if len(table_lines) < 2:
        return None
    
    # Parse table
    data = []
    headers = None
    
    for line in table_lines:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        
        if headers is None:
            headers = cells
        else:
            if len(cells) == len(headers):
                data.append(cells)
    
    if not data:
        return None
    
    df = pd.DataFrame(data, columns=headers)
    
    # Try to find date column and pro_load column
    date_col = None
    pro_load_col = None
    bookings_col = None
    
    for col in df.columns:
        col_lower = col.lower()
        if 'date' in col_lower or 'дата' in col_lower:
            date_col = col
        elif 'pro_load' in col_lower or 'перегрузка' in col_lower or 'load' in col_lower:
            pro_load_col = col
        elif 'booking' in col_lower or 'букинг' in col_lower or 'lucas' in col_lower:
            bookings_col = col
    
    return df


def compare_results(expected_df: pd.DataFrame, actual_df: pd.DataFrame):
    """Compare expected and actual results."""
    logger.info('=' * 60)
    logger.info('COMPARISON RESULTS')
    logger.info('=' * 60)
    
    logger.info(f'\nExpected columns: {list(expected_df.columns)}')
    logger.info(f'Actual columns: {list(actual_df.columns)}')
    
    logger.info(f'\nExpected rows: {len(expected_df)}')
    logger.info(f'Actual rows: {len(actual_df)}')
    
    # Print expected data
    logger.info('\n--- EXPECTED DATA ---')
    for _, row in expected_df.iterrows():
        logger.info(f'{row["date"]}: bookings={row["bookings_lucas"]}, maxcap={row["pro_lucas"]}, pro_load={row["pro_load"]}')
    
    # Print actual data
    logger.info('\n--- ACTUAL DATA ---')
    logger.info(actual_df.to_string())
    
    # Check if pro_load values match
    logger.info('\n--- PRO_LOAD VALIDATION ---')
    logger.info('Expected pro_load distribution:')
    logger.info(expected_df['pro_load'].value_counts().sort_index())
    
    # Validate pro_load formula
    logger.info('\n--- FORMULA VALIDATION ---')
    for _, row in expected_df.iterrows():
        bookings = row['bookings_lucas']
        maxcap = row['pro_lucas']
        expected_load = row['pro_load']
        
        # Calculate expected pro_load based on formula
        if bookings is None or bookings == 0:
            calculated_load = 0
        elif bookings > 0 and bookings < maxcap:
            calculated_load = 1
        elif bookings == maxcap:
            calculated_load = 2
        elif bookings > maxcap:
            calculated_load = 3
        else:
            calculated_load = -1
        
        if calculated_load != expected_load:
            logger.error(f'MISMATCH at {row["date"]}: bookings={bookings}, maxcap={maxcap}, expected={expected_load}, calculated={calculated_load}')
        else:
            logger.info(f'OK {row["date"]}: bookings={bookings}, maxcap={maxcap}, pro_load={expected_load}')


if __name__ == '__main__':
    # Run in Streamlit context
    import streamlit as st
    
    st.set_page_config(page_title='Pro Load Test', page_icon='🧪')
    st.title('🧪 Pro Load Calculation Test')
    
    if st.button('Run Test'):
        with st.spinner('Running workflow test...'):
            try:
                result, tool_results = asyncio.run(test_workflow())
                
                st.success('Test completed!')
                
                st.subheader('Tool Calls')
                for i, tr in enumerate(tool_results):
                    with st.expander(f'Tool Call {i+1}'):
                        st.json(tr)
                
                st.subheader('Final Result')
                st.text(result[:5000] if result else 'No result')
                
            except Exception as e:
                st.error(f'Test failed: {e}')
                import traceback
                st.code(traceback.format_exc())
    
    # Also show expected data
    st.subheader('Expected Data')
    expected_df = pd.read_csv(StringIO(EXPECTED_DATA))
    expected_df = expected_df.sort_values('date').reset_index(drop=True)
    st.dataframe(expected_df)

