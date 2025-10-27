"""Configuration and initialization for Azure AI Search Knowledge Base."""

import logging
import streamlit as st
from typing import Optional

from src.search.client import SearchClient
from src.search.embeddings import EmbeddingsGenerator
from src.search.indexer import DocumentIndexer
from src.search.chunking import TextChunker
from src.tools.search_knowledge_base import KnowledgeBaseSearchTool

logger = logging.getLogger(__name__)

# Global instances (singleton pattern)
_search_client: Optional[SearchClient] = None
_embeddings_generator: Optional[EmbeddingsGenerator] = None
_document_indexer: Optional[DocumentIndexer] = None
_kb_search_tool: Optional[KnowledgeBaseSearchTool] = None


def init_azure_search_config() -> dict:
    """
    Initialize Azure AI Search configuration from secrets.
    
    Returns:
        Configuration dictionary
    """
    try:
        config = {
            # Azure Search
            'search_endpoint': st.secrets['azure_search']['endpoint'],
            'search_index_name': st.secrets['azure_search']['index_name'],
            'search_admin_key': st.secrets['azure_search']['admin_key'],
            'search_query_key': st.secrets['azure_search'].get('query_key'),
            
            # Embeddings
            'embeddings_model': st.secrets['embeddings']['model'],
            'embeddings_dimensions': st.secrets['embeddings']['dimensions'],
            'embeddings_batch_size': st.secrets['embeddings'].get('batch_size', 16),
            
            # OpenAI for Embeddings (use embeddings-specific config if available, fallback to open_ai)
            'openai_api_key': st.secrets['embeddings'].get('api_key') or st.secrets['open_ai']['api_key'],
            'openai_base_url': st.secrets['embeddings'].get('api_base') or st.secrets['open_ai'].get('base_url'),
            'openai_api_version': st.secrets['embeddings'].get('api_version', '2024-02-01'),
            
            # Search settings
            'use_semantic_search': st.secrets['search'].get('use_semantic_search', True),
            'use_hybrid_search': st.secrets['search'].get('use_hybrid_search', True),
            'top_k': st.secrets['search'].get('top_k', 5),
            'min_score': st.secrets['search'].get('min_score', 0.7),
            
            # Chunking
            'chunk_size': st.secrets.get('chunking', {}).get('chunk_size', 1000),
            'chunk_overlap': st.secrets.get('chunking', {}).get('chunk_overlap', 200),
            'chunk_strategy': st.secrets.get('chunking', {}).get('strategy', 'semantic'),
        }
        
        return config
    
    except KeyError as e:
        logger.error(f'Missing required configuration in secrets.toml: {e}')
        raise ValueError(f'Configuration error: {e}. Please check secrets.toml')


def get_search_client(use_admin_key: bool = False) -> SearchClient:
    """
    Get or create SearchClient instance (singleton).
    
    Args:
        use_admin_key: Use admin key (for indexing) vs query key (for search)
        
    Returns:
        SearchClient instance
    """
    global _search_client
    
    if _search_client is None:
        config = init_azure_search_config()
        
        api_key = config['search_admin_key'] if use_admin_key else config.get('search_query_key', config['search_admin_key'])
        
        _search_client = SearchClient(
            endpoint=config['search_endpoint'],
            index_name=config['search_index_name'],
            api_key=api_key,
            use_semantic_search=config['use_semantic_search'],
            use_hybrid_search=config['use_hybrid_search']
        )
        
        logger.info(f'Initialized SearchClient for index: {config["search_index_name"]}')
    
    return _search_client


def get_embeddings_generator() -> EmbeddingsGenerator:
    """
    Get or create EmbeddingsGenerator instance (singleton).
    
    Returns:
        EmbeddingsGenerator instance
    """
    global _embeddings_generator
    
    if _embeddings_generator is None:
        config = init_azure_search_config()
        
        # Determine if using Azure OpenAI
        use_azure = 'azure.com' in config.get('openai_base_url', '')
        
        _embeddings_generator = EmbeddingsGenerator(
            model=config['embeddings_model'],
            dimensions=config['embeddings_dimensions'],
            batch_size=config['embeddings_batch_size'],
            use_azure=use_azure,
            api_key=config['openai_api_key'],
            base_url=config.get('openai_base_url'),
            api_version=config.get('openai_api_version')
        )
        
        logger.info(f'Initialized EmbeddingsGenerator with model: {config["embeddings_model"]}')
    
    return _embeddings_generator


def get_document_indexer() -> DocumentIndexer:
    """
    Get or create DocumentIndexer instance (singleton).
    
    Returns:
        DocumentIndexer instance
    """
    global _document_indexer
    
    if _document_indexer is None:
        config = init_azure_search_config()
        
        embeddings_gen = get_embeddings_generator()
        
        chunker = TextChunker(
            chunk_size=config['chunk_size'],
            chunk_overlap=config['chunk_overlap'],
            strategy=config['chunk_strategy']
        )
        
        _document_indexer = DocumentIndexer(
            search_endpoint=config['search_endpoint'],
            index_name=config['search_index_name'],
            api_key=config['search_admin_key'],
            embeddings_generator=embeddings_gen,
            chunker=chunker
        )
        
        logger.info(f'Initialized DocumentIndexer for index: {config["search_index_name"]}')
    
    return _document_indexer


def get_kb_search_tool() -> KnowledgeBaseSearchTool:
    """
    Get or create KnowledgeBaseSearchTool instance (singleton).
    
    Returns:
        KnowledgeBaseSearchTool instance
    """
    global _kb_search_tool
    
    if _kb_search_tool is None:
        config = init_azure_search_config()
        
        search_client = get_search_client(use_admin_key=False)
        embeddings_gen = get_embeddings_generator()
        
        _kb_search_tool = KnowledgeBaseSearchTool(
            search_client=search_client,
            embeddings_generator=embeddings_gen,
            top_k=config['top_k'],
            min_score=config['min_score']
        )
        
        logger.info('Initialized KnowledgeBaseSearchTool')
    
    return _kb_search_tool


# Cleanup functions
async def cleanup_search_resources():
    """Cleanup all search-related resources."""
    global _search_client, _embeddings_generator, _document_indexer, _kb_search_tool
    
    if _search_client:
        await _search_client.close()
        _search_client = None
    
    if _embeddings_generator:
        await _embeddings_generator.close()
        _embeddings_generator = None
    
    if _document_indexer:
        await _document_indexer.close()
        _document_indexer = None
    
    _kb_search_tool = None
    
    logger.info('Cleaned up all search resources')

