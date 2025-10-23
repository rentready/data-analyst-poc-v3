"""Data Analyst Chat - Entry Point."""

import streamlit as st
from src.ui.app import DataAnalystApp

st.set_page_config(page_title="Data Analyst Chat", page_icon="🤖")

def main():
    """Main entry point for the application."""
    app = DataAnalystApp()
    app.run()

if __name__ == "__main__":
    main()