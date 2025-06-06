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
from datetime import datetime
from streamlit_extras.customize_running import center_running

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
if 'available_dates' not in st.session_state:
    st.session_state.available_dates = []

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
    
    def fetch_available_dates(self, project_code: str) -> List[str]:
        """Fetch available modification dates from the project"""
        # GraphQL query to fetch media with modified dates
        query = """
        query GetProjectMediaDates($icrtcode: String!) {
            project(icrtcode: $icrtcode) {
                name
                media {
                    filename
                    modified
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
            st.error(f"Failed to fetch dates: {response.get('error', 'Unknown error')}")
            return []
        
        if 'errors' in response:
            st.error(f"GraphQL errors: {response['errors']}")
            return []
        
        # Extract media data
        project_data = response.get('data', {}).get('project', {})
        if not project_data:
            return []
        
        media_files = project_data.get('media', [])
        
        # Extract unique year-month combinations
        date_set = set()
        for media in media_files:
            modified_date = media.get('modified')
            if modified_date:
                try:
                    # Parse the ISO date string: "2020-12-03T20:37:06.581Z"
                    dt = datetime.fromisoformat(modified_date.replace('Z', '+00:00'))
                    year_month = dt.strftime('%Y-%m')
                    date_set.add(year_month)
                except Exception as e:
                    # Skip invalid dates
                    continue
        
        # Sort dates in descending order (newest first)
        sorted_dates = sorted(list(date_set), reverse=True)
        return sorted_dates
    
    def search_images_for_codes(self, project_code: str, webkodes: List[str], selected_date_filters: List[str] = None) -> Dict:
        """Search for images matching the webkodes with optional date filtering"""
        results = {
            'found': {},
            'missing': [],
            'suggestions': {}
        }
        
        # Create a set of webkodes for faster lookup (convert to lowercase)
        webkode_set = {code.strip().lower() for code in webkodes}
        
        # Build GraphQL query using variables - now including modified date
        query = """
        query GetProjectMedia($icrtcode: String!) {
            project(icrtcode: $icrtcode) {
                name
                media {
                    filename
                    image
                    modified
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
        
        # Filter by date if date filters are selected
        if selected_date_filters:
            filtered_media = []
            for media in media_files:
                modified_date = media.get('modified')
                if modified_date:
                    try:
                        dt = datetime.fromisoformat(modified_date.replace('Z', '+00:00'))
                        year_month = dt.strftime('%Y-%m')
                        if year_month in selected_date_filters:
                            filtered_media.append(media)
                    except:
                        # Skip files with invalid dates
                        continue
                else:
                    # Include files without modification dates if you want to be inclusive
                    # Comment out this line if you want to exclude files without dates
                    filtered_media.append(media)
            
            media_files = filtered_media
        
        st.write(f"📊 Samlet antal billeder fundet {len(media_files)} ")
        if selected_date_filters:
            st.write(f"🗓️ Filtreret efter måneder: {', '.join(selected_date_filters)}")
        
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
            modified_date = media.get('modified', '')
            
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
                            'webkode': original_webkode,
                            'modified': modified_date
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
                                                'modified': media.get('modified', ''),
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

def format_date_for_display(date_str: str) -> str:
    """Convert YYYY-MM format to a more readable format"""
    try:
        year, month = date_str.split('-')
        month_names = {
            '01': 'Januar', '02': 'Februar', '03': 'Marts', '04': 'April',
            '05': 'Maj', '06': 'Juni', '07': 'Juli', '08': 'August',
            '09': 'September', '10': 'Oktober', '11': 'November', '12': 'December'
        }
        return f"{month_names.get(month, month)} {year}"
    except:
        return date_str

def main_application():
    """Main application interface"""
    st.title("🚚 TA Billedhenter")
    
    # Initialize downloader
    downloader = ICRTImageDownloader()
    downloader.jwt_token = st.session_state.jwt_token
    
    # File upload section
    st.header("📃 Upload dit prisark eller webskema")
    uploaded_file = st.file_uploader(
        "Her kan du bruge både prisark og webskema, filen skal bare have en fane der hedder 'Priser' og en kolonneoverskrift i række 3 der hedder 'Webkode' ",
        type=['xlsx', 'xls']
    )
    
    if uploaded_file:
        # Parse Excel file
        webkodes, error = parse_excel_file(uploaded_file)
        
        if error:
            st.error(error)
            return
        
        st.success(f"Fundet {len(webkodes)} webkoder i Excel-fil")
        
        # Extract and display project code
        project_code = ""
        if webkodes:
            project_code = downloader.extract_project_code(webkodes[0])
        
        # Project code input
        st.header("🏷️ Tjek projekt-koden")
        project_code_input = st.text_input(
            "Projektkoden bliver hentet automatisk fra prisark/webskema, men kan tilpasses hvis ikke den bliver genkendt rigtigt.",
            value=project_code,
            help="Format: LLDDDDD (e.g., IC20006) or DDDDD"
        )
        
        # Fetch available dates when project code is available
        if project_code_input and st.button("🗓️ Hent tilgængelige datoer", help="Klik for at se hvilke måneder der er billeder fra"):
            with st.spinner("Henter tilgængelige datoer..."):
                available_dates = downloader.fetch_available_dates(project_code_input)
                st.session_state.available_dates = available_dates
                if available_dates:
                    st.success(f"Fundet billeder fra {len(available_dates)} forskellige måneder")
                else:
                    st.warning("Ingen datoer fundet eller fejl ved hentning")
        
        # Date filtering section
        if st.session_state.available_dates:
            st.header("🗓️ Vælg måneder (valgfrit)")
            st.markdown("Vælg specifikke måneder hvis du kun vil have billeder fra bestemte perioder. Lad feltet tomt for at få alle billeder.")
            
            # Create options for multiselect
            date_options = []
            for date in st.session_state.available_dates:
                display_name = format_date_for_display(date)
                date_options.append({"value": date, "display": f"{display_name} ({date})"})
            
            selected_date_filters = st.multiselect(
                "Vælg måneder:",
                options=[opt["value"] for opt in date_options],
                format_func=lambda x: next(opt["display"] for opt in date_options if opt["value"] == x),
                help="Du kan vælge flere måneder. Lad feltet tomt for at inkludere alle billeder."
            )
            
            if selected_date_filters:
                st.info(f"Filtrerer efter {len(selected_date_filters)} måned(er): {', '.join([format_date_for_display(d) for d in selected_date_filters])}")
        else:
            selected_date_filters = None
        
        if st.button("🔍 Find billedfiler", type="primary"):
            if not project_code_input:
                st.error("Projectkode ikke fundet, prøv igen")
                return
            
            with st.spinner("Søger efter filer..."):
                results = downloader.search_images_for_codes(project_code_input, webkodes, selected_date_filters)
                st.session_state.search_results = results
        
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
                
                # First show all found images (sorted)
                sorted_found_items = sorted(results['found'].items())
                for webkode, images in sorted_found_items:
                    # Sort images within each webkode
                    sorted_images = sorted(images, key=lambda x: x['filename'])
                    
                    st.subheader(f"📋 {webkode} ({len(sorted_images)} billeder)")
                    
                    # Detect duplicates within this webkode
                    filename_counts = {}
                    for image in sorted_images:
                        filename = image['filename']
                        filename_counts[filename] = filename_counts.get(filename, 0) + 1
                    
                    # Display images in a more compact format
                    filename_occurrence = {}
                    for idx, image in enumerate(sorted_images):
                        filename = image['filename']
                        modified_date = image.get('modified', '')
                        
                        # Track occurrence of this filename
                        if filename not in filename_occurrence:
                            filename_occurrence[filename] = 0
                        filename_occurrence[filename] += 1
                        
                        # Create truly unique key using global counter
                        global_image_counter += 1
                        image_key = f"img_{global_image_counter}_{webkode}_{image['filename']}"
                        
                        # Add duplicate indicator if needed
                        is_duplicate = filename_counts[filename] > 1
                        if is_duplicate:
                            duplicate_suffix = f" (kopi #{filename_occurrence[filename]})"
                            display_name = f"🔄 {filename}{duplicate_suffix}"
                        else:
                            display_name = f"📷 {filename}"
                        
                        # Add date info if available
                        if modified_date:
                            try:
                                dt = datetime.fromisoformat(modified_date.replace('Z', '+00:00'))
                                date_str = dt.strftime('%Y-%m-%d')
                                display_name += f" (ændret: {date_str})"
                            except:
                                pass
                        
                        # Simple checkbox with duplicate highlighting
                        selected = st.checkbox(
                            display_name,
                            key=image_key,
                            value=image_key in st.session_state.selected_images,
                            help="Duplikat billede fundet" if is_duplicate else None
                        )
                        
                        if selected:
                            st.session_state.selected_images.add(image_key)
                            # Add duplicate info to image for later processing
                            image_with_duplicate_info = image.copy()
                            image_with_duplicate_info['is_duplicate'] = is_duplicate
                            image_with_duplicate_info['duplicate_number'] = filename_occurrence[filename] if is_duplicate else None
                            all_images.append(image_with_duplicate_info)
                        elif image_key in st.session_state.selected_images:
                            st.session_state.selected_images.remove(image_key)
                
                # Then show missing codes with suggestions (sorted)
                if results['missing']:
                    st.subheader("💡 Foreslåede alternativer for manglende billeder")
                    
                    # Sort missing webkodes
                    sorted_missing = sorted(results['missing'])
                    
                    for webkode in sorted_missing:
                        if webkode in results.get('suggestions', {}):
                            # Show missing code with suggestions
                            st.write(f"🔍 **{webkode}** - Intet direkte match fundet")
                            suggestions = results['suggestions'][webkode]
                            
                            # Sort suggestions by filename
                            sorted_suggestions = sorted(suggestions, key=lambda x: x['filename'])
                            
                            st.write(f"💡 **Fundet {len(sorted_suggestions)} alternativer:**")
                            
                            # Detect duplicates within suggestions - collect all filenames first
                            suggestion_filenames = [suggestion['filename'] for suggestion in sorted_suggestions]
                            suggestion_filename_counts = {}
                            for filename in suggestion_filenames:
                                suggestion_filename_counts[filename] = suggestion_filename_counts.get(filename, 0) + 1
                            
                            # Display suggestions with selection option
                            suggestion_filename_occurrence = {}
                            for idx, suggestion in enumerate(sorted_suggestions):
                                filename = suggestion['filename']
                                modified_date = suggestion.get('modified', '')
                                
                                # Track occurrence of this filename
                                if filename not in suggestion_filename_occurrence:
                                    suggestion_filename_occurrence[filename] = 0
                                suggestion_filename_occurrence[filename] += 1
                                
                                suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                                
                                # Add duplicate indicator if needed
                                is_duplicate = suggestion_filename_counts[filename] > 1
                                occurrence_number = suggestion_filename_occurrence[filename]
                                
                                if is_duplicate:
                                    duplicate_suffix = f" (kopi #{occurrence_number})"
                                    display_name = f"🔄 {suggestion['filename']}{duplicate_suffix} (fra {suggestion['webkode']})"
                                    help_text = f"{suggestion['suggestion_reason']} - Duplikat #{occurrence_number} af {suggestion_filename_counts[filename]}"
                                else:
                                    display_name = f"📷 {suggestion['filename']} (fra {suggestion['webkode']})"
                                    help_text = suggestion['suggestion_reason']
                                
                                # Add date info if available
                                if modified_date:
                                    try:
                                        dt = datetime.fromisoformat(modified_date.replace('Z', '+00:00'))
                                        date_str = dt.strftime('%Y-%m-%d')
                                        display_name += f" (ændret: {date_str})"
                                    except:
                                        pass
                                
                                suggested = st.checkbox(
                                    display_name,
                                    key=suggestion_key,
                                    value=suggestion_key in st.session_state.selected_images,
                                    help=help_text
                                )
                                
                                if suggested:
                                    st.session_state.selected_images.add(suggestion_key)
                                elif suggestion_key in st.session_state.selected_images:
                                    st.session_state.selected_images.remove(suggestion_key)
                        else:
                            # No suggestions available
                            st.write(f"• **{webkode}** - Ingen alternativer fundet")
                
                # Add rename option for alternatives
                st.subheader("⚙️ Indstillinger")
                rename_alternatives = st.checkbox(
                    "🔄 Omdøb alternative filer til det ønskede variant-nummer",
                    help="Eksempel: AB23456-0023-00_01 → AB23456-0023-50_01 hvis du søgte efter AB23456-0023-50"
                )
                
                # Batch selection controls - placed after all images and suggestions
                st.subheader("🎛️ Vælg flere ad gangen")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    if st.button("✅ Vælg alle inkl. forslag"):
                        # Clear existing selections and select all (matches + suggestions)
                        st.session_state.selected_images.clear()
                        counter = 0
                        
                        # Select all found images (using sorted data)
                        sorted_found_items = sorted(results['found'].items())
                        for webkode, images in sorted_found_items:
                            sorted_images = sorted(images, key=lambda x: x['filename'])
                            for image in sorted_images:
                                counter += 1
                                image_key = f"img_{counter}_{webkode}_{image['filename']}"
                                st.session_state.selected_images.add(image_key)
                        
                        # Select all suggestions (using sorted data)
                        if 'suggestions' in results:
                            sorted_missing = sorted(results['missing'])
                            for webkode in sorted_missing:
                                if webkode in results['suggestions']:
                                    sorted_suggestions = sorted(results['suggestions'][webkode], key=lambda x: x['filename'])
                                    for idx, suggestion in enumerate(sorted_suggestions):
                                        suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                                        st.session_state.selected_images.add(suggestion_key)
                        
                        st.rerun()
                
                with col2:
                    if st.button("🎯 Vælg kun hele matches"):
                        # Clear existing selections and select only exact matches (using sorted data)
                        st.session_state.selected_images.clear()
                        counter = 0
                        
                        # Select only found images (no suggestions)
                        sorted_found_items = sorted(results['found'].items())
                        for webkode, images in sorted_found_items:
                            sorted_images = sorted(images, key=lambda x: x['filename'])
                            for image in sorted_images:
                                counter += 1
                                image_key = f"img_{counter}_{webkode}_{image['filename']}"
                                st.session_state.selected_images.add(image_key)
                        
                        st.rerun()
                
                with col3:
                    if st.button("🔄 Fravælg dubletter"):
                        # Remove duplicates from selection (keep only copy #1 of each duplicate)
                        keys_to_remove = set()
                        
                        # Check found images for duplicates (using sorted data)
                        sorted_found_items = sorted(results['found'].items())
                        counter = 0
                        for webkode, images in sorted_found_items:
                            sorted_images = sorted(images, key=lambda x: x['filename'])
                            filename_counts = {}
                            for image in sorted_images:
                                filename = image['filename']
                                filename_counts[filename] = filename_counts.get(filename, 0) + 1
                            
                            # Find keys for duplicates (copy #2, #3, etc.)
                            filename_occurrence = {}
                            for image in sorted_images:
                                counter += 1
                                filename = image['filename']
                                
                                if filename not in filename_occurrence:
                                    filename_occurrence[filename] = 0
                                filename_occurrence[filename] += 1
                                
                                # If this is a duplicate (copy #2 or higher), mark for removal
                                if filename_counts[filename] > 1 and filename_occurrence[filename] > 1:
                                    image_key = f"img_{counter}_{webkode}_{image['filename']}"
                                    keys_to_remove.add(image_key)
                        
                        # Check suggestions for duplicates (using sorted data)
                        if 'suggestions' in results:
                            sorted_missing = sorted(results['missing'])
                            for webkode in sorted_missing:
                                if webkode in results['suggestions']:
                                    sorted_suggestions = sorted(results['suggestions'][webkode], key=lambda x: x['filename'])
                                    suggestion_filename_counts = {}
                                    for suggestion in sorted_suggestions:
                                        filename = suggestion['filename']
                                        suggestion_filename_counts[filename] = suggestion_filename_counts.get(filename, 0) + 1
                                    
                                    # Find keys for suggestion duplicates
                                    suggestion_filename_occurrence = {}
                                    for idx, suggestion in enumerate(sorted_suggestions):
                                        filename = suggestion['filename']
                                        
                                        if filename not in suggestion_filename_occurrence:
                                            suggestion_filename_occurrence[filename] = 0
                                        suggestion_filename_occurrence[filename] += 1
                                        
                                        # If this is a duplicate (copy #2 or higher), mark for removal
                                        if suggestion_filename_counts[filename] > 1 and suggestion_filename_occurrence[filename] > 1:
                                            suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                                            keys_to_remove.add(suggestion_key)
                        
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
                    
                    if st.button("📦 Pak og download ZIP fil", type="primary"):
                        selected_images = []
                        counter = 0
                        
                        # Rebuild the mapping to find selected images from found results
                        duplicate_counter = {}
                        sorted_found_items = sorted(results['found'].items())
                        for webkode, images in sorted_found_items:
                            sorted_images = sorted(images, key=lambda x: x['filename'])
                            for image in sorted_images:
                                counter += 1
                                image_key = f"img_{counter}_{webkode}_{image['filename']}"
                                if image_key in st.session_state.selected_images:
                                    # Handle duplicate filenames
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
                        
                        # Also include selected suggestions (with optional renaming)
                        if 'suggestions' in results:
                            sorted_missing = sorted(results['missing'])
                            for webkode in sorted_missing:
                                if webkode in results['suggestions']:
                                    sorted_suggestions = sorted(results['suggestions'][webkode], key=lambda x: x['filename'])
                                    for idx, suggestion in enumerate(sorted_suggestions):
                                        suggestion_key = f"suggestion_{webkode}_{idx}_{suggestion['filename']}"
                                        if suggestion_key in st.session_state.selected_images:
                                            # Determine filename
                                            if rename_alternatives:
                                                # Extract the original variant from the searched webkode
                                                if '-' in webkode:
                                                    parts = webkode.split('-')
                                                    if len(parts) >= 3:
                                                        desired_variant = parts[-1]  # e.g., "50"
                                                        
                                                        # Replace the variant in the filename
                                                        original_filename = suggestion['filename']
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
                                                        new_filename = f"{webkode}_{suggestion['filename']}_suggested"
                                                else:
                                                    new_filename = f"{webkode}_{suggestion['filename']}_suggested"
                                            else:
                                                new_filename = f"{webkode}_{suggestion['filename']}_suggested"
                                            
                                            # Handle duplicates for suggestions too
                                            if new_filename in duplicate_counter:
                                                duplicate_counter[new_filename] += 1
                                                final_filename = f"{new_filename}_kopi{duplicate_counter[new_filename]}"
                                            else:
                                                duplicate_counter[new_filename] = 0
                                                final_filename = new_filename
                                            
                                            selected_images.append({
                                                'url': suggestion['url'],
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