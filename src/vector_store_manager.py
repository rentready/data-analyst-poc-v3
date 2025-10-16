"""Vector Store manager for File Search Tool."""

import logging
from typing import List, Optional, BinaryIO, Tuple
from azure.ai.projects.aio import AIProjectClient

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """Manage vector stores for file search."""
    
    def __init__(self, project_client: AIProjectClient):
        """
        Initialize Vector Store manager.
        
        Args:
            project_client: Azure AI Project client instance
        """
        self.project_client = project_client
    
    async def create_vector_store(self, name: str, file_ids: Optional[List[str]] = None):
        """
        Create a vector store.
        
        Args:
            name: Name for the vector store
            file_ids: Optional list of file IDs to add to the vector store
            
        Returns:
            Created vector store object
        """
        vector_store = await self.project_client.agents.create_vector_store_and_poll(
            name=name,
            file_ids=file_ids or []
        )
        logger.info(f'Created vector store: {vector_store.id} with name: {name}')
        return vector_store
    
    async def upload_file_to_project(self, file_path: str, purpose: str = 'assistants') -> str:
        """
        Upload file to AI Project from local path.
        
        Args:
            file_path: Local file path
            purpose: Purpose of the file (default: 'assistants')
            
        Returns:
            File ID in the project
        """
        with open(file_path, 'rb') as file_data:
            uploaded_file = await self.project_client.agents.upload_file_and_poll(
                file_path=file_path,
                purpose=purpose
            )
        logger.info(f'Uploaded file to project: {uploaded_file.id}')
        return uploaded_file.id
    
    async def upload_stream_to_project(self, data: bytes, filename: str, purpose: str = 'assistants') -> str:
        """
        Upload file stream to AI Project.
        
        Args:
            data: File data as bytes
            filename: Name for the file
            purpose: Purpose of the file (default: 'assistants')
            
        Returns:
            File ID in the project
        """
        import io
        file_stream = io.BytesIO(data)
        
        uploaded_file = await self.project_client.agents.upload_file_and_poll(
            data=file_stream,
            purpose=purpose,
            file_name=filename
        )
        logger.info(f'Uploaded stream to project: {uploaded_file.id} (filename: {filename})')
        return uploaded_file.id
    
    async def add_file_to_vector_store(self, vector_store_id: str, file_id: str):
        """
        Add file to existing vector store.
        
        Args:
            vector_store_id: ID of the vector store
            file_id: ID of the file to add
            
        Returns:
            Vector store file object
        """
        vector_store_file = await self.project_client.agents.create_vector_store_file_and_poll(
            vector_store_id=vector_store_id,
            file_id=file_id
        )
        logger.info(f'Added file {file_id} to vector store {vector_store_id}')
        return vector_store_file
    
    async def create_vector_store_with_files(self, name: str, file_paths: List[str]):
        """
        Create vector store and upload multiple files from local paths.
        
        Args:
            name: Name for the vector store
            file_paths: List of local file paths to upload
            
        Returns:
            Created vector store object
        """
        # Upload files first
        file_ids = []
        for file_path in file_paths:
            file_id = await self.upload_file_to_project(file_path)
            file_ids.append(file_id)
        
        # Create vector store with files
        vector_store = await self.create_vector_store(name=name, file_ids=file_ids)
        
        logger.info(f'Created vector store {vector_store.id} with {len(file_ids)} files')
        return vector_store
    
    async def create_vector_store_with_streams(self, name: str, files: List[Tuple[bytes, str]]):
        """
        Create vector store and upload multiple files from byte streams.
        
        Args:
            name: Name for the vector store
            files: List of tuples (file_data, filename)
            
        Returns:
            Created vector store object
        """
        # Upload files first
        file_ids = []
        for file_data, filename in files:
            file_id = await self.upload_stream_to_project(file_data, filename)
            file_ids.append(file_id)
        
        # Create vector store with files
        vector_store = await self.create_vector_store(name=name, file_ids=file_ids)
        
        logger.info(f'Created vector store {vector_store.id} with {len(file_ids)} files from streams')
        return vector_store
    
    async def list_vector_stores(self):
        """
        List all vector stores.
        
        Returns:
            List of vector store objects
        """
        stores = await self.project_client.agents.list_vector_stores()
        return list(stores)
    
    async def get_vector_store(self, vector_store_id: str):
        """
        Get vector store by ID.
        
        Args:
            vector_store_id: ID of the vector store
            
        Returns:
            Vector store object
        """
        return await self.project_client.agents.get_vector_store(vector_store_id)
    
    async def delete_vector_store(self, vector_store_id: str) -> None:
        """
        Delete vector store.
        
        Args:
            vector_store_id: ID of the vector store to delete
        """
        await self.project_client.agents.delete_vector_store(vector_store_id)
        logger.info(f'Deleted vector store: {vector_store_id}')
    
    async def list_files_in_vector_store(self, vector_store_id: str):
        """
        List files in a vector store.
        
        Args:
            vector_store_id: ID of the vector store
            
        Returns:
            List of file objects in the vector store
        """
        files = await self.project_client.agents.list_vector_store_files(vector_store_id)
        return list(files)
    
    async def delete_file_from_vector_store(self, vector_store_id: str, file_id: str) -> None:
        """
        Delete file from vector store.
        
        Args:
            vector_store_id: ID of the vector store
            file_id: ID of the file to delete
        """
        await self.project_client.agents.delete_vector_store_file(
            vector_store_id=vector_store_id,
            file_id=file_id
        )
        logger.info(f'Deleted file {file_id} from vector store {vector_store_id}')

