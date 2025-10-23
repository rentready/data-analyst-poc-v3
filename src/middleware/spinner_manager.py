"""Manages spinner state without global session state pollution."""

import streamlit as st
from typing import Optional

class SpinnerManager:
    """Context manager for spinners without global state."""
    
    def __init__(self):
        """Initialize spinner manager."""
        self._current_spinner: Optional[Any] = None
    
    def start(self, text: str) -> None:
        """
        Start spinner with given text.
        
        Args:
            text: Text to display in spinner
        """
        self.stop()  # Stop previous spinner if exists
        self._current_spinner = st.spinner(text)
        self._current_spinner.__enter__()
    
    def stop(self) -> None:
        """Stop current spinner if one exists."""
        if self._current_spinner:
            try:
                self._current_spinner.__exit__(None, None, None)
            except Exception:
                # Ignore errors when stopping spinner
                pass
            self._current_spinner = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
    
    def is_active(self) -> bool:
        """
        Check if spinner is currently active.
        
        Returns:
            True if spinner is active, False otherwise
        """
        return self._current_spinner is not None
