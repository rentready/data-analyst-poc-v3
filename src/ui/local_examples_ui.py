"""Direct KB UI components - Expert-verified templates and data from Azure Blob Storage."""

import streamlit as st
import logging
from typing import Dict, List, Optional
from src.storage.blob_examples import BlobExamplesManager

logger = logging.getLogger(__name__)

# Supported text file extensions
TEXT_EXTENSIONS = ['.sql', '.txt', '.md', '.json', '.py', '.yaml', '.yml', '.csv', '.xml']


def list_text_templates(blob_manager: BlobExamplesManager) -> List[Dict[str, str]]:
    """
    List all available text templates from Blob Storage.
    
    Args:
        blob_manager: Blob storage manager instance
        
    Returns:
        List of dicts with template metadata
    """
    try:
        blobs = blob_manager.list_blobs()
        
        templates = []
        
        for blob_info in blobs:
            filename = blob_info['filename']
            
            # Skip README files
            if filename == 'README.md':
                continue
            # Extract title and description
            title = filename.replace('_', ' ').replace('.sql', '').replace('.md', '').title()
            file_type = blob_info['extension'][1:].upper() if blob_info['extension'] else 'TXT'
            
            # Default description by file type
            type_descriptions = {
                'sql': 'SQL query template',
                'md': 'Documentation',
                'json': 'JSON data',
                'py': 'Python script',
                'txt': 'Text document',
                'yaml': 'YAML configuration',
                'yml': 'YAML configuration',
                'csv': 'CSV data',
                'xml': 'XML data'
            }
            description = type_descriptions.get(file_type.lower(), 'Text template')
            
            templates.append({
                'filename': filename,
                'title': title,
                'description': description,
                'relative_path': blob_info['relative_path'],
                'category': blob_info['category'].title(),
                'type': file_type,
                'size': blob_info['size'],
                'last_modified': blob_info['last_modified']
            })
        
        return templates
    
    except Exception as e:
        logger.error(f'Error listing templates from blob: {e}')
        return []


def read_template(blob_manager: BlobExamplesManager, relative_path: str) -> Optional[str]:
    """
    Read template content from Blob Storage.
    
    Args:
        blob_manager: Blob storage manager instance
        relative_path: Relative path from examples directory (e.g., 'sql/pro_load_calculation.sql')
        
    Returns:
        File content or None if error
    """
    try:
        return blob_manager.read_blob(relative_path)
    except Exception as e:
        logger.error(f'Error reading {relative_path} from blob: {e}')
        return None


def get_metrics_definitions(blob_manager: BlobExamplesManager) -> Optional[str]:
    """Read metrics definitions file from Blob Storage."""
    try:
        return blob_manager.read_blob('definitions/metrics.md')
    except Exception as e:
        logger.warning(f'Metrics definitions not available: {e}')
        return None


def render_local_examples_sidebar(blob_manager: BlobExamplesManager) -> None:
    """
    Render Direct KB UI in sidebar.
    
    This provides direct access to expert-verified templates and data
    stored in Azure Blob Storage (SQL, JSON, markdown, etc.).
    
    Args:
        blob_manager: Blob storage manager instance
    """
    with st.sidebar:
        st.header('📁 Knowledge Base (direct)')
        st.caption('Expert-verified templates & data')
        
        try:
            # Get all text templates from blob storage
            templates = list_text_templates(blob_manager)
            
            # Group by category
            categories = {}
            for template in templates:
                cat = template['category']
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(template)
            
            # Display statistics
            col1, col2 = st.columns(2)
            with col1:
                st.metric('Templates', len(templates))
            with col2:
                st.metric('Categories', len(categories))
            
            # Display templates list by category
            if templates:
                expander = st.expander('📄 View Templates', expanded=False)
                
                with expander:
                    st.caption('Click to view template content')
                    
                    # Display by category
                    for category, cat_templates in sorted(categories.items()):
                        if len(categories) > 1:
                            st.markdown(f"**📂 {category}**")
                        
                        for template in cat_templates:
                            filename = template['filename']
                            rel_path = template['relative_path']
                            
                            # Template header with badge
                            col_header, col_badge = st.columns([3, 1])
                            with col_header:
                                st.markdown(f"**{template['title']}**")
                            with col_badge:
                                st.caption(f"`{template['type']}`")
                            
                            # Format file size
                            size_bytes = template['size']
                            if size_bytes < 1024:
                                size_str = f"{size_bytes} bytes"
                            elif size_bytes < 1024 * 1024:
                                size_str = f"{size_bytes / 1024:.1f} KB"
                            else:
                                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                            
                            st.caption(f"📄 `{rel_path}` • {size_str}")
                            
                            if template['description']:
                                st.info(template['description'])
                            
                            # Action buttons
                            col1, col2 = st.columns([2, 1])
                            
                            with col1:
                                expander_key = f'expand_{rel_path}'
                                
                                if expander_key not in st.session_state:
                                    st.session_state[expander_key] = False
                                
                                if st.button('👁️ View', key=f'view_{rel_path}', use_container_width=True):
                                    st.session_state[expander_key] = not st.session_state[expander_key]
                                
                                if st.session_state[expander_key]:
                                    content = read_template(blob_manager, rel_path)
                                    if content:
                                        # Choose language for syntax highlighting
                                        lang_map = {
                                            'SQL': 'sql',
                                            'PY': 'python',
                                            'JSON': 'json',
                                            'YAML': 'yaml',
                                            'YML': 'yaml',
                                            'MD': 'markdown',
                                            'CSV': 'csv',
                                            'TXT': 'text'
                                        }
                                        lang = lang_map.get(template['type'], 'text')
                                        
                                        with st.expander(f'📝 {template["type"]} Content', expanded=True):
                                            st.code(content, language=lang, line_numbers=True)
                                    else:
                                        st.error('Could not load template')
                            
                            with col2:
                                # Copy to clipboard info
                                st.caption('💡 Use tool')
                            
                            st.divider()
            else:
                st.info('No SQL templates found')
            
            # Metrics definitions section
            st.divider()
            
            with st.expander('📊 Metrics Definitions', expanded=False):
                metrics_content = get_metrics_definitions(blob_manager)
                if metrics_content:
                    st.markdown(metrics_content)
                else:
                    st.info('Metrics definitions not available')
            
            # File upload section
            st.divider()
            
            st.subheader('📤 Upload Template')
            
            uploaded_file = st.file_uploader(
                'Upload new template or data file',
                type=['sql', 'txt', 'md', 'json', 'py', 'yaml', 'yml', 'csv', 'xml'],
                help='Upload expert-verified templates or reference data'
            )
            
            if uploaded_file:
                category_choice = st.selectbox(
                    'Category',
                    ['sql', 'definitions', 'scripts', 'data'],
                    help='Choose where to store this file'
                )
                
                if st.button('Upload', type='primary'):
                    try:
                        content = uploaded_file.read().decode('utf-8')
                        relative_path = f"{category_choice}/{uploaded_file.name}"
                        
                        if blob_manager.upload_blob(content, relative_path, overwrite=True):
                            st.success(f'✅ Uploaded {uploaded_file.name} to {category_choice}/')
                            st.rerun()
                        else:
                            st.error('❌ Upload failed')
                    except Exception as e:
                        st.error(f'❌ Error: {str(e)}')
            
            # Info section
            st.divider()
            
            with st.expander('ℹ️ About Direct KB', expanded=False):
                st.markdown("""
                **Knowledge Base (direct)** provides:
                
                ✅ **100% Accuracy**: Expert-verified templates & data  
                ✅ **Deterministic**: Same input = same output  
                ✅ **Centralized**: Azure Blob Storage  
                ✅ **Versioned**: Blob versioning enabled  
                
                **Supported formats**:
                - SQL queries (`.sql`)
                - Documentation (`.md`)
                - Data files (`.json`, `.csv`)
                - Scripts (`.py`, `.yaml`)
                - Text files (`.txt`)
                
                **How agents use it**:
                1. Call `read_example(category="sql", name="pro_load")`
                2. Get complete template/data
                3. Use directly or replace placeholders
                
                **vs Semantic KB**:
                - **Semantic KB**: AI search through uploaded documents - good for finding business definitions, context
                - **Direct KB**: Exact file access - perfect for templates, queries, and data requiring precision
                """)
                
                # Show blob storage info
                st.caption(f'☁️ Storage: Azure Blob (container: `{blob_manager.container_name}`)')
        
        except Exception as e:
            logger.error(f'Error rendering local examples UI: {e}')
            st.error(f'Error loading local examples: {str(e)}')


def render_examples_info() -> None:
    """Render information about local examples system."""
    st.info("""
    **Local Examples** are expert-verified templates and data stored directly in the project.
    
    They provide 100% accurate content for SQL queries, business rules, reference data, and more.
    AI agents use them via tools like `read_example()` for guaranteed correct results.
    
    Supports: SQL, JSON, YAML, Markdown, Python scripts, CSV, and text files.
    """)

