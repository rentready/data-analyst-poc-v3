"""Script to create Azure AI Search index with proper schema."""

import asyncio
import logging
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch
)
from azure.core.credentials import AzureKeyCredential
import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_index():
    """Create Azure AI Search index with vector search and semantic configuration."""
    try:
        # Load configuration
        endpoint = st.secrets['azure_search']['endpoint']
        admin_key = st.secrets['azure_search']['admin_key']
        index_name = st.secrets['azure_search']['index_name']
        
        # Create index client
        credential = AzureKeyCredential(admin_key)
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as index_client:
            
            # Define index fields
            fields = [
                SimpleField(
                    name='id',
                    type=SearchFieldDataType.String,
                    key=True,
                    filterable=False,
                    sortable=False
                ),
                SearchableField(
                    name='content',
                    type=SearchFieldDataType.String,
                    analyzer_name='en.microsoft'
                ),
                SearchField(
                    name='content_vector',
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=1536,
                    vector_search_profile_name='vector-profile'
                ),
                SearchableField(
                    name='filename',
                    type=SearchFieldDataType.String,
                    filterable=True,
                    sortable=True,
                    facetable=True
                ),
                SimpleField(
                    name='chunk_id',
                    type=SearchFieldDataType.Int32,
                    filterable=True,
                    sortable=True
                ),
                SimpleField(
                    name='file_type',
                    type=SearchFieldDataType.String,
                    filterable=True,
                    facetable=True
                ),
                SimpleField(
                    name='upload_date',
                    type=SearchFieldDataType.DateTimeOffset,
                    filterable=True,
                    sortable=True
                ),
                SimpleField(
                    name='metadata',
                    type=SearchFieldDataType.String
                )
            ]
            
            # Configure vector search
            vector_search = VectorSearch(
                algorithms=[
                    HnswAlgorithmConfiguration(
                        name='vector-algorithm',
                        parameters={
                            'm': 4,
                            'efConstruction': 400,
                            'efSearch': 500,
                            'metric': 'cosine'
                        }
                    )
                ],
                profiles=[
                    VectorSearchProfile(
                        name='vector-profile',
                        algorithm_configuration_name='vector-algorithm'
                    )
                ]
            )
            
            # Configure semantic search
            semantic_search = SemanticSearch(
                configurations=[
                    SemanticConfiguration(
                        name='semantic-config',
                        prioritized_fields=SemanticPrioritizedFields(
                            content_fields=[SemanticField(field_name='content')],
                            keywords_fields=[SemanticField(field_name='filename')]
                        )
                    )
                ]
            )
            
            # Create index
            index = SearchIndex(
                name=index_name,
                fields=fields,
                vector_search=vector_search,
                semantic_search=semantic_search
            )
            
            # Create or update index
            logger.info(f'Creating index: {index_name}')
            result = await index_client.create_or_update_index(index)
            
            logger.info(f'✅ Index created successfully: {result.name}')
            logger.info(f'   Endpoint: {endpoint}')
            logger.info(f'   Fields: {len(result.fields)}')
            logger.info(f'   Vector search: Enabled')
            logger.info(f'   Semantic search: Enabled')
    
    except Exception as e:
        logger.error(f'❌ Failed to create index: {e}')
        raise


if __name__ == '__main__':
    print('Creating Azure AI Search index...')
    asyncio.run(create_index())
    print('Done!')

