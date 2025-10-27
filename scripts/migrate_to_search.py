"""Script to migrate documents from Vector Store to Azure AI Search."""

import asyncio
import logging
from pathlib import Path
import streamlit as st

from src.search_config import get_document_indexer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_documents_from_directory(directory: str):
    """
    Migrate all documents from a directory to Azure AI Search.
    
    Args:
        directory: Path to directory containing documents
    """
    try:
        indexer = get_document_indexer()
        
        # Get all supported files
        supported_extensions = ['.pdf', '.txt', '.docx', '.md', '.json', '.csv']
        directory_path = Path(directory)
        
        files = []
        for ext in supported_extensions:
            files.extend(directory_path.glob(f'*{ext}'))
        
        if not files:
            logger.warning(f'No supported files found in {directory}')
            return
        
        logger.info(f'Found {len(files)} files to migrate')
        
        # Process each file
        success_count = 0
        failure_count = 0
        
        for file_path in files:
            try:
                logger.info(f'Processing {file_path.name}...')
                
                # Read file content
                with open(file_path, 'rb') as f:
                    file_content = f.read()
                
                # Get file type
                file_type = file_path.suffix[1:]  # Remove leading dot
                
                # Index document
                result = await indexer.index_document(
                    file_content=file_content,
                    filename=file_path.name,
                    file_type=file_type
                )
                
                if result['success']:
                    success_count += 1
                    logger.info(f'✅ {file_path.name}: {result["indexed_chunks"]} chunks indexed')
                else:
                    failure_count += 1
                    logger.error(f'❌ {file_path.name}: {result["failed_chunks"]} chunks failed')
            
            except Exception as e:
                failure_count += 1
                logger.error(f'❌ {file_path.name}: {e}')
        
        logger.info(f'\n=== Migration Complete ===')
        logger.info(f'Success: {success_count} files')
        logger.info(f'Failed: {failure_count} files')
        
        # Display final statistics
        stats = await indexer.get_index_statistics()
        logger.info(f'\n=== Index Statistics ===')
        logger.info(f'Total files: {stats["total_files"]}')
        logger.info(f'Total chunks: {stats["total_documents"]}')
    
    except Exception as e:
        logger.error(f'Migration failed: {e}')
        raise


async def migrate_single_file(file_path: str):
    """
    Migrate a single file to Azure AI Search.
    
    Args:
        file_path: Path to file
    """
    try:
        indexer = get_document_indexer()
        
        file_path_obj = Path(file_path)
        
        if not file_path_obj.exists():
            raise FileNotFoundError(f'File not found: {file_path}')
        
        logger.info(f'Migrating {file_path_obj.name}...')
        
        # Read file
        with open(file_path_obj, 'rb') as f:
            file_content = f.read()
        
        # Get file type
        file_type = file_path_obj.suffix[1:]
        
        # Index document
        result = await indexer.index_document(
            file_content=file_content,
            filename=file_path_obj.name,
            file_type=file_type
        )
        
        if result['success']:
            logger.info(f'✅ Successfully indexed {result["indexed_chunks"]} chunks')
        else:
            logger.error(f'❌ Failed to index {result["failed_chunks"]} chunks')
    
    except Exception as e:
        logger.error(f'Failed to migrate file: {e}')
        raise


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print('Usage:')
        print('  Migrate directory: python migrate_to_search.py /path/to/directory')
        print('  Migrate single file: python migrate_to_search.py /path/to/file.pdf')
        sys.exit(1)
    
    path = sys.argv[1]
    path_obj = Path(path)
    
    if path_obj.is_dir():
        print(f'Migrating all documents from directory: {path}')
        asyncio.run(migrate_documents_from_directory(path))
    elif path_obj.is_file():
        print(f'Migrating single file: {path}')
        asyncio.run(migrate_single_file(path))
    else:
        print(f'Error: {path} is not a valid file or directory')
        sys.exit(1)
    
    print('Migration complete!')

