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

# Configure Streamlit page
st.set_page_config(
    page_title="TA Billedhenter",
    page_icon="📸",
    layout="wide"
)

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'jwt_token' not in st.session_state:
    st.session_state.jwt_token = None
if 'api_authenticated' not in st.session_state:
    st.session_state.api_authenticated = False
if 'search_results' not in st.session_state:
    st.session_state.search_results = {}
if 'selected_images' not in st.session_state:
    st.session_state.selected_images = set()

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
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, {"error": f"GraphQL query failed: {response.status_code} - {response.text}"}
                
        except requests.exceptions.RequestException as e:
            return False, {"error": f"Connection error: {str(e)}"}
    
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
        st.write(f"📊 Fundet {len(media_files)} Samlet antal billeder")
        
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
                        
                        st.write(f"🔍 Looking for alternatives to missing {clean_webkode} (base: {base_product})")
                        
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
                            st.write(f"✅ Found {len(variant_suggestions)} variant alternatives for {clean_webkode}")
                        else:
                            st.write(f"❌ No variant alternatives found for {clean_webkode}")
        
        st.success(f"🎯 Search completed: Found {found_count} total images for {len(results['found'])} webkodes")
        
        return results

def login_screen():
    """Display login screen"""
    st.title("🔐 T&A billedhenter Login")
    st.markdown("Skriv dine loginoplysninger for at fortsætte.")
    
    
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            try:
                # Get credentials from Streamlit secrets
                valid_username = st.secrets["login"]["username"]
                valid_password = st.secrets["login"]["password"]
                
                # Debug output (remove after fixing)
                st.write(f"🔍 Debug: Comparing '{username}' with expected username")
                st.write(f"🔍 Debug: Password lengths - entered: {len(password)}, expected: {len(valid_password)}")
                
                if username == valid_username and password == valid_password:
                    st.session_state.logged_in = True
                    st.success("Login successful!")
                    time.sleep(1)
                    st.rerun()
                elif username and password:
                    st.error("Invalid username or password")
                    st.write(f"🔍 Username match: {username == valid_username}")
                    st.write(f"🔍 Password match: {password == valid_password}")
                else:
                    st.error("Please enter both username and password")
                    
            except KeyError as e:
                st.error(f"Login configuration error: Missing key {e}")
                st.error("Please check your Streamlit secrets configuration.")
                st.code("""
                    Expected secrets format:
                    [login]
                    username = "your_username"
                    password = "your_password"
                """)
            except Exception as e:
                st.error(f"Authentication error: {e}")
    # Debug: Show secrets configuration status
    with st.expander("🔧 Debug: Secrets Configuration", expanded=False):
        try:
            if hasattr(st, 'secrets'):
                st.write("✅ Streamlit secrets are available")
                if "login" in st.secrets:
                    st.write("✅ 'login' section found in secrets")
                    if "username" in st.secrets["login"]:
                        st.write(f"✅ Username configured: '{st.secrets['login']['username']}'")
                    else:
                        st.write("❌ 'username' not found in login secrets")
                    if "password" in st.secrets["login"]:
                        st.write("✅ Password configured (hidden)")
                    else:
                        st.write("❌ 'password' not found in login secrets")
                else:
                    st.write("❌ 'login' section not found in secrets")
                    st.write(f"Available sections: {list(st.secrets.keys())}")
            else:
                st.write("❌ Streamlit secrets not available")
        except Exception as e:
            st.write(f"❌ Error checking secrets: {e}")

def api_credentials_screen():
    """Display API credentials input"""
    st.title("🔑 API adgang")
    st.markdown("Indsæt API koder.")
    
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

def main_application():
    """Main application interface"""
    st.title("📸 TA Billedhenter")
    
    # Initialize downloader
    downloader = ICRTImageDownloader()
    downloader.jwt_token = st.session_state.jwt_token
    
    # File upload section
    st.header("📁 Upload Excel File")
    uploaded_file = st.file_uploader(
        "Choose Excel file with 'Priser' sheet containing 'Webkode' column",
        type=['xlsx', 'xls']
    )
    
    if uploaded_file:
        # Parse Excel file
        webkodes, error = parse_excel_file(uploaded_file)
        
        if error:
            st.error(error)
            return
        
        st.success(f"Found {len(webkodes)} webkodes in Excel file")
        
        # Extract and display project code
        project_code = ""
        if webkodes:
            project_code = downloader.extract_project_code(webkodes[0])
        
        # Project code input
        st.header("🏷️ Project Configuration")
        project_code_input = st.text_input(
            "Project Code (auto-detected or enter manually)",
            value=project_code,
            help="Format: LLDDDDD (e.g., IC20006) or DDDDD"
        )
        
        if st.button("🔍 Search for Images", type="primary"):
            if not project_code_input:
                st.error("Please enter a project code")
                return
            
            with st.spinner("Searching for images..."):
                results = downloader.search_images_for_codes(project_code_input, webkodes)
                st.session_state.search_results = results
        
        # Display search results
        if st.session_state.search_results:
            results = st.session_state.search_results
            
            # Summary
            st.header("📊 Search Results Summary")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Found", len(results['found']))
            with col2:
                st.metric("Missing", len(results['missing']))
            with col3:
                total_images = sum(len(images) for images in results['found'].values())
                st.metric("Total Images", total_images)
            
            # Display found images
            if results['found']:
                st.header("✅ Found Images - Select for Download")
                
                all_images = []
                global_image_counter = 0  # Add global counter for unique keys
                
                for webkode, images in results['found'].items():
                    st.subheader(f"📋 {webkode} ({len(images)} images)")
                    
                    # Display images in a more compact format
                    for idx, image in enumerate(images):
                        # Create truly unique key using global counter
                        global_image_counter += 1
                        image_key = f"img_{global_image_counter}_{webkode}_{image['filename']}"
                        
                        # Simple checkbox without preview or size info
                        selected = st.checkbox(
                            f"📷 {image['filename']}",
                            key=image_key,
                            value=image_key in st.session_state.selected_images
                        )
                        
                        if selected:
                            st.session_state.selected_images.add(image_key)
                            all_images.append(image)
                        elif image_key in st.session_state.selected_images:
                            st.session_state.selected_images.remove(image_key)
                
                # Batch selection controls
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("✅ Select All"):
                        # Clear existing selections and select all with new key format
                        st.session_state.selected_images.clear()
                        counter = 0
                        for webkode, images in results['found'].items():
                            for image in images:
                                counter += 1
                                image_key = f"img_{counter}_{webkode}_{image['filename']}"
                                st.session_state.selected_images.add(image_key)
                        st.rerun()
                
                with col2:
                    if st.button("❌ Deselect All"):
                        st.session_state.selected_images.clear()
                        st.rerun()
                
                # Download section - count selected images (including suggestions)
                all_selected_keys = st.session_state.selected_images
                selected_count = len(all_selected_keys)
                
                if selected_count > 0:
                    st.header(f"⬇️ Download Selected Images ({selected_count})")
                    
                    if st.button("📦 Create Download ZIP", type="primary"):
                        selected_images = []
                        counter = 0
                        
                        # Rebuild the mapping to find selected images from found results
                        for webkode, images in results['found'].items():
                            for image in images:
                                counter += 1
                                image_key = f"img_{counter}_{webkode}_{image['filename']}"
                                if image_key in st.session_state.selected_images:
                                    selected_images.append(image)
                        
                        # Also include selected suggestions
                        if 'suggestions' in results:
                            for webkode, suggestions in results['suggestions'].items():
                                for idx, suggestion in enumerate(suggestions):
                                    suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                                    if suggestion_key in st.session_state.selected_images:
                                        selected_images.append({
                                            'url': suggestion['url'],
                                            'filename': f"{webkode}_{suggestion['filename']}_suggested",
                                            'webkode': webkode
                                        })
                        
                        with st.spinner("Creating ZIP file..."):
                            zip_data = create_download_zip(selected_images)
                            
                            st.download_button(
                                label="💾 Download ZIP File",
                                data=zip_data,
                                file_name=f"icrt_images_{project_code_input}_{int(time.time())}.zip",
                                mime="application/zip"
                            )
            
            # Display missing codes and suggestions
            if results['missing']:
                st.header("❌ Missing Images & Suggestions")
                
                for webkode in results['missing']:
                    if webkode in results.get('suggestions', {}):
                        # Show missing code with suggestions
                        st.write(f"🔍 **{webkode}** - No direct match found")
                        suggestions = results['suggestions'][webkode]
                        
                        st.write(f"💡 **Found {len(suggestions)} suggested alternatives:**")
                        
                        # Display suggestions with selection option
                        for idx, suggestion in enumerate(suggestions):
                            suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                            
                            suggested = st.checkbox(
                                f"📷 {suggestion['filename']} (from {suggestion['webkode']})",
                                key=suggestion_key,
                                value=suggestion_key in st.session_state.selected_images,
                                help=suggestion['suggestion_reason']
                            )
                            
                            if suggested:
                                st.session_state.selected_images.add(suggestion_key)
                            elif suggestion_key in st.session_state.selected_images:
                                st.session_state.selected_images.remove(suggestion_key)
                        
                        st.write("---")
                    else:
                        # No suggestions available
                        st.write(f"• {webkode} - No images or alternatives found")

def main():
    """Main application entry point"""
    # Check login status
    if not st.session_state.logged_in:
        login_screen()
        return
    
    # Check API authentication
    if not st.session_state.api_authenticated:
        api_credentials_screen()
        return
    
    # Sidebar with logout option
    with st.sidebar:
        st.header("🔧 Options")
        if st.button("🚪 Logout"):
            # Clear all session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        st.markdown("---")
        st.markdown("**Status:** ✅ Authenticated")
        st.markdown("**API:** 🟢 Connected")
    
    # Main application
    main_application()

if __name__ == "__main__":
    main()