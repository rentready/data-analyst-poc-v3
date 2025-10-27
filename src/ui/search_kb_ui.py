"""Knowledge Base UI components for Azure AI Search."""

import streamlit as st
import logging
from typing import Optional

from src.search.indexer import DocumentIndexer
from src.search.embeddings import EmbeddingsGenerator
from src.utils.async_helpers import run_async_safe as run_async

logger = logging.getLogger(__name__)


def render_knowledge_base_sidebar(indexer: DocumentIndexer) -> None:
    """
    Render Knowledge Base management UI in sidebar using Azure AI Search.
    
    Args:
        indexer: Document indexer instance
    """
    with st.sidebar:
        st.header('📚 Knowledge Base')
        
        try:
            # Get index statistics
            stats = run_async(indexer.get_index_statistics())
            
            if 'error' in stats:
                st.error(f'Error loading statistics: {stats["error"]}')
                return
            
            # Display statistics
            col1, col2 = st.columns(2)
            with col1:
                st.metric('Files', stats.get('total_files', 0))
            with col2:
                st.metric('Chunks', stats.get('total_documents', 0))
            
            # Display files list
            files = stats.get('files', [])
            if files:
                expander = st.expander('View Files', expanded=False)
                
                # Check if expander was just opened and we haven't loaded files yet
                expander_key = 'kb_files_loaded_for_download'
                if expander.expanded and expander_key not in st.session_state:
                    # Pre-load all files ONCE when expander is opened
                    with st.spinner('Preparing files...'):
                        for file_info in files:
                            filename = file_info['filename']
                            content_key = f'content_{filename}'
                            if content_key not in st.session_state:
                                try:
                                    result = run_async(indexer.download_document_by_filename(filename))
                                    if result['success']:
                                        st.session_state[content_key] = result['content']
                                except Exception as e:
                                    pass  # Silently skip failed loads
                        st.session_state[expander_key] = True
                        st.rerun()
                
                with expander:
                    st.info('💡 Files are indexed and searchable via hybrid search.')
                    
                    for file_info in files:
                        filename = file_info['filename']
                        
                        # File info container
                        with st.container():
                            # Filename display
                            st.markdown(f'**{filename}**')
                            
                            # Action buttons in one row
                            col1, col2 = st.columns([1, 1])
                            
                            with col1:
                                content_key = f'content_{filename}'
                                if content_key in st.session_state:
                                    # File is pre-loaded, show download button
                                    st.download_button(
                                        label='⬇️ Download',
                                        data=st.session_state[content_key],
                                        file_name=filename,
                                        mime='text/plain',
                                        key=f'download_{filename}',
                                        use_container_width=True
                                    )
                                else:
                                    # File not loaded yet (shouldn't happen after pre-load)
                                    st.button('⏳ Loading...', key=f'dl_disabled_{filename}', disabled=True, use_container_width=True)
                            
                            with col2:
                                if st.button('🗑️ Delete', key=f"delete_{filename}", use_container_width=True):
                                    try:
                                        result = run_async(indexer.delete_document_by_filename(filename))
                                        if result['success']:
                                            st.success(f"Deleted {filename}")
                                            # Clean up download state
                                            st.session_state.pop(f'content_{filename}', None)
                                            st.session_state.pop(expander_key, None)  # Force reload on next open
                                            st.rerun()
                                        else:
                                            st.error('Failed to delete')
                                    except Exception as e:
                                        st.error(f'Error: {str(e)}')
                            
                            st.divider()
            else:
                st.info('No files indexed yet')
        
        except Exception as e:
            st.warning(f'Could not load statistics: {e}')
        
        st.divider()
        
        # File upload section
        st.subheader('Upload Documents')
        
        uploaded_files = st.file_uploader(
            'Choose files',
            accept_multiple_files=True,
            type=['pdf', 'txt', 'docx', 'md', 'json', 'csv'],
            help='Upload documents to index in Knowledge Base'
        )
        
        # Chunking strategy selection
        chunk_strategy = st.selectbox(
            'Chunking Strategy',
            ['semantic', 'fixed', 'sentence'],
            help='Method for splitting documents into chunks'
        )
        
        if uploaded_files and st.button('📤 Upload & Index', type='primary'):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            upload_errors = []
            upload_success = []
            
            for idx, uploaded_file in enumerate(uploaded_files):
                file_data = uploaded_file.getvalue()
                filename = uploaded_file.name
                file_type = filename.split('.')[-1].lower()
                
                status_text.text(f'Processing {filename}...')
                
                try:
                    # Update chunker strategy
                    indexer.chunker.strategy = chunk_strategy
                    
                    # Index document
                    result = run_async(indexer.index_document(
                        file_content=file_data,
                        filename=filename,
                        file_type=file_type
                    ))
                    
                    if result['success']:
                        upload_success.append(
                            f"{filename}: {result['indexed_chunks']} chunks indexed"
                        )
                    else:
                        upload_errors.append(
                            f"{filename}: {result['failed_chunks']} chunks failed"
                        )
                
                except Exception as e:
                    upload_errors.append(f'{filename}: {str(e)}')
                
                progress_bar.progress((idx + 1) / len(uploaded_files))
            
            status_text.empty()
            progress_bar.empty()
            
            if upload_success:
                st.success('✅ Upload complete!')
                for msg in upload_success:
                    st.success(f'  • {msg}')
            
            if upload_errors:
                st.error('❌ Errors occurred:')
                for error in upload_errors:
                    st.error(f'  • {error}')
            
            st.rerun()
        
        st.divider()
        
        # Search configuration
        with st.expander('⚙️ Search Settings', expanded=False):
            st.caption('Azure AI Search Configuration')
            st.text(f'Index: {indexer.index_name}')
            st.text(f'Endpoint: {indexer.search_endpoint[:50]}...')
            st.text(f'Embedding Model: {indexer.embeddings_generator.model}')
            st.text(f'Chunk Strategy: {indexer.chunker.strategy}')


def render_search_test_ui():
    """Render search test interface for debugging."""
    st.subheader('🔍 Test Knowledge Base Search')
    
    query = st.text_input('Enter search query:', placeholder='e.g., What is DSAT?')
    
    col1, col2 = st.columns(2)
    with col1:
        top_k = st.slider('Number of results', 1, 10, 5)
    
    with col2:
        search_type = st.selectbox('Search type', ['hybrid', 'vector', 'keyword'])
    
    if st.button('Search', type='primary') and query:
        with st.spinner('Searching...'):
            try:
                from src.config import get_kb_search_tool
                tool = get_kb_search_tool()
                
                results = run_async(tool.search(
                    query=query,
                    top_k=top_k,
                    search_type=search_type
                ))
                
                if results:
                    st.success(f'Found {len(results)} results')
                    
                    for i, result in enumerate(results, 1):
                        with st.expander(f'Result {i}: {result.filename} (Score: {result.score:.3f})'):
                            st.markdown(f'**Source:** `{result.filename}` (chunk {result.chunk_id})')
                            st.markdown(f'**Score:** {result.score:.3f}')
                            
                            if result.captions:
                                st.markdown('**Relevant excerpts:**')
                                for caption in result.captions:
                                    st.info(caption)
                            
                            st.markdown('**Full Content:**')
                            st.text(result.content)
                else:
                    st.warning('No results found')
            
            except Exception as e:
                st.error(f'Search error: {e}')

