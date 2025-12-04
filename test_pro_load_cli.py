"""
CLI Test script to verify 'перегрузка Про' calculation.

Run with: streamlit run test_pro_load_cli.py --server.port 8505
"""

import asyncio
import logging
import pandas as pd
from io import StringIO
import sys
import os
import streamlit as st

st.set_page_config(page_title='Pro Load Test', page_icon='🧪', layout='wide')

import datetime

# Setup file logging
log_file = f'test_log_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info(f'Logging to file: {log_file}')

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


async def run_test():
    """Run the full workflow test."""
    
    status = st.status('Running test...', expanded=True)
    
    # Load expected data
    expected_df = pd.read_csv(StringIO(EXPECTED_DATA))
    expected_df['date'] = pd.to_datetime(expected_df['date']).dt.date
    expected_df = expected_df.sort_values('date').reset_index(drop=True)
    
    status.write(f'✅ Expected data loaded: {len(expected_df)} rows')
    
    # Import necessary modules
    from azure.identity.aio import DefaultAzureCredential
    from azure.ai.projects.aio import AIProjectClient
    
    from src.ui.thread_manager import ThreadManager
    from src.workflow.builder import WorkflowBuilder
    from src.middleware.spinner_manager import SpinnerManager
    
    # Load secrets
    azure_endpoint = st.secrets['azure_ai_foundry']['proj_endpoint']
    model_name = st.secrets['azure_ai_foundry']['model_deployment_name']
    
    status.write(f'✅ Config loaded: {model_name}')
    
    # Create spinner manager
    spinner_manager = SpinnerManager()
    
    # Mock event handler
    class MockEventHandler:
        def __init__(self): pass
        async def handle_orchestrator_message(self, event): pass
        async def handle_final_result(self, event): pass
    
    event_handler = MockEventHandler()
    
    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=azure_endpoint, credential=credential) as project_client,
    ):
        status.write('✅ Azure client connected')
        
        # Create thread manager
        thread_manager = ThreadManager(project_client)
        
        # Create threads
        agent_names = ['data_planner', 'data_extractor', 'orchestrator']
        threads = await thread_manager.get_all_threads(agent_names)
        
        status.write('✅ Threads created')
        
        # Create MCP tool
        from src.credentials import get_mcp_token_sync
        from agent_framework import HostedMCPTool
        
        mcp_config = st.secrets.get('mcp', {})
        mcp_tools = []
        
        mcp_url = mcp_config.get('mcp_server_url')
        if mcp_url:
            mcp_token = get_mcp_token_sync({
                'mcp_client_id': mcp_config.get('mcp_client_id'),
                'mcp_client_secret': mcp_config.get('mcp_client_secret'),
                'AZURE_TENANT_ID': st.secrets.get('azure_ai_foundry', {}).get('tenant_id')
            })
            
            mcp_tool = HostedMCPTool(
                name=mcp_config.get('mcp_server_label', 'rentready_mcp'),
                url=mcp_url,
                approval_mode='never_require',
                allowed_tools=mcp_config.get('allowed_tools', []),
                headers={'Authorization': f'Bearer {mcp_token}'} if mcp_token else {},
            )
            mcp_tools.append(mcp_tool)
            status.write(f'✅ MCP tool created: {mcp_url[:50]}...')
            logger.info(f'MCP tool created: {mcp_url}')
        else:
            status.write('⚠️ MCP not configured, skipping')
            logger.warning('MCP not configured')
        
        # Create workflow builder
        workflow_builder = WorkflowBuilder(
            project_client=project_client,
            project_endpoint=azure_endpoint,
            credential=credential,
            model=model_name,
            middleware=[],
            tools=mcp_tools,
            spinner_manager=spinner_manager,
            event_handler=event_handler,
        )
        
        status.write('✅ WorkflowBuilder created')
        
        # Build workflow
        workflow = await workflow_builder.build_workflow(threads, USER_QUESTION)
        
        status.write('✅ Workflow built')
        status.write(f'🚀 Running workflow with: {USER_QUESTION}')
        
        # Run workflow with logging
        logger.info('Starting workflow.run()...')
        result = await workflow.run(USER_QUESTION)
        logger.info(f'Workflow completed. Result type: {type(result)}')
        logger.info(f'Result: {str(result)[:2000]}')
        
        status.write('✅ Workflow completed!')
        status.update(label='Test completed!', state='complete', expanded=False)
        
        # Extract final response
        final_response = None
        if hasattr(result, 'value'):
            final_response = str(result.value)
        elif hasattr(result, 'messages'):
            for msg in result.messages:
                if hasattr(msg, 'content'):
                    final_response = msg.content
        else:
            final_response = str(result)
        
        return final_response, expected_df


def main():
    st.title('🧪 Pro Load Calculation Test')
    
    st.markdown(f'''
    **Question:** {USER_QUESTION}
    
    This test runs the full workflow and compares results with expected data.
    ''')
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader('Expected Data')
        expected_df = pd.read_csv(StringIO(EXPECTED_DATA))
        expected_df = expected_df.sort_values('date').reset_index(drop=True)
        st.dataframe(expected_df, use_container_width=True)
        
        st.markdown('''
        **Pro Load Categories:**
        - 0 = No bookings
        - 1 = Low load (bookings < maxcap)
        - 2 = Medium load (bookings = maxcap)
        - 3 = Overload (bookings > maxcap)
        ''')
    
    with col2:
        st.subheader('Test Results')
        
        if st.button('▶️ Run Test', type='primary', use_container_width=True):
            try:
                result, expected = asyncio.run(run_test())
                
                st.success('Test completed!')
                
                st.markdown('### Final Response')
                st.text_area('Response', result[:5000] if result else 'No result', height=400)
                
            except Exception as e:
                st.error(f'Test failed: {e}')
                import traceback
                st.code(traceback.format_exc())


if __name__ == '__main__':
    main()
