import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
from PIL import Image
from typing import List, Dict, Tuple, Optional
import time
import base64
import os

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="TA Billedhenter v2",
    page_icon="🔥",
    layout="wide"
)

# IMMEDIATE TEST - THIS SHOULD SHOW UP
st.error("🔥🔥🔥 BRAND NEW VERSION 2 - IF YOU SEE THIS, THE NEW CODE IS WORKING! 🔥🔥🔥")

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'jwt_token' not in st.session_state:
    st.session_state.jwt_token = None
if 'api_authenticated' not in st.session_state:
    st.session_state.api_authenticated = False

class ICRTImageDownloader:
    def __init__(self):
        self.base_url = "https://api.icrt.io"
        self.jwt_token = None
    
    def authenticate_api(self, client_id: str, client_key: str) -> Tuple[bool, str]:
        """Authenticate with ICRT API and get JWT token"""
        try:
            auth_url = "https://api.icrt.io/auth"
            auth_payload = {"client_id": client_id, "client_key": client_key}
            auth_response = requests.post(auth_url, json=auth_payload)
            
            if 'Failed' in auth_response.text:
                return False, "Authentication failed. Please check your Client ID and Client Key."
            else:
                self.jwt_token = auth_response.text
                return True, "Authentication successful!"
                
        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"
    
    def extract_project_code(self, webkode: str) -> str:
        """Extract project code from webkode"""
        match = re.match(r'^([A-Z]{2}\d{5}|\d{5})', webkode)
        return match.group(1) if match else ""
    
    def process_webkodes(self, webkodes: List[str]) -> Tuple[List[str], Dict[str, str]]:
        """Process webkodes: strip letters if they start with two letters"""
        processed_codes = []
        original_mapping = {}
        
        st.write("🔧 Processing webkodes:")
        for code in webkodes:
            clean_code = code.strip()
            if re.match(r'^[A-Z]{2}\d', clean_code):
                processed_code = clean_code[2:]  # Remove first 2 letters
                st.write(f"🔄 '{clean_code}' → '{processed_code}' (stripped letters)")
            else:
                processed_code = clean_code
                st.write(f"✅ '{clean_code}' (kept as is)")
            
            processed_codes.append(processed_code)
            original_mapping[processed_code.lower()] = clean_code
        
        return processed_codes, original_mapping

def login_screen():
    st.title("🔐 Login")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            try:
                if username == st.secrets["login"]["username"] and password == st.secrets["login"]["password"]:
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")
            except:
                st.error("Login configuration error")

def api_screen():
    st.title("🔑 API Authentication")
    with st.form("api"):
        client_id = st.text_input("Client ID")
        client_key = st.text_input("Client Key", type="password")
        if st.form_submit_button("Authenticate"):
            if client_id and client_key:
                downloader = ICRTImageDownloader()
                success, message = downloader.authenticate_api(client_id, client_key)
                if success:
                    st.session_state.jwt_token = downloader.jwt_token
                    st.session_state.api_authenticated = True
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

def parse_text_input(text_input: str) -> List[str]:
    """Simple text parser"""
    if not text_input.strip():
        return []
    
    codes = re.split(r'[\s,]+', text_input.strip())
    return [code.strip() for code in codes if code.strip()]

def main_app():
    st.title("🚚 TA Billedhenter v2")
    
    downloader = ICRTImageDownloader()
    downloader.jwt_token = st.session_state.jwt_token
    
    # SIMPLE INPUT METHOD SELECTION
    st.header("📝 Input Method")
    method = st.selectbox("Choose input method:", ["Text Input", "Excel Upload"])
    
    webkodes = []
    
    if method == "Text Input":
        st.subheader("✏️ Enter Webkodes")
        text_input = st.text_area(
            "Paste webkodes here:",
            placeholder="IC23022-0259-00 IC23022-0263-00",
            height=100
        )
        
        if text_input:
            webkodes = parse_text_input(text_input)
            if webkodes:
                st.success(f"Found {len(webkodes)} webkodes")
                st.write("First few:", webkodes[:3])
    
    elif method == "Excel Upload":
        st.subheader("📁 Upload Excel File")
        st.info("Excel upload functionality simplified for testing")
    
    # PROCESSING SECTION
    if webkodes:
        st.header("🔍 Processing")
        
        # Extract project code
        project_code = downloader.extract_project_code(webkodes[0])
        st.write(f"Project code: {project_code}")
        
        # Process webkodes
        processed_codes, mapping = downloader.process_webkodes(webkodes)
        
        st.write("**Final search codes:**")
        for code in processed_codes:
            st.write(f"- `{code}`")
        
        if st.button("🔍 Search for Images"):
            st.success("Search functionality would run here!")
            st.write("This confirms the webkode processing is working!")

def main():
    if not st.session_state.logged_in:
        login_screen()
    elif not st.session_state.api_authenticated:
        api_screen()
    else:
        main_app()

if __name__ == "__main__":
    main()
