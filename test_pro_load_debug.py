"""
Debug test for 'peregruzka Pro' calculation.

This script tests each step separately to find where the problem occurs:
1. Knowledge Base search - what SQL does it return?
2. Direct SQL execution - what data comes back?
3. Compare with expected results

Run: python test_pro_load_debug.py
"""

import asyncio
import sys
import os
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Setup for streamlit secrets access
os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'

import pandas as pd
from io import StringIO

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

USER_QUESTION = 'Посчитай для профессионала "Magdalena Campos - R" значения индикатора "перегрузка Про" за сентябрь 2025 года.'


def print_section(title):
    print('\n' + '=' * 80)
    print(f' {title}')
    print('=' * 80)


async def test_knowledge_base_search():
    """Test what knowledge base returns for перегрузка Про."""
    print_section('STEP 1: Knowledge Base Search')
    
    import streamlit as st
    
    try:
        from src.search_config import get_file_search_client, get_embeddings_generator
        from src.search.client import SearchClient
        from src.tools.azure_search_tool import create_azure_search_tool
        
        file_search_client = get_file_search_client()
        embeddings_gen = get_embeddings_generator()
        
        # Create search clients
        management_companies_client = SearchClient(
            endpoint=st.secrets['azure_search']['endpoint'],
            index_name=st.secrets['azure_search']['management_companies_index_name'],
            api_key=st.secrets['azure_search']['admin_key']
        )
        
        properties_client = SearchClient(
            endpoint=st.secrets['azure_search']['endpoint'],
            index_name=st.secrets['azure_search']['properties_index_name'],
            api_key=st.secrets['azure_search']['admin_key']
        )
        
        # Create search tool
        azure_search_tool = create_azure_search_tool(
            file_search_client,
            management_companies_client,
            properties_client,
            embeddings_gen
        )
        
        # Search for перегрузка Про
        query = 'перегрузка Про индикатор формула расчёт'
        print(f'\nSearching KB for: "{query}"')
        
        result = azure_search_tool.execute(query, 'all', 10)
        
        print(f'\n--- KB Search Result ({len(result)} chars) ---')
        print(result[:3000])
        print('...' if len(result) > 3000 else '')
        
        return result
        
    except Exception as e:
        print(f'ERROR: {e}')
        import traceback
        traceback.print_exc()
        return None


async def test_mcp_sql_execution():
    """Test direct SQL execution via MCP."""
    print_section('STEP 2: MCP SQL Execution')
    
    import streamlit as st
    from src.credentials import get_mcp_token_sync
    import requests
    
    mcp_config = st.secrets.get('mcp', {})
    mcp_url = mcp_config.get('mcp_server_url')
    
    if not mcp_url:
        print('ERROR: MCP not configured')
        return None
    
    # Get MCP token
    mcp_token = get_mcp_token_sync({
        'mcp_client_id': mcp_config.get('mcp_client_id'),
        'mcp_client_secret': mcp_config.get('mcp_client_secret'),
        'AZURE_TENANT_ID': st.secrets.get('azure_ai_foundry', {}).get('tenant_id')
    })
    
    if not mcp_token:
        print('ERROR: Could not get MCP token')
        return None
    
    print(f'MCP URL: {mcp_url}')
    print(f'MCP Token: {mcp_token[:20]}...')
    
    # First, find Magdalena's ID
    print('\n--- Finding Magdalena Campos - R ---')
    
    find_sql = """
    SELECT bookableresourceid, name, rr_lucasnumber 
    FROM bookableresource 
    WHERE name LIKE '%Magdalena Campos%'
    """
    
    result = await call_mcp_execute_sql(mcp_url, mcp_token, find_sql)
    print(f'Result: {result}')
    
    # Extract bookableresourceid
    pro_id = None
    maxcap = None
    if result and 'data' in str(result):
        # Parse result to get ID
        import json
        try:
            data = json.loads(result) if isinstance(result, str) else result
            if data.get('data'):
                pro_id = data['data'][0].get('bookableresourceid')
                maxcap = data['data'][0].get('rr_lucasnumber')
                print(f'Found: ID={pro_id}, maxcap={maxcap}')
        except:
            print('Could not parse result')
    
    if not pro_id:
        # Try hardcoded ID from expected data
        pro_id = 'f7fef730-b009-ec11-b6e6-000d3a8d582c'
        maxcap = 14
        print(f'Using hardcoded ID: {pro_id}')
    
    # Now execute the CORRECT SQL from knowledge base
    print('\n--- Executing CORRECT SQL (from KB) ---')
    
    correct_sql = f"""
    SELECT 
        CONVERT(DATE, brb.starttime) as date,
        brb.resourcename,
        r.rr_lucasnumber as pro_lucas,
        SUM(brb.rr_lucasnumbertotal) as bookings_lucas,
        CASE
            WHEN SUM(brb.rr_lucasnumbertotal) IS NULL OR SUM(brb.rr_lucasnumbertotal) = 0 THEN 0
            WHEN SUM(brb.rr_lucasnumbertotal) > 0 AND SUM(brb.rr_lucasnumbertotal) < r.rr_lucasnumber THEN 1
            WHEN SUM(brb.rr_lucasnumbertotal) = r.rr_lucasnumber THEN 2
            WHEN SUM(brb.rr_lucasnumbertotal) > r.rr_lucasnumber THEN 3
        END as pro_load
    FROM bookableresourcebooking brb
        LEFT JOIN bookableresource r ON brb.resource = r.bookableresourceid
        LEFT JOIN msdyn_workorder wo ON wo.msdyn_workorderid = brb.msdyn_workorder
    WHERE 
        brb.resource = '{pro_id}'
        AND brb.starttime BETWEEN '2025-08-31' AND '2025-10-01'
        AND wo.msdyn_systemstatus IN (690970004, 690970003, 690970002, 690970001)
        AND wo.statuscode = 1
        AND wo.rr_workscheduleddate IS NOT NULL
        AND brb.bookingstatus = 'c33410b9-1abe-4631-b4e9-6e4a1113af34'
    GROUP BY 
        CONVERT(DATE, brb.starttime),
        brb.resourcename,
        r.rr_lucasnumber
    ORDER BY date
    """
    
    print(f'SQL:\n{correct_sql[:500]}...')
    
    result = await call_mcp_execute_sql(mcp_url, mcp_token, correct_sql)
    
    return result


async def call_mcp_execute_sql(mcp_url, token, sql):
    """Call MCP execute_sql tool."""
    import aiohttp
    import json
    
    # MCP tool call format
    payload = {
        'jsonrpc': '2.0',
        'method': 'tools/call',
        'params': {
            'name': 'mcp_rentready-prod_execute_sql',
            'arguments': {
                'query': sql
            }
        },
        'id': 1
    }
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(mcp_url, json=payload, headers=headers) as response:
                result = await response.text()
                print(f'Response status: {response.status}')
                
                if response.status == 200:
                    data = json.loads(result)
                    if 'result' in data:
                        return data['result']
                    return data
                else:
                    print(f'Error response: {result[:500]}')
                    return None
    except Exception as e:
        print(f'Request error: {e}')
        return None


def compare_with_expected():
    """Compare results with expected data."""
    print_section('STEP 3: Expected Data Analysis')
    
    expected_df = pd.read_csv(StringIO(EXPECTED_DATA))
    expected_df = expected_df.sort_values('date').reset_index(drop=True)
    
    print('\nExpected data:')
    print(expected_df.to_string())
    
    print('\n\nPro_load distribution:')
    print(expected_df['pro_load'].value_counts().sort_index())
    
    print('\n\nFormula verification:')
    print('pro_load should be:')
    print('  0 = bookings IS NULL OR bookings = 0')
    print('  1 = bookings > 0 AND bookings < maxcap (14)')
    print('  2 = bookings = maxcap (14)')
    print('  3 = bookings > maxcap (14)')
    
    print('\nChecking each row:')
    errors = []
    for _, row in expected_df.iterrows():
        bookings = row['bookings_lucas']
        maxcap = row['pro_lucas']
        expected_load = row['pro_load']
        
        # Calculate what pro_load should be
        if bookings is None or bookings == 0:
            calculated = 0
        elif bookings > 0 and bookings < maxcap:
            calculated = 1
        elif bookings == maxcap:
            calculated = 2
        elif bookings > maxcap:
            calculated = 3
        else:
            calculated = -1
        
        status = '✅' if calculated == expected_load else '❌'
        if calculated != expected_load:
            errors.append(row['date'])
        
        print(f"  {status} {row['date']}: bookings={bookings}, maxcap={maxcap} -> expected={expected_load}, calculated={calculated}")
    
    if errors:
        print(f'\n❌ ERRORS in expected data on dates: {errors}')
    else:
        print('\n✅ All expected data matches formula!')


async def main():
    print('=' * 80)
    print(' PRO LOAD DEBUG TEST')
    print(' Question:', USER_QUESTION)
    print('=' * 80)
    
    # Step 1: Check knowledge base
    kb_result = await test_knowledge_base_search()
    
    # Step 2: Execute SQL via MCP  
    sql_result = await test_mcp_sql_execution()
    
    # Step 3: Compare with expected
    compare_with_expected()
    
    print_section('CONCLUSIONS')
    
    if kb_result:
        if 'CASE' in kb_result and 'pro_load' in kb_result.lower():
            print('✅ Knowledge base contains correct SQL with CASE formula')
        else:
            print('❌ Knowledge base may not contain correct SQL formula')
    
    if sql_result:
        print('✅ MCP SQL execution successful')
        print(f'Result preview: {str(sql_result)[:500]}...')
    else:
        print('❌ MCP SQL execution failed or returned no data')


if __name__ == '__main__':
    asyncio.run(main())

