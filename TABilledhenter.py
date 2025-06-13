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
    
    def process_webkodes(self, webkodes: List[str]) -> Tuple[List[str], Dict[str, str]]:
        """Process webkodes: strip letters if they start with two letters, maintain mapping"""
        processed_codes = []
        original_mapping = {}  # Maps processed code back to original
        
        for code in webkodes:
            clean_code = code.strip()
            # Check if starts with two letters followed by numbers
            if re.match(r'^[A-Z]{2}\d', clean_code):
                # Remove the first two letters
                processed_code = clean_code[2:]
                st.write(f"🔄 Stripped letters: '{clean_code}' → '{processed_code}'")
            else:
                # Keep as is
                processed_code = clean_code
                st.write(f"✅ Kept as is: '{clean_code}'")
            
            processed_codes.append(processed_code)
            original_mapping[processed_code.lower()] = clean_code
        
        return processed_codes, original_mapping
    
    def search_images_for_codes(self, project_code: str, webkodes: List[str]) -> Dict:
        """Search for images matching the webkodes using the proven filtering approach"""
        results = {
            'found': {},
            'missing': [],
            'suggestions': {}
        }
        
        # Process webkodes: strip letters if needed and maintain mapping
        processed_codes, original_mapping = self.process_webkodes(webkodes)
        
        # Create a set of processed webkodes for faster lookup (convert to lowercase)
        webkode_set = {code.strip().lower() for code in processed_codes}
        
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
            if (response.get('error') == 'jwt_expired' or 
                '401' in str(response.get('error', '')) or 
                'jwt expired' in str(response.get('error', '')).lower()):
                
                st.error("🔑 Din session er udløbet. Du skal logge ind igen med dine API-oplysninger.")
                
                # Clear the API authentication state to force re-login
                st.session_state.api_authenticated = False
                st.session_state.jwt_token = None
                
                # Show re-authentication button
                st.warning("Klik på knappen herunder for at gå tilbage til API login-siden.")
                if st.button("🔄 Gå til API Login", type="primary", key="reauth_button"):
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
        
        # Debug: Look for our target files specifically
        target_files_found = []
        target_patterns = ['23022-0259', '23022-0263']  # Add your specific test patterns
        
        for media in media_files[:100]:  # Check first 100 files
            filename = media.get('filename', '')
            if any(pattern in filename.lower() for pattern in target_patterns):
                target_files_found.append(filename)
        
        if target_files_found:
            st.write(f"🎯 Found {len(target_files_found)} target files in first 100:")
            for f in target_files_found:
                st.write(f"  - {f}")
        else:
            st.write("❌ No target files found in first 100 files")
        
        for i, media in enumerate(media_files):
            if i % 50 == 0:  # Update progress every 50 files
                status_text.text(f"Processing images... {i+1}/{len(media_files)}")
                progress_bar.progress((i + 1) / len(media_files))
            
            filename = media.get('filename', '')
            image_url = media.get('image', '')
            
            if filename and image_url:
                # Extract product code
                product_code = extract_product_code(filename)
                
                # Debug: Show processing of target files
                if any(pattern in filename.lower() for pattern in target_patterns):
                    st.write(f"🔍 Target file processing:")
                    st.write(f"  Filename: '{filename}'")
                    st.write(f"  Extracted product code: '{product_code}'")
                    st.write(f"  In webkode_set? {product_code in webkode_set}")
                    st.write(f"  Webkode_set contains: {list(webkode_set)}")
                
                # Check for match - CHANGED TO USE "CONTAINS" LOGIC
                matched_code = None
                for search_code in webkode_set:
                    if search_code in product_code.lower():  # Check if search code is contained in filename
                        matched_code = search_code
                        break
                
                if matched_code:
                    found_count += 1
                    
                    # Find original webkode using mapping
                    original_webkode = original_mapping.get(matched_code, matched_code)
                    
                    # Debug: Show successful match
                    st.write(f"✅ MATCH FOUND: '{filename}' contains '{matched_code}' → '{original_webkode}'")
                    
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
        for original_webkode in webkodes:
            clean_webkode = original_webkode.strip()
            if clean_webkode not in results['found']:
                results['missing'].append(clean_webkode)
                
                # Look for variant alternatives if this webkode is missing
                # Extract base product code (remove last -DD part)
                processed_code = processed_codes[webkodes.index(original_webkode)]
                if '-' in processed_code:
                    parts = processed_code.split('-')
                    if len(parts) >= 3:  # Format: DDDDD-DDDD-DD
                        base_product = '-'.join(parts[:-1])  # e.g., "18486-0047"
                        
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
                                        if file_base.lower() == base_product.lower() and product_code.lower() != processed_code.lower():
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
                
                if username == valid_username and password == valid_password:
                    st.session_state.logged_in = True
                    st.success("Login successful!")
                    time.sleep(1)
                    st.rerun()
                elif username and password:
                    st.error("Invalid username or password")
                else:
                    st.error("Please enter both username and password")
                    
            except KeyError as e:
                st.error(f"Login configuration error: Missing key {e}")
                st.error("Please check your Streamlit secrets configuration.")
            except Exception as e:
                st.error(f"Authentication error: {e}")

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
    
    # COMPLETELY NEW SECTION - NO TABS
    st.header("📃 Input webkoder")
    
    # TEST: Show a simple message to confirm this code is running
    st.success("🧪 NEW CODE IS RUNNING - NO MORE TABS!")
    
    # Choose input method with radio buttons
    input_method = st.radio(
        "Vælg input metode:",
        ["📁 Upload Excel fil", "✏️ Indsæt tekst"],
        horizontal=True
    )
    
    webkodes = None
    project_code = ""
    
    if input_method == "📁 Upload Excel fil":
        st.markdown("Upload dit prisark eller webskema")
        uploaded_file = st.file_uploader(
            "Her kan du bruge både prisark og webskema, filen skal bare have en fane der hedder 'Priser' og en kolonneoverskrift i række 3 der hedder 'Webkode'",
            type=['xlsx', 'xls']
        )
        
        if uploaded_file:
            # Parse Excel file
            st.write("🔍 DEBUG: Starting Excel file parsing...")
            webkodes, error = parse_excel_file(uploaded_file)
            
            st.write(f"🔍 DEBUG: Parse result - webkodes: {webkodes is not None}, error: {error}")
            
            if error:
                st.error(error)
                st.write("🔍 DEBUG: Excel parsing failed with error above")
            else:
                st.success(f"✅ Fundet {len(webkodes)} webkoder i Excel-fil")
                st.write(f"🔍 DEBUG: First few webkodes: {webkodes[:3] if webkodes else 'None'}")
                # Extract project code from first webkode
                if webkodes:
                    # Use original webkode (before any letter stripping) to extract project code
                    first_webkode = webkodes[0]
                    project_code = downloader.extract_project_code(first_webkode)
                    st.write(f"🔍 DEBUG: Extracted project code: '{project_code}'")
    
    elif input_method == "✏️ Indsæt tekst":
        st.markdown("Indsæt webkoder direkte fra clipboard")
        text_input = st.text_area(
            "Indsæt webkoder her (adskilt af mellemrum, linjeskift eller kommaer):",
            placeholder="IC23022-0072-00 IC23022-0220-31 IC23022-0050-00\nIC23022-0072-10 IC23022-0054-00",
            height=150,
            help="Du kan indsætte webkoder adskilt af mellemrum, linjeskift eller kommaer"
        )
        
        if text_input:
            # Parse text input
            st.write("🔍 DEBUG: Starting text input parsing...")
            webkodes, error = parse_text_input(text_input)
            
            st.write(f"🔍 DEBUG: Parse result - webkodes: {webkodes is not None}, error: {error}")
            
            if error:
                st.error(error)
                st.write("🔍 DEBUG: Text parsing failed with error above")
            else:
                st.success(f"✅ Fundet {len(webkodes)} webkoder i tekst input")
                st.write(f"🔍 DEBUG: First few webkodes: {webkodes[:3] if webkodes else 'None'}")
                # Show preview of parsed codes
                with st.expander("👀 Vis fundne webkoder", expanded=False):
                    st.write(", ".join(webkodes[:20]))
                    if len(webkodes) > 20:
                        st.write(f"... og {len(webkodes) - 20} flere")
                
                # Extract project code from first webkode
                if webkodes:
                    # Use original webkode (before any letter stripping) to extract project code
                    first_webkode = webkodes[0]
                    project_code = downloader.extract_project_code(first_webkode)
                    st.write(f"🔍 DEBUG: Extracted project code: '{project_code}'")

    # Continue with the rest of the processing if webkodes were found
    if webkodes:
        # ADD SIMPLE DEBUG TEST HERE
        st.warning("🧪 DEBUG TEST: This should always be visible if webkodes were found!")
        st.write(f"Number of webkodes found: {len(webkodes)}")
        st.write(f"First webkode: {webkodes[0] if webkodes else 'None'}")
        
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
            
            # Show debug BEFORE calling the search function
            st.header("🔍 Debug: Webkoder der bruges til søgning")
            
            # Process webkodes here to show debug info
            processed_codes, original_mapping = downloader.process_webkodes(webkodes)
            webkode_set = {code.strip().lower() for code in processed_codes}
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📝 Original input")
                for i, code in enumerate(webkodes, 1):
                    st.write(f"{i}. `{code}`")
            
            with col2:
                st.subheader("🔄 Processeret til søgning")
                for i, code in enumerate(processed_codes, 1):
                    st.write(f"{i}. `{code}`")
            
            st.subheader("🎯 Finale søgesæt (lowercase)")
            st.write(", ".join(f"`{code}`" for code in sorted(webkode_set)))
            
            st.subheader("🗺️ Mapping tilbage")
            for processed, original in original_mapping.items():
                st.write(f"`{processed}` → `{original}`")
            
            st.markdown("---")
            
            with st.spinner("Søger efter filer..."):
                results = downloader.search_images_for_codes(project_code_input, webkodes)
                st.session_state.search_results = results
                # Clear the keys registry when new search is performed
                st.session_state.image_keys_registry = {}

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