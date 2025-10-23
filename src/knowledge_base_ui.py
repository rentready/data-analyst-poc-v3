"""Knowledge Base UI components for Streamlit."""
import streamlit as st
import logging
import asyncio
from typing import Optional
from src.knowledge_base_api import get_vector_store_files, upload_file_to_vector_store, delete_file_from_vector_store

logger = logging.getLogger(__name__)

def render_knowledge_base_sidebar(vector_store_id: Optional[str], config: dict) -> None:
    """Render Knowledge Base management UI in sidebar."""
    with st.sidebar:
        st.header('📚 Knowledge Base')
        
        if not vector_store_id:
            st.info('💡 Configure vector_store_id in secrets.toml')
            return
        
        try:
            files = asyncio.run(get_vector_store_files(vector_store_id, config))
            
            if files:
                st.metric('Files in Knowledge Base', len(files))
                
                with st.expander('View Files', expanded=False):
                    st.info('💡 Files are accessible by agents via File Search Tool.')
                    
                    for file_info in files:
                        col1, col2, col3 = st.columns([4, 1, 1])
                        
                        with col1:
                            st.text(file_info['filename'])
                        
                        with col2:
                            status = file_info.get('status', 'unknown')
                            if status == 'completed':
                                st.caption('✅')
                            elif status == 'in_progress':
                                st.caption('⏳')
                            elif status == 'failed':
                                st.caption('❌')
                        
                        with col3:
                            if st.button('🗑️', key=f"delete_{file_info['id']}", help='Delete'):
                                try:
                                    deleted = asyncio.run(delete_file_from_vector_store(file_info['filename'], vector_store_id, config))
                                    if deleted:
                                        st.success(f"Deleted {file_info['filename']}")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f'Error: {e}')
            else:
                st.info('No files yet')
        
        except Exception as e:
            st.warning(f'Could not load files: {e}')
        
        st.divider()
        
        uploaded_files = st.file_uploader('Upload documents', accept_multiple_files=True, type=['pdf', 'txt', 'docx', 'md', 'json', 'csv'], help='Upload documents for knowledge base')
        
        if uploaded_files and st.button('📤 Upload', type='primary'):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            upload_errors = []
            upload_success = []
            
            for idx, uploaded_file in enumerate(uploaded_files):
                file_data = uploaded_file.getvalue()
                status_text.text(f'Uploading {uploaded_file.name}...')
                
                try:
                    asyncio.run(upload_file_to_vector_store(file_data, uploaded_file.name, vector_store_id, config))
                    upload_success.append(uploaded_file.name)
                except Exception as e:
                    upload_errors.append(f'{uploaded_file.name}: {e}')
                
                progress_bar.progress((idx + 1) / len(uploaded_files))
            
            status_text.empty()
            progress_bar.empty()
            
            if upload_success:
                st.success(f'Uploaded {len(upload_success)} file(s)!')
            
            if upload_errors:
                st.error('Upload errors:')
                for error in upload_errors:
                    st.error(f'  {error}')
            
            st.rerun()
        
        st.caption(f'Vector Store: {vector_store_id[:20]}...')
        st.divider()

