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
if 'image_keys_registry' not in st.session_state:
    st.session_state.image_keys_registry = {}

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
        # Note: We can't automatically refresh without storing credentials
        # This would require the user to re-enter their API credentials
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
        # Also create a set of numeric parts for flexible matching
        numeric_webkode_set = {extract_numeric_part(code.strip()) for code in webkodes}
        
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
        
        def extract_numeric_part(code):
            """Extract numeric part from webcode (e.g., IC23022-0259-00 -> 23022-0259-00)"""
            # Remove letters from the beginning and return the numeric part with dashes
            match = re.search(r'(\d+(?:-\d+)*)', code)
            return match.group(1).lower() if match else code.lower()
        
        # Process files with progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        found_count = 0
        
        # Debug: Show what we're looking for
        st.write(f"🔍 Debug: Looking for these webkodes:")
        for code in webkodes[:5]:  # Show first 5
            numeric_part = extract_numeric_part(code.strip())
            st.write(f"  - Full: '{code.strip().lower()}' | Numeric: '{numeric_part}'")
        if len(webkodes) > 5:
            st.write(f"  ... and {len(webkodes) - 5} more")
        
        for i, media in enumerate(media_files):
            if i % 50 == 0:  # Update progress every 50 files
                status_text.text(f"Processing images... {i+1}/{len(media_files)}")
                progress_bar.progress((i + 1) / len(media_files))
            
            filename = media.get('filename', '')
            image_url = media.get('image', '')
            
            if filename and image_url:
                # Extract product code
                product_code = extract_product_code(filename)
                numeric_product_code = extract_numeric_part(product_code)
                
                # Debug: Show some examples of what we find
                if i < 10:  # Show first 10 files
                    st.write(f"📁 Debug file {i+1}: '{filename}' -> Full: '{product_code}' | Numeric: '{numeric_product_code}'")
                
                # Check for match (both full match and numeric match)
                matched_webkode = None
                match_type = ""
                
                # First try exact match
                if product_code in webkode_set:
                    # Find original webkode
                    for original in webkodes:
                        if original.strip().lower() == product_code:
                            matched_webkode = original.strip()
                            match_type = "exact"
                            break
                
                # If no exact match, try numeric match
                elif numeric_product_code in numeric_webkode_set:
                    # Find original webkode by numeric part
                    for original in webkodes:
                        if extract_numeric_part(original.strip()) == numeric_product_code:
                            matched_webkode = original.strip()
                            match_type = "numeric"
                            break
                
                if matched_webkode:
                    found_count += 1
                    
                    # Debug: Show successful matches
                    if found_count <= 5:  # Show first 5 matches
                        st.write(f"✅ Match {found_count}: '{filename}' -> '{matched_webkode}' ({match_type} match)")
                    
                    if matched_webkode not in results['found']:
                        results['found'][matched_webkode] = []
                    
                    results['found'][matched_webkode].append({
                        'url': image_url,
                        'filename': filename,
                        'webkode': matched_webkode
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
                                        
                                        # If same base product but different variant (using numeric matching)
                                        if (file_base.lower() == base_product.lower() or 
                                            extract_numeric_part(file_base) == extract_numeric_part(base_product)) and \
                                           product_code.lower() != clean_webkode.lower():
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

def parse_text_input(text_input: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Parse text input and extract webkodes"""
    try:
        if not text_input.strip():
            return None, "Text input is empty"
        
        # Split by spaces, tabs, newlines, and commas
        # This handles various paste formats
        import re
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

def main_application():
    """Main application interface"""
    st.title("🚚 TA Billedhenter")
    
    # Initialize downloader
    downloader = ICRTImageDownloader()
    downloader.jwt_token = st.session_state.jwt_token
    
    # File upload section
    st.header("📃 Input webkoder")
    
    # Create tabs for different input methods
    tab1, tab2 = st.tabs(["📁 Upload Excel fil", "✏️ Indsæt tekst"])
    
    webkodes = None
    project_code = ""
    
    with tab1:
        st.markdown("Upload dit prisark eller webskema")
        uploaded_file = st.file_uploader(
            "Her kan du bruge både prisark og webskema, filen skal bare have en fane der hedder 'Priser' og en kolonneoverskrift i række 3 der hedder 'Webkode'",
            type=['xlsx', 'xls']
        )
        
        if uploaded_file:
            # Parse Excel file
            webkodes, error = parse_excel_file(uploaded_file)
            
            if error:
                st.error(error)
            else:
                st.success(f"✅ Fundet {len(webkodes)} webkoder i Excel-fil")
                # Extract project code from first webkode
                if webkodes:
                    project_code = downloader.extract_project_code(webkodes[0])
    
    with tab2:
        st.markdown("Indsæt webkoder direkte fra clipboard")
        text_input = st.text_area(
            "Indsæt webkoder her (adskilt af mellemrum, linjeskift eller kommaer):",
            placeholder="IC23022-0072-00 IC23022-0220-31 IC23022-0050-00\nIC23022-0072-10 IC23022-0054-00",
            height=150,
            help="Du kan indsætte webkoder adskilt af mellemrum, linjeskift eller kommaer"
        )
        
        if text_input:
            # Parse text input
            webkodes, error = parse_text_input(text_input)
            
            if error:
                st.error(error)
            else:
                st.success(f"✅ Fundet {len(webkodes)} webkoder i tekst input")
                # Show preview of parsed codes
                with st.expander("👀 Vis fundne webkoder", expanded=False):
                    st.write(", ".join(webkodes[:20]))
                    if len(webkodes) > 20:
                        st.write(f"... og {len(webkodes) - 20} flere")
                
                # Extract project code from first webkode
                if webkodes:
                    project_code = downloader.extract_project_code(webkodes[0])
    
    # Continue with the rest of the processing if webkodes were found
    if webkodes:
        # Project code input
        st.header("🏷️ Tjek projekt-koden")
        project_code_input = st.text_input(
            "Projektkoden bliver hentet automatisk fra den første webkode, men kan tilpasses hvis ikke den bliver genkendt rigtigt.",
            value=project_code,
            help="Format: LLDDDDD (e.g., IC20006) or DDDDD"
        )
        
        if st.button("🔍 Find billedfiler", type="primary"):
            if not project_code_input:
                st.error("Projectkode ikke fundet, prøv igen")
                return
            
            with st.spinner("Søger efter filer..."):
                results = downloader.search_images_for_codes(project_code_input, webkodes)
                st.session_state.search_results = results
                # Clear the keys registry when new search is performed
                st.session_state.image_keys_registry = {}
        
        # Display search results
        if st.session_state.search_results:
            results = st.session_state.search_results
            
            # Summary
            st.header("📊 Filer fundet")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Fundet", len(results['found']))
            with col2:
                st.metric("Mangler", len(results['missing']))
            with col3:
                total_images = sum(len(images) for images in results['found'].values())
                st.metric("Fundet billeder i alt", total_images)

            # Display found images and suggestions in merged format
            if results['found'] or results['missing']:
                st.header("✅ Vælg de billeder du vil hente ned")
                
                all_images = []
                global_image_counter = 0  # Add global counter for unique keys
                
                # Build a registry of all keys and their corresponding images
                # This ensures consistency between display and batch selection
                keys_registry = {}
                
                # First pass: register all found images
                sorted_found_items = sorted(results['found'].items())
                for webkode, images in sorted_found_items:
                    # Sort images within each webkode
                    sorted_images = sorted(images, key=lambda x: x['filename'])
                    
                    # Detect duplicates within this webkode
                    filename_counts = {}
                    for image in sorted_images:
                        filename = image['filename']
                        filename_counts[filename] = filename_counts.get(filename, 0) + 1
                    
                    # Register images with consistent keys
                    filename_occurrence = {}
                    for idx, image in enumerate(sorted_images):
                        filename = image['filename']
                        
                        # Track occurrence of this filename
                        if filename not in filename_occurrence:
                            filename_occurrence[filename] = 0
                        filename_occurrence[filename] += 1
                        
                        # Create truly unique key using global counter
                        global_image_counter += 1
                        image_key = f"img_{global_image_counter}_{webkode}_{image['filename']}"
                        
                        # Store in registry
                        keys_registry[image_key] = {
                            'type': 'found',
                            'webkode': webkode,
                            'image': image,
                            'is_duplicate': filename_counts[filename] > 1,
                            'duplicate_number': filename_occurrence[filename] if filename_counts[filename] > 1 else None
                        }
                
                # Second pass: register all suggestions
                if results['missing']:
                    sorted_missing = sorted(results['missing'])
                    
                    for webkode in sorted_missing:
                        if webkode in results.get('suggestions', {}):
                            suggestions = results['suggestions'][webkode]
                            # Sort suggestions by filename
                            sorted_suggestions = sorted(suggestions, key=lambda x: x['filename'])
                            
                            # Detect duplicates within suggestions
                            suggestion_filenames = [suggestion['filename'] for suggestion in sorted_suggestions]
                            suggestion_filename_counts = {}
                            for filename in suggestion_filenames:
                                suggestion_filename_counts[filename] = suggestion_filename_counts.get(filename, 0) + 1
                            
                            # Register suggestions with consistent keys
                            suggestion_filename_occurrence = {}
                            for idx, suggestion in enumerate(sorted_suggestions):
                                filename = suggestion['filename']
                                
                                # Track occurrence of this filename
                                if filename not in suggestion_filename_occurrence:
                                    suggestion_filename_occurrence[filename] = 0
                                suggestion_filename_occurrence[filename] += 1
                                
                                suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                                
                                # Store in registry
                                keys_registry[suggestion_key] = {
                                    'type': 'suggestion',
                                    'webkode': webkode,
                                    'image': suggestion,
                                    'is_duplicate': suggestion_filename_counts[filename] > 1,
                                    'duplicate_number': suggestion_filename_occurrence[filename] if suggestion_filename_counts[filename] > 1 else None
                                }
                
                # Store registry in session state
                st.session_state.image_keys_registry = keys_registry
                
                # Now display the images using the registry
                for webkode, images in sorted_found_items:
                    sorted_images = sorted(images, key=lambda x: x['filename'])
                    
                    st.subheader(f"📋 {webkode} ({len(sorted_images)} billeder)")
                    
                    # Find keys for this webkode from registry
                    webkode_keys = [key for key, data in keys_registry.items() 
                                   if data['type'] == 'found' and data['webkode'] == webkode]
                    
                    for key in webkode_keys:
                        data = keys_registry[key]
                        image = data['image']
                        is_duplicate = data['is_duplicate']
                        duplicate_number = data['duplicate_number']
                        
                        # Create display name
                        if is_duplicate:
                            duplicate_suffix = f" (kopi #{duplicate_number})"
                            display_name = f"🔄 {image['filename']}{duplicate_suffix}"
                        else:
                            display_name = f"📷 {image['filename']}"
                        
                        # Display checkbox
                        selected = st.checkbox(
                            display_name,
                            key=key,
                            value=key in st.session_state.selected_images,
                            help="Duplikat billede fundet" if is_duplicate else None
                        )
                        
                        # Update selection state
                        if selected:
                            st.session_state.selected_images.add(key)
                        elif key in st.session_state.selected_images:
                            st.session_state.selected_images.remove(key)
                
                # Display missing codes with suggestions
                if results['missing']:
                    st.subheader("💡 Foreslåede alternativer for manglende billeder")
                    
                    for webkode in sorted_missing:
                        if webkode in results.get('suggestions', {}):
                            # Show missing code with suggestions
                            st.write(f"🔍 **{webkode}** - Intet direkte match fundet")
                            suggestions = results['suggestions'][webkode]
                            st.write(f"💡 **Fundet {len(suggestions)} alternativer:**")
                            
                            # Find keys for this webkode's suggestions from registry
                            suggestion_keys = [key for key, data in keys_registry.items() 
                                             if data['type'] == 'suggestion' and data['webkode'] == webkode]
                            
                            for key in suggestion_keys:
                                data = keys_registry[key]
                                suggestion = data['image']
                                is_duplicate = data['is_duplicate']
                                duplicate_number = data['duplicate_number']
                                
                                # Create display name
                                if is_duplicate:
                                    duplicate_suffix = f" (kopi #{duplicate_number})"
                                    display_name = f"🔄 {suggestion['filename']}{duplicate_suffix} (fra {suggestion['webkode']})"
                                    help_text = f"{suggestion['suggestion_reason']} - Duplikat #{duplicate_number}"
                                else:
                                    display_name = f"📷 {suggestion['filename']} (fra {suggestion['webkode']})"
                                    help_text = suggestion['suggestion_reason']
                                
                                # Display checkbox
                                suggested = st.checkbox(
                                    display_name,
                                    key=key,
                                    value=key in st.session_state.selected_images,
                                    help=help_text
                                )
                                
                                # Update selection state
                                if suggested:
                                    st.session_state.selected_images.add(key)
                                elif key in st.session_state.selected_images:
                                    st.session_state.selected_images.remove(key)
                        else:
                            # No suggestions available
                            st.write(f"• **{webkode}** - Ingen alternativer fundet")
                
                # Add rename option for alternatives
                st.subheader("⚙️ Indstillinger")
                rename_alternatives = st.checkbox(
                    "🔄 Omdøb alternative filer til det ønskede variant-nummer",
                    help="Eksempel: AB23456-0023-00_01 → AB23456-0023-50_01 hvis du søgte efter AB23456-0023-50"
                )
                
                # Batch selection controls - now using the registry for consistency
                st.subheader("🎛️ Vælg flere ad gangen")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    if st.button("✅ Vælg alle inkl. forslag"):
                        # Clear existing selections and select all using registry keys
                        st.session_state.selected_images.clear()
                        
                        # Select all keys from registry
                        for key in keys_registry.keys():
                            st.session_state.selected_images.add(key)
                        
                        st.rerun()
                
                with col2:
                    if st.button("🎯 Vælg kun hele matches"):
                        # Clear existing selections and select only exact matches using registry
                        st.session_state.selected_images.clear()
                        
                        # Select only found images (no suggestions)
                        for key, data in keys_registry.items():
                            if data['type'] == 'found':
                                st.session_state.selected_images.add(key)
                        
                        st.rerun()
                
                with col3:
                    if st.button("🔄 Fravælg dubletter"):
                        # Remove duplicates from selection (keep only copy #1 of each duplicate)
                        keys_to_remove = set()
                        
                        # Check registry for duplicates
                        for key, data in keys_registry.items():
                            if data['is_duplicate'] and data['duplicate_number'] > 1:
                                keys_to_remove.add(key)
                        
                        # Remove the duplicate keys
                        for key in keys_to_remove:
                            st.session_state.selected_images.discard(key)
                        
                        st.rerun()
                
                with col4:
                    if st.button("❌ Fravælg alle"):
                        st.session_state.selected_images.clear()
                        st.rerun()
                
                # Download section - count selected images (including suggestions)
                all_selected_keys = st.session_state.selected_images
                selected_count = len(all_selected_keys)
                
                if selected_count > 0:
                    st.header(f"⬇️ Hent valgte billeder ({selected_count})")
                    
                    # Check if too many images are selected
                    MAX_IMAGES_PER_ZIP = 300
                    
                    if selected_count > MAX_IMAGES_PER_ZIP:
                        st.error(f"⚠️ **For mange billeder valgt!**")
                        st.warning(f"Du har valgt **{selected_count} billeder**, men maksimum er **{MAX_IMAGES_PER_ZIP} billeder** per download.")
                        st.info(f"💡 **Løsninger:**")
                        st.markdown(f"""
                        - **Fravælg nogle billeder** og prøv igen
                        - **Brug 'Fravælg dubletter'** knappen for at reducere antallet
                        - **Download i mindre portioner** - vælg færre billeder ad gangen
                        """)
                        
                        # Show how many to remove
                        excess_count = selected_count - MAX_IMAGES_PER_ZIP
                        st.markdown(f"🎯 **Du skal fravælge {excess_count} billeder for at fortsætte**")
                        
                    else:
                        # Safe to proceed with download
                        if selected_count <= 100:
                            zip_size_estimate = "lille"
                            zip_color = "🟢"
                        elif selected_count <= 200:
                            zip_size_estimate = "medium"
                            zip_color = "🟡"
                        else:
                            zip_size_estimate = "stor"
                            zip_color = "🟠"
                        
                        st.info(f"{zip_color} **ZIP størrelse**: {zip_size_estimate} (~{selected_count * 0.2:.1f}MB estimeret)")
                    
                    if selected_count <= MAX_IMAGES_PER_ZIP and st.button("📦 Pak og download ZIP fil", type="primary"):
                        selected_images = []
                        
                        # Use the registry to build selected images list
                        duplicate_counter = {}
                        
                        for key in st.session_state.selected_images:
                            if key in keys_registry:
                                data = keys_registry[key]
                                image = data['image']
                                webkode = data['webkode']
                                
                                if data['type'] == 'found':
                                    # Handle duplicate filenames for found images
                                    original_filename = image['filename']
                                    if original_filename in duplicate_counter:
                                        duplicate_counter[original_filename] += 1
                                        final_filename = f"{original_filename}_kopi{duplicate_counter[original_filename]}"
                                    else:
                                        duplicate_counter[original_filename] = 0
                                        final_filename = original_filename
                                    
                                    # Create image with final filename
                                    final_image = image.copy()
                                    final_image['filename'] = final_filename
                                    selected_images.append(final_image)
                                
                                elif data['type'] == 'suggestion':
                                    # Handle suggestions with optional renaming
                                    if rename_alternatives:
                                        # Extract the original variant from the searched webkode
                                        if '-' in webkode:
                                            parts = webkode.split('-')
                                            if len(parts) >= 3:
                                                desired_variant = parts[-1]  # e.g., "50"
                                                
                                                # Replace the variant in the filename
                                                original_filename = image['filename']
                                                if '_' in original_filename:
                                                    base_part = original_filename.split('_')[0]  # e.g., "AB23456-0023-00"
                                                    suffix_part = original_filename.split('_')[1]  # e.g., "01"
                                                    
                                                    # Replace the last variant part
                                                    if '-' in base_part:
                                                        base_parts = base_part.split('-')
                                                        if len(base_parts) >= 3:
                                                            base_parts[-1] = desired_variant  # Replace "00" with "50"
                                                            new_filename = '-'.join(base_parts) + '_' + suffix_part
                                                        else:
                                                            new_filename = f"{webkode}_{original_filename}_renamed"
                                                    else:
                                                        new_filename = f"{webkode}_{original_filename}_renamed"
                                                else:
                                                    new_filename = f"{webkode}_{original_filename}_renamed"
                                            else:
                                                new_filename = f"{webkode}_{image['filename']}_suggested"
                                        else:
                                            new_filename = f"{webkode}_{image['filename']}_suggested"
                                    else:
                                        new_filename = f"{webkode}_{image['filename']}_suggested"
                                    
                                    # Handle duplicates for suggestions too
                                    if new_filename in duplicate_counter:
                                        duplicate_counter[new_filename] += 1
                                        final_filename = f"{new_filename}_kopi{duplicate_counter[new_filename]}"
                                    else:
                                        duplicate_counter[new_filename] = 0
                                        final_filename = new_filename
                                    
                                    selected_images.append({
                                        'url': image['url'],
                                        'filename': final_filename,
                                        'webkode': webkode
                                    })
                        
                        with st.spinner("Pakker dine filer..."):
                            zip_data = create_download_zip(selected_images)
                            
                            st.download_button(
                                label="💾 Klik her hvis download ikke starter automatisk",
                                data=zip_data,
                                file_name=f"icrt_images_{project_code_input}_{int(time.time())}.zip",
                                mime="application/zip",
                                use_container_width=True
                            )
                            st.success("✅ ZIP fil er klar til download!")

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
        st.header("🕹️ Menu")
        if st.button("👋 Log ud"):
            # Clear all session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        st.markdown("---")
        st.markdown("**Status:** ✅ Logget ind")
        st.markdown("**API:** 🟢 Forbundet")
    
    # Main application
    main_application()

if __name__ == "__main__":
    main()