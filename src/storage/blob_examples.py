"""Azure Blob Storage manager for local examples (SQL, JSON, etc.)."""

import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)


class BlobExamplesManager:
    """
    Manages expert-verified templates and data in Azure Blob Storage.
    
    Container structure:
        examples/
        ├── sql/
        │   ├── pro_load_calculation.sql
        │   └── other_queries.sql
        ├── definitions/
        │   └── metrics.md
        ├── scripts/
        └── data/
    """
    
    def __init__(
        self,
        connection_string: str,
        container_name: str = "knowledge-base-direct"
    ):
        """
        Initialize blob examples manager.
        
        Args:
            connection_string: Azure Storage connection string
            container_name: Container name for examples
        """
        self.connection_string = connection_string
        self.container_name = container_name
        
        # Initialize clients
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_client = self.blob_service_client.get_container_client(container_name)
        
        # Ensure container exists
        self._ensure_container_exists()
    
    def _ensure_container_exists(self) -> None:
        """Create container if it doesn't exist."""
        try:
            self.container_client.create_container()
            logger.info(f"Created container: {self.container_name}")
        except Exception as e:
            if "ContainerAlreadyExists" in str(e):
                logger.debug(f"Container {self.container_name} already exists")
            else:
                logger.warning(f"Error creating container: {e}")
    
    def list_blobs(
        self,
        category: Optional[str] = None,
        extension: Optional[str] = None
    ) -> List[Dict[str, any]]:
        """
        List all blobs (templates/data files).
        
        Args:
            category: Filter by category (sql, definitions, scripts, data)
            extension: Filter by file extension (e.g., '.sql', '.json')
            
        Returns:
            List of blob metadata dicts
        """
        try:
            blobs = []
            prefix = f"examples/{category}/" if category else "examples/"
            
            for blob in self.container_client.list_blobs(name_starts_with=prefix):
                blob_name = blob.name
                
                # Skip if not in examples/ or is a directory marker
                if not blob_name.startswith("examples/") or blob_name.endswith("/"):
                    continue
                
                # Parse path
                path_parts = blob_name.split("/")
                if len(path_parts) < 3:  # examples/category/file.ext
                    continue
                
                blob_category = path_parts[1]
                filename = path_parts[-1]
                file_ext = Path(filename).suffix
                
                # Apply extension filter
                if extension and file_ext != extension:
                    continue
                
                # Extract metadata
                relative_path = "/".join(path_parts[1:])  # category/file.ext
                
                blobs.append({
                    'blob_name': blob_name,
                    'filename': filename,
                    'category': blob_category,
                    'extension': file_ext,
                    'relative_path': relative_path,
                    'size': blob.size,
                    'last_modified': blob.last_modified,
                    'content_type': blob.content_settings.content_type if blob.content_settings else None
                })
            
            return sorted(blobs, key=lambda x: (x['category'], x['filename']))
        
        except Exception as e:
            logger.error(f"Error listing blobs: {e}")
            return []
    
    def read_blob(self, relative_path: str) -> Optional[str]:
        """
        Read blob content.
        
        Args:
            relative_path: Path relative to examples/ (e.g., 'sql/pro_load_calculation.sql')
            
        Returns:
            Blob content as string or None if error
        """
        blob_name = f"examples/{relative_path}"
        
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_data = blob_client.download_blob()
            content = blob_data.readall().decode('utf-8')
            
            logger.info(f"✅ Read blob: {relative_path} ({len(content)} chars)")
            return content
        
        except ResourceNotFoundError:
            logger.warning(f"Blob not found: {relative_path}")
            return None
        except Exception as e:
            logger.error(f"Error reading blob {relative_path}: {e}")
            return None
    
    def upload_blob(
        self,
        content: str,
        relative_path: str,
        overwrite: bool = True
    ) -> bool:
        """
        Upload content to blob.
        
        Args:
            content: File content
            relative_path: Path relative to examples/ (e.g., 'sql/new_query.sql')
            overwrite: Whether to overwrite existing blob
            
        Returns:
            True if successful
        """
        blob_name = f"examples/{relative_path}"
        
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            
            # Set content type based on extension
            content_type = self._get_content_type(relative_path)
            
            blob_client.upload_blob(
                content.encode('utf-8'),
                overwrite=overwrite,
                content_settings={'content_type': content_type}
            )
            
            logger.info(f"✅ Uploaded blob: {relative_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error uploading blob {relative_path}: {e}")
            return False
    
    def delete_blob(self, relative_path: str) -> bool:
        """
        Delete blob.
        
        Args:
            relative_path: Path relative to examples/ (e.g., 'sql/old_query.sql')
            
        Returns:
            True if successful
        """
        blob_name = f"examples/{relative_path}"
        
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.delete_blob()
            
            logger.info(f"✅ Deleted blob: {relative_path}")
            return True
        
        except ResourceNotFoundError:
            logger.warning(f"Blob not found: {relative_path}")
            return False
        except Exception as e:
            logger.error(f"Error deleting blob {relative_path}: {e}")
            return False
    
    def get_blob_metadata(self, relative_path: str) -> Optional[Dict]:
        """Get blob metadata without downloading content."""
        blob_name = f"examples/{relative_path}"
        
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            properties = blob_client.get_blob_properties()
            
            return {
                'name': properties.name,
                'size': properties.size,
                'last_modified': properties.last_modified,
                'content_type': properties.content_settings.content_type,
                'etag': properties.etag
            }
        except Exception as e:
            logger.error(f"Error getting blob metadata {relative_path}: {e}")
            return None
    
    def sync_from_local(self, local_examples_dir: Path) -> Tuple[int, int]:
        """
        Sync local examples directory to blob storage.
        
        Args:
            local_examples_dir: Path to local examples/ directory
            
        Returns:
            Tuple of (uploaded_count, error_count)
        """
        uploaded = 0
        errors = 0
        
        # Supported extensions
        extensions = ['.sql', '.md', '.txt', '.json', '.py', '.yaml', '.yml', '.csv', '.xml']
        
        # Scan local directory
        for category_dir in local_examples_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name.startswith('.'):
                continue
            
            category = category_dir.name
            
            # Upload files from this category
            for file_path in category_dir.rglob('*'):
                if file_path.is_file() and file_path.suffix in extensions:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        relative_path = f"{category}/{file_path.name}"
                        
                        if self.upload_blob(content, relative_path, overwrite=True):
                            uploaded += 1
                            logger.info(f"  ✅ {relative_path}")
                        else:
                            errors += 1
                    
                    except Exception as e:
                        logger.error(f"  ❌ Error uploading {file_path.name}: {e}")
                        errors += 1
        
        return uploaded, errors
    
    @staticmethod
    def _get_content_type(filename: str) -> str:
        """Get content type based on file extension."""
        ext = Path(filename).suffix.lower()
        
        content_types = {
            '.sql': 'text/plain',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.json': 'application/json',
            '.py': 'text/x-python',
            '.yaml': 'text/yaml',
            '.yml': 'text/yaml',
            '.csv': 'text/csv',
            '.xml': 'text/xml'
        }
        
        return content_types.get(ext, 'text/plain')

