"""Configuration management for Azure AI Foundry Chatbot."""

import streamlit as st
import os


def setup_environment_variables() -> None:
    """Set up environment variables for DefaultAzureCredential."""
    try:
        env_config = st.secrets["env"]
        
        os.environ["AZURE_CLIENT_ID"] = env_config.get("AZURE_CLIENT_ID", "")
        os.environ["AZURE_CLIENT_SECRET"] = env_config.get("AZURE_CLIENT_SECRET", "")
        os.environ["AZURE_TENANT_ID"] = env_config.get("AZURE_TENANT_ID", "")
    except KeyError:
        pass  # No environment variables found