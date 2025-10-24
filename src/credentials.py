"""Credentials and authentication management for Azure AI Foundry Chatbot."""

import streamlit as st
import os
import logging
import requests
from typing import Optional, Dict
from streamlit_msal import Msal

logger = logging.getLogger(__name__)

# Constants used only in this file
AUTHORITY_BASE_URL = "https://login.microsoftonline.com"
MCP_CLIENT_ID_KEY = "mcp_client_id"
MCP_CLIENT_SECRET_KEY = "mcp_client_secret"
AZURE_TENANT_ID_KEY = "AZURE_TENANT_ID"


def setup_environment_variables() -> None:
    """Set up environment variables for DefaultAzureCredential."""
    try:
        env_config = st.secrets["env"]
        
        os.environ["AZURE_CLIENT_ID"] = env_config.get("AZURE_CLIENT_ID", "")
        os.environ["AZURE_CLIENT_SECRET"] = env_config.get("AZURE_CLIENT_SECRET", "")
        os.environ["AZURE_TENANT_ID"] = env_config.get("AZURE_TENANT_ID", "")
    except KeyError:
        pass  # No environment variables found


def get_mcp_token_sync(config: Dict[str, str]) -> Optional[str]:
    """
    Get MCP access token synchronously using client credentials flow.
    
    Args:
        config: MCP configuration dictionary
        
    Returns:
        Access token string or None if failed
    """
    if not config:
        return None
    
    try:
        client_id = config[MCP_CLIENT_ID_KEY]
        client_secret = config[MCP_CLIENT_SECRET_KEY]
        tenant_id = config[AZURE_TENANT_ID_KEY]
        
        # Construct OAuth endpoint
        token_endpoint = f"{AUTHORITY_BASE_URL}/{tenant_id}/oauth2/token"
        
        # Prepare form data for client credentials flow
        data = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default'
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Make synchronous request
        response = requests.post(
            token_endpoint,
            data=data,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            
            if access_token:
                logger.info("Successfully obtained MCP access token")
                return access_token
            else:
                logger.error("No access token in response")
                return None
        else:
            logger.error(f"Failed to get access token. Status: {response.status_code}, Error: {response.text}")
            return None
            
    except requests.Timeout:
        logger.error("Timeout while getting MCP access token")
        return None
    except Exception as e:
        logger.error(f"Error getting MCP access token: {e}")
        return None


def initialize_msal_auth(client_id: str, tenant_id: str) -> dict:
    """Initialize MSAL authentication UI.
    
    Args:
        client_id: Azure AD client ID
        tenant_id: Azure AD tenant ID
        
    Returns:
        TokenCredential instance or None if not authenticated
    """
    # Form authority URL from tenant_id
    authority = f"{AUTHORITY_BASE_URL}/{tenant_id}"
    
    auth_data = Msal.initialize_ui(
        client_id=client_id,
        authority=authority,
        scopes=[],  # Required scope for Azure AI Foundry
        # Customize (Default values):
        connecting_label="Connecting",
        disconnected_label="Disconnected",
        sign_in_label="Sign in",
        sign_out_label="Sign out"
    )
    
    # Check if authentication was successful
    if not _is_authenticated(auth_data):
        return None
        
    return auth_data


def get_user_initials(auth_data: dict) -> str:
    """Extract user initials from authentication data.
    
    Args:
        auth_data: Authentication data from MSAL
        
    Returns:
        User initials (e.g., "JD" for John Doe)
    """
    if not auth_data:
        return ""
    
    # Try to get name from account info
    account = auth_data.get("account", {})
    name = account.get("name", "")
    
    if name:
        # Split name and get first letter of each part
        parts = name.split()
        initials = "".join([part[0].upper() for part in parts if part])
        return initials
    
    # Fallback to username/email
    username = account.get("username", "")
    if username:
        # If it's an email, use first letters before @
        email_parts = username.split("@")[0]
        # Try to split by dots or underscores
        parts = email_parts.replace(".", " ").replace("_", " ").split()
        if len(parts) >= 2:
            return "".join([part[0].upper() for part in parts[:2]])
        elif parts:
            return parts[0][:2].upper()
    
    return ""


def _is_authenticated(auth_data: dict) -> bool:
    """Check if user is authenticated.
    
    Args:
        auth_data: Authentication data from MSAL
        
    Returns:
        True if authenticated, False otherwise
    """
    return auth_data and "accessToken" in auth_data
