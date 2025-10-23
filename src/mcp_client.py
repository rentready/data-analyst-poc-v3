"""MCP Token Client for Azure AI Foundry Agent integration."""

import logging
import requests
from typing import Optional, Dict

from .constants import (
    MCP_CLIENT_ID_KEY, MCP_CLIENT_SECRET_KEY,
    AZURE_TENANT_ID_KEY, AUTHORITY_BASE_URL
)

logger = logging.getLogger(__name__)


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