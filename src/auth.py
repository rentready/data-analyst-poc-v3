"""Authentication management for Azure AI Foundry Chatbot."""

from streamlit_msal import Msal

# Constants used only in this file
AUTHORITY_BASE_URL = "https://login.microsoftonline.com"

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
