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

class ICRTImageDownloader:
    """ICRT API handler for image downloading"""
    
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
                self.jwt_token = auth_response.text  # Token is returned directly as text
                return True, "Authentication successful!"
                
        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"
    
    def query_graphql_with_variables(self, query: str, variables: dict) -> Tuple[bool, Dict]:
        """Execute GraphQL query with variables"""
        if not self.jwt_token:
            return False, {"error": "Not authenticated"}
        
        try:
            headers = {
                "Authorization": f"Bearer {self.jwt_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "query": query,
                "variables": variables
            }
            
            response = requests.post(
                f"{self.base_url}/graphql",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            # Check if token is expired (401 error)
            if response.status_code == 401:
                error_data = response.json() if response.headers.get('content-type') == 'application/json' else {}
                if 'jwt expired' in str(error_data).lower() or 'expired' in str(error_data).lower():
                    return False, {"error": "jwt_expired", "message": "JWT token has expired. Please re-authenticate."}
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, {"error": f"GraphQL query failed: {response.status_code} - {response.text}"}
                
        except requests.exceptions.RequestException as e:
            return False, {"error": f"Connection error: {str(e)}"}
    
    def refresh_authentication(self) -> bool:
        """Try to refresh authentication using stored credentials"""
        return False
    
    def extract_project_code(self, webkode: str) -> str:
        """Extract project code from webkode"""
        # Pattern: LLDDDDD-DDDD-DD or DDDDD-DDDD-DD
        match = re.match(r'^([A-Z]{2}\d{5}|\d{5})', webkode)
        return match.group(1) if match else ""
    
    def search_images_for_codes(self, project_code: str, webkodes: List[str]) -> Dict:
        """Search for images matching the webkodes using the proven filtering approach"""
        results = {
            'found': {},
            'missing': [],
            'suggestions': {}
        }
        
        # Create a set of webkodes for faster lookup (convert to lowercase)
        webkode_set = {code.strip().lower() for code in webkodes}
        
        # Build GraphQL query using variables
        query = """
        query GetProjectMedia($icrtcode: String!) {
            project(icrtcode: $icrtcode) {
                name
                media {
                    filename
                    image
                }
            }
        }
        """
        
        variables = {
            'icrtcode': project_code
        }
        
        # Execute query
        success, response = self.query_graphql_with_variables(query, variables)
        
        if not success:
            # Check if JWT expired
            if response.get('error') == 'jwt_expired':
                st.error("🔑 Din session er udløbet. Du skal logge ind igen med dine API-oplysninger.")
                
                # Clear the API authentication state to force re-login
                st.session_state.api_authenticated = False
                st.session_state.jwt_token = None
                
                # Show re-authentication button
                st.warning("Klik på knappen herunder for at gå tilbage til API login-siden.")
                if st.button("🔄 Gå til API Login", type="primary"):
                    st.rerun()
                
                return results
            else:
                st.error(f"Failed to query images: {response.get('error', 'Unknown error')}")
                return results
        
        if 'errors' in response:
            st.error(f"GraphQL errors: {response['errors']}")
            return results
        
        # Extract media data
        project_data = response.get('data', {}).get('project', {})
        if not project_data:
            st.warning(f"Intet project fundet med koden: {project_code}")
            return results
        
        media_files = project_data.get('media', [])
        st.write(f"📊 Samlet antal billeder fundet {len(media_files)} ")
        
        # Use the proven extract_product_code function
        def extract_product_code(filename):
            """Extract product code from filename (your proven method)"""
            if '_' in filename:
                return filename.split('_')[0].strip().lower()
            elif '(' in filename:
                return filename.split('(')[0].strip().lower()
            else:
                return filename.strip().lower()
        
        # Process files with progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        found_count = 0
        
        for i, media in enumerate(media_files):
            if i % 50 == 0:  # Update progress every 50 files
                status_text.text(f"Processing images... {i+1}/{len(media_files)}")
                progress_bar.progress((i + 1) / len(media_files))
            
            filename = media.get('filename', '')
            image_url = media.get('image', '')
            
            if filename and image_url:
                # Extract product code
                product_code = extract_product_code(filename)
                
                # Check for match
                if product_code in webkode_set:
                    found_count += 1
                    
                    # Find original webkode
                    original_webkode = None
                    for original in webkodes:
                        if original.strip().lower() == product_code:
                            original_webkode = original.strip()
                            break
                    
                    if original_webkode:
                        if original_webkode not in results['found']:
                            results['found'][original_webkode] = []
                        
                        results['found'][original_webkode].append({
                            'url': image_url,
                            'filename': filename,
                            'webkode': original_webkode
                        })
        
        # Clean up progress indicators
        progress_bar.empty()
        status_text.empty()
        
        # Identify missing webkodes and look for variant alternatives
        for webkode in webkodes:
            clean_webkode = webkode.strip()
            if clean_webkode not in results['found']:
                results['missing'].append(clean_webkode)
                
                # Look for variant alternatives if this webkode is missing
                # Extract base product code (remove last -DD part)
                if '-' in clean_webkode:
                    parts = clean_webkode.split('-')
                    if len(parts) >= 3:  # Format: LLDDDDD-DDDD-DD
                        base_product = '-'.join(parts[:-1])  # e.g., "OT18486-0047"
                        
                        st.write(f"🔍 Foreslag til alternativer til {clean_webkode} (baseret på: {base_product})")
                        
                        # Search through ALL media files for variants of this base product
                        variant_suggestions = []
                        
                        for media in media_files:
                            filename = media.get('filename', '')
                            if filename:
                                # Extract product code from filename
                                product_code = extract_product_code(filename)
                                
                                # Check if this file belongs to the same base product
                                if '-' in product_code:
                                    file_parts = product_code.split('-')
                                    if len(file_parts) >= 3:
                                        file_base = '-'.join(file_parts[:-1])
                                        
                                        # If same base product but different variant
                                        if file_base.lower() == base_product.lower() and product_code.lower() != clean_webkode.lower():
                                            variant_suggestions.append({
                                                'url': media.get('image', ''),
                                                'filename': filename,
                                                'webkode': product_code,
                                                'original_webkode': clean_webkode,
                                                'suggestion_reason': f"Alternative variant ({product_code}) found for missing variant ({clean_webkode})"
                                            })
                        
                        # Add suggestions to results
                        if variant_suggestions:
                            if 'suggestions' not in results:
                                results['suggestions'] = {}
                            results['suggestions'][clean_webkode] = variant_suggestions
                            st.write(f"✅ Fundet {len(variant_suggestions)} alternativ(-er) til {clean_webkode}")
                        else:
                            st.write(f"❌ No variant alternatives found for {clean_webkode}")
        
        st.success(f"🎯 Søgning afsluttet: Fundet {found_count} billeder til i alt {len(results['found'])} webkoder")
        
        return results

def parse_excel_file(uploaded_file) -> Tuple[Optional[List[str]], Optional[str]]:
    """Parse Excel file and extract webkodes"""
    try:
        # Read Excel file
        excel_data = pd.read_excel(uploaded_file, sheet_name=None)
        
        # Look for "Priser" sheet
        if "Priser" not in excel_data:
            return None, "Sheet 'Priser' not found in Excel file"
        
        df = excel_data["Priser"]
        
        # Look for "Webkode" in the first several rows
        webkode_col = None
        header_row = None
        webkode_variations = ['webkode', 'Webkode', 'WEBKODE', 'Web kode', 'WebKode']
        
        for row_idx in range(min(6, len(df))):
            row_data = df.iloc[row_idx].fillna('')
            for col_idx, cell_value in enumerate(row_data):
                cell_str = str(cell_value).strip()
                if cell_str in webkode_variations:
                    webkode_col = col_idx
                    header_row = row_idx
                    break
            if webkode_col is not None:
                break
        
        if webkode_col is None:
            return None, "Column 'Webkode' not found in the first 6 rows of the sheet"
        
        # Extract webkodes from column (starting from the row after headers)
        webkodes = []
        data_start_row = header_row + 1
        
        for i in range(data_start_row, len(df)):
            value = df.iloc[i, webkode_col]
            if pd.notna(value) and str(value).strip():
                webkodes.append(str(value).strip())
        
        if not webkodes:
            return None, "No webkodes found in the Excel file"
        
        return webkodes, None
        
    except Exception as e:
        return None, f"Error parsing Excel file: {str(e)}"

def parse_text_input(text_input: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Parse text input and extract webkodes"""
    try:
        if not text_input.strip():
            return None, "Text input is empty"
        
        # Split by spaces, tabs, newlines, and commas
        # This handles various paste formats
        webkodes = re.split(r'[\s,]+', text_input.strip())
        
        # Filter out empty strings and clean up
        webkodes = [code.strip() for code in webkodes if code.strip()]
        
        if not webkodes:
            return None, "No valid webkodes found in text input"
        
        # Basic validation - check if codes look like webkodes
        valid_webkodes = []
        invalid_codes = []
        
        for code in webkodes:
            # Basic pattern check for webkodes (e.g., IC23022-0072-00 or similar)
            if re.match(r'^[A-Z]{0,2}\d{5}-\d{4}-\d{2}$', code):
                valid_webkodes.append(code)
            else:
                # More lenient check - at least contains numbers and dashes
                if re.search(r'\d', code) and '-' in code:
                    valid_webkodes.append(code)
                else:
                    invalid_codes.append(code)
        
        if invalid_codes:
            st.warning(f"⚠️ Følgende koder ser ikke ud som gyldige webkoder: {', '.join(invalid_codes[:5])}{'...' if len(invalid_codes) > 5 else ''}")
        
        if not valid_webkodes:
            return None, "No valid webkodes found. Expected format: IC23022-0072-00"
        
        return valid_webkodes, None
        
    except Exception as e:
        return None, f"Error parsing text input: {str(e)}"

def create_download_zip(selected_images: List[Dict]) -> bytes:
    """Create ZIP file with selected images"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, image_info in enumerate(selected_images):
            status_text.text(f"Downloading... {i+1}/{len(selected_images)}")
            progress_bar.progress((i + 1) / len(selected_images))
            
            try:
                response = requests.get(image_info['url'], timeout=30)
                if response.status_code == 200:
                    zip_file.writestr(image_info['filename'] + '.jpg', response.content)
            except Exception as e:
                st.warning(f"Failed to download {image_info['filename']}: {str(e)}")
        
        progress_bar.empty()
        status_text.empty()
    
    return zip_buffer.getvalue()

def api_credentials_screen():
    """Display API credentials input"""
    st.subheader("Indsæt API adgangkode 🔑")
        
    with st.form("api_credentials"):
        client_id = st.text_input("Client ID")
        client_key = st.text_input("Client Key", type="password")
        submitted = st.form_submit_button("Godkend")
        
        if submitted:
            if client_id and client_key:
                with st.spinner("Authenticating with ICRT API..."):
                    downloader = ICRTImageDownloader()
                    success, message = downloader.authenticate_api(client_id, client_key)
                    
                    if success:
                        st.session_state.jwt_token = downloader.jwt_token
                        st.session_state.api_authenticated = True
                        st.success(message)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(message)
            else:
                st.error("Please enter both Client ID and Client Key")