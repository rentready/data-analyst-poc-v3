"""Data Analyst Chat - Entry Point."""

import streamlit as st
import logging
from src.ui.app import DataAnalystApp

st.set_page_config(page_title="Data Analyst Chat", page_icon="🤖")
logging.basicConfig(level=logging.INFO, force=True)

def main():
    """Main entry point for the application."""
    app = DataAnalystApp()
    app.run()

if __name__ == "__main__":
    main()