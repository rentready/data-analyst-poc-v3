"""
Knowledge Base API operations using REST API.
Handles file upload, deletion, and listing operations for Azure AI Vector Store.
"""

import logging
import tempfile
import os
import shutil
import aiohttp
from typing import List, Dict, Tuple, Optional
from azure.identity.aio import DefaultAzureCredential
from azure.ai.projects.aio import AIProjectClient

logger = logging.getLogger(__name__)


async def get_vector_store_files(vector_store_id: str, config: dict) -> List[Dict]:
    """
    Get list of files in Vector Store using REST API.
    Reference: https://learn.microsoft.com/en-us/rest/api/aifoundry/aiagents/vector-store-files/list-vector-store-files
    
    Args:
        vector_store_id: ID of the Vector Store
        config: Configuration dictionary with project endpoint
        
    Returns:
        List of file dicts with id, filename, status
    """
    try:
        async with DefaultAzureCredential() as credential:
            # Get token for authentication
            token = await credential.get_token("https://ai.azure.com/.default")
            
            # Build REST API URL
            endpoint = config.get('proj_endpoint')
            url = f"{endpoint}/vector_stores/{vector_store_id}/files?api-version=v1"
            
            # Make HTTP request
            headers = {
                'Authorization': f'Bearer {token.token}',
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        files = []
                        
                        # Process each file from response
                        for file_data in data.get('data', []):
                            # Get full file details to get filename
                            file_id = file_data.get('id')
                            file_url = f"{endpoint}/files/{file_id}?api-version=v1"
                            
                            async with session.get(file_url, headers=headers) as file_response:
                                if file_response.status == 200:
                                    file_details = await file_response.json()
                                    filename = file_details.get('filename', '')
                                    logger.info(f'Extracted filename for {file_id}: "{filename}"')
                                    
                                    if not filename:
                                        filename = f'File {file_id[:8]}...'
                                        logger.warning(f'Filename is empty, using fallback: {filename}')
                                    
                                    files.append({
                                        'id': file_id,
                                        'filename': filename,
                                        'status': file_data.get('status', 'unknown')
                                    })
                                else:
                                    # Fallback if can't get filename
                                    logger.warning(f'GET /files/{file_id} failed with status {file_response.status}')
                                    files.append({
                                        'id': file_id,
                                        'filename': f'File {file_id[:8]}...',
                                        'status': file_data.get('status', 'unknown')
                                    })
                        
                        return files
                    else:
                        logger.error(f'Failed to list files: HTTP {response.status}')
                        return []
    
    except Exception as e:
        logger.error(f'Failed to list vector store files: {e}')
        return []


async def upload_file_to_vector_store(
    file_data: bytes, 
    filename: str, 
    vector_store_id: str, 
    config: dict
) -> Tuple[str, str]:
    """
    Upload file to AI Project and add to Vector Store.
    Uses Python SDK for file upload (properly handles filename) and REST API for adding to Vector Store.
    
    Args:
        file_data: File content as bytes
        filename: Name of the file
        vector_store_id: ID of the Vector Store
        config: Configuration dictionary with project endpoint
        
    Returns:
        Tuple of (file_id, vector_store_file_id)
    """
    temp_file_path = None
    try:
        endpoint = config.get('proj_endpoint')
        async with DefaultAzureCredential() as credential:
            async with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
                # Step 1: Save file temporarily (SDK requires file path, not BytesIO)
                temp_dir = tempfile.mkdtemp()
                temp_file_path = os.path.join(temp_dir, filename)
                with open(temp_file_path, 'wb') as temp_file:
                    temp_file.write(file_data)
                
                # Step 2: Upload file to AI Project using SDK
                uploaded_file = await project_client.agents.files.upload_and_poll(
                    file_path=temp_file_path,
                    purpose='assistants'
                )
                
                file_id = uploaded_file.id
                logger.info(f'Uploaded file to AI Project: {file_id}, filename: {uploaded_file.filename}')
                
                # Step 3: Add file to Vector Store using REST API
                token = await credential.get_token("https://ai.azure.com/.default")
                vs_file_url = f"{endpoint}/vector_stores/{vector_store_id}/files?api-version=v1"
                
                headers = {
                    'Authorization': f'Bearer {token.token}',
                    'Content-Type': 'application/json'
                }
                
                payload = {'file_id': file_id}
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(vs_file_url, headers=headers, json=payload) as response:
                        if response.status == 200:
                            vs_file_info = await response.json()
                            logger.info(f'Added file {file_id} to vector store {vector_store_id}')
                            return file_id, vs_file_info.get('id')
                        else:
                            error_text = await response.text()
                            logger.error(f'Failed to add file to vector store: HTTP {response.status}, {error_text}')
                            raise Exception(f'Failed to add file to vector store: HTTP {response.status}')
    
    except Exception as e:
        logger.error(f'Failed to upload file to vector store: {e}')
        raise
    finally:
        # Clean up temporary file and directory
        if temp_file_path:
            try:
                temp_dir = os.path.dirname(temp_file_path)
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.debug(f'Cleaned up temporary directory: {temp_dir}')
            except Exception as e:
                logger.warning(f'Failed to clean up temporary directory: {e}')


async def delete_file_from_vector_store(filename: str, vector_store_id: str, config: dict) -> bool:
    """
    Delete file from Vector Store by filename.
    
    Args:
        filename: Name of the file to delete
        vector_store_id: ID of the Vector Store
        config: Configuration dictionary with project endpoint
        
    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        async with DefaultAzureCredential() as credential:
            # Get token for authentication
            token = await credential.get_token("https://ai.azure.com/.default")
            
            # Build REST API URL
            endpoint = config.get('proj_endpoint')
            
            headers = {
                'Authorization': f'Bearer {token.token}',
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                # Step 1: List all files in vector store
                list_url = f"{endpoint}/vector_stores/{vector_store_id}/files?api-version=v1"
                
                async with session.get(list_url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f'Failed to list files: HTTP {response.status}')
                        return False
                    
                    data = await response.json()
                    files = data.get('data', [])
                
                # Step 2: Find file by name
                file_id_to_delete = None
                for file_data in files:
                    file_id = file_data.get('id')
                    file_url = f"{endpoint}/files/{file_id}?api-version=v1"
                    
                    async with session.get(file_url, headers=headers) as response:
                        if response.status == 200:
                            file_details = await response.json()
                            if file_details.get('filename') == filename:
                                file_id_to_delete = file_id
                                break
                
                if not file_id_to_delete:
                    logger.warning(f'File {filename} not found in vector store')
                    return False
                
                # Step 3: Delete from vector store
                delete_vs_url = f"{endpoint}/vector_stores/{vector_store_id}/files/{file_id_to_delete}?api-version=v1"
                
                async with session.delete(delete_vs_url, headers=headers) as response:
                    if response.status in [200, 204]:
                        logger.info(f'Deleted file {file_id_to_delete} ({filename}) from vector store')
                    else:
                        logger.error(f'Failed to delete from vector store: HTTP {response.status}')
                        return False
                
                # Step 4: Delete file from AI Project
                delete_file_url = f"{endpoint}/files/{file_id_to_delete}?api-version=v1"
                
                async with session.delete(delete_file_url, headers=headers) as response:
                    if response.status in [200, 204]:
                        logger.info(f'Deleted file {file_id_to_delete} from AI Project')
                        return True
                    else:
                        logger.warning(f'Failed to delete file from AI Project: HTTP {response.status}')
                        # Still return True as it was removed from vector store
                        return True
    
    except Exception as e:
        logger.error(f'Failed to delete file from vector store: {e}')
        return False

