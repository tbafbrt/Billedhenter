import streamlit as st
import os
import time
from auth import AuthManager
from common_functions import (
    ICRTImageDownloader, 
    api_credentials_screen, 
    parse_excel_file, 
    parse_text_input, 
    create_download_zip
)

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer - Billedhenter",
    page_icon="📸",
    layout="wide"
)

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'logged_in': False,
        'jwt_token': None,
        'api_authenticated': False,
        'search_results': {},
        'selected_images': set(),
        'image_keys_registry': {},
        'current_page': 'billedhenter',
        'debug_message': '',
        'last_action': ''
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# No callback functions needed - we'll use button click detection instead

def create_suggested_filename(original_filename, searched_webkode, rename_alternatives, add_suggested_suffix):
    """Create filename for suggested images with improved logic"""
    if not rename_alternatives and not add_suggested_suffix:
        return original_filename
    
    new_filename = original_filename
    
    if rename_alternatives:
        # Extract the desired variant from the searched webkode
        if '-' in searched_webkode:
            searched_parts = searched_webkode.split('-')
            if len(searched_parts) >= 3:
                desired_variant = searched_parts[-1]  # e.g., "53"
                
                # Get file extension first
                if '.' in original_filename:
                    filename_without_ext, file_extension = original_filename.rsplit('.', 1)
                else:
                    filename_without_ext = original_filename
                    file_extension = ""
                
                # Handle different filename patterns
                if '_' in filename_without_ext:
                    # Split by underscore: "IC24010-0006-00_10" -> ["IC24010-0006-00", "10"]
                    parts_split = filename_without_ext.split('_')
                    base_part = parts_split[0]  # "IC24010-0006-00"
                    suffix_parts = parts_split[1:]  # ["10"] or ["more", "parts"]
                    
                    # Replace variant in the base webkode
                    if '-' in base_part and len(base_part.split('-')) >= 3:
                        base_components = base_part.split('-')
                        base_components[-1] = desired_variant  # Replace "00" with "53"
                        new_base = '-'.join(base_components)  # "IC24010-0006-53"
                        
                        # Reconstruct filename with suffix parts
                        new_filename_base = new_base + '_' + '_'.join(suffix_parts)
                    else:
                        # Base doesn't look like webkode, replace entirely
                        new_filename_base = searched_webkode + '_' + '_'.join(suffix_parts)
                else:
                    # No underscore - filename is just the webkode
                    # Direct replacement of variant: "IC24010-0006-00" -> "IC24010-0006-53"
                    if '-' in filename_without_ext and len(filename_without_ext.split('-')) >= 3:
                        name_parts = filename_without_ext.split('-')
                        name_parts[-1] = desired_variant  # Replace last part with desired variant
                        new_filename_base = '-'.join(name_parts)
                    else:
                        # Fallback: filename doesn't match expected webkode pattern
                        new_filename_base = searched_webkode
                
                # Reconstruct with extension
                if file_extension:
                    new_filename = f"{new_filename_base}.{file_extension}"
                else:
                    new_filename = new_filename_base
            else:
                # Searched webkode doesn't have expected format
                new_filename = original_filename
        else:
            # No dashes in searched webkode
            new_filename = original_filename
    
    # Add suggested suffix if requested
    if add_suggested_suffix:
        if '.' in new_filename:
            name_part, ext_part = new_filename.rsplit('.', 1)
            new_filename = f"{name_part}_suggested.{ext_part}"
        else:
            new_filename = f"{new_filename}_suggested"
    
    return new_filename

def add_prefix_to_filename(original_filename, searched_webkode):
    """Add prefix to filename if it was found without prefix"""
    # Extract prefix from searched webkode (first 2 characters if they are letters)
    if len(searched_webkode) > 2 and searched_webkode[:2].isalpha():
        prefix = searched_webkode[:2].upper()
        
        # Get file extension first
        if '.' in original_filename:
            filename_without_ext, file_extension = original_filename.rsplit('.', 1)
        else:
            filename_without_ext = original_filename
            file_extension = ""
        
        # Check if filename already starts with the prefix (case insensitive)
        if not filename_without_ext.upper().startswith(prefix.upper()):
            # Add prefix to the filename
            new_filename_base = f"{prefix}{filename_without_ext}"
        else:
            # Already has prefix, return as is
            new_filename_base = filename_without_ext
        
        # Reconstruct with extension
        if file_extension:
            return f"{new_filename_base}.{file_extension}"
        else:
            return new_filename_base
    
    # If no valid prefix found, return original filename
    return original_filename

def show():
    """Display the billedhenter page"""
    st.title("T&A Billedhenter 🚚")
    st.write("""Her kan du hente billeder fra ICRT databasen ved at indsætte webkoder eller uploade et prisark.  
        Du kan også vælge at omdøbe alternative billeder inden download, så du slipper for at gøre det manuelt bagefter.
    """)
    
    # DEBUG: Show debug messages at the top
    if st.session_state.debug_message:
        st.info(f"🐛 {st.session_state.debug_message}")
        st.caption(f"Last action: {st.session_state.last_action}")
        st.caption(f"Current selected count: {len(st.session_state.selected_images)}")
        st.caption(f"Registry keys count: {len(st.session_state.image_keys_registry)}")
    
    # Initialize downloader
    downloader = ICRTImageDownloader()
    downloader.jwt_token = st.session_state.jwt_token
    
    # Check API authentication
    if not st.session_state.api_authenticated:
        api_credentials_screen()
        return
    
    # Show API status in sidebar
    with st.sidebar:
        st.markdown("---")
        st.subheader("🔗 API Status")
        st.success("✅ ICRT API Forbundet")
        
        if st.button("🔄 Genindlæs API", key="refresh_api"):
            st.session_state.api_authenticated = False
            st.session_state.jwt_token = None
            st.rerun()
    
    # File upload section
    st.header("Input webkoder 📋")
    
    st.subheader("Her har du to muligheder for at tilføje webkoderne til dine billeder:")
    st.text("✏️ I første fane er der en tekstboks du direkte kan copy-paste webkoderne du skal bruge billeder til ind\n🗂️ I den anden fane kan du uploade et prisark eller webskema med prisark")

    # Create tabs for different input methods
    tab1, tab2 = st.tabs(["✏️ Indsæt tekst","🗂️ Upload Excel fil"])
    
    webkodes = None
    project_code = ""
    
    with tab1:
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
                # Extract project code from first webkode
                if webkodes:
                    project_code = downloader.extract_project_code(webkodes[0])
        st.write("Tryk her :dart: når du har indsat eller rettet i webkoderne i textboxen")
    
    with tab2:
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
    
    # Continue with the rest of the processing if webkodes were found
    if webkodes:
        # Project code input
        st.header("Tjek projekt-koden 🏷️ ")
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
                # Clear selections on new search
                st.session_state.selected_images = set()
        
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
                beskrivelse_til_valg = '''Herunder kan du vælge de billeder du vil hente ned.  
                               Du kan vælge både billeder der matcher direkte og forslag til alternativer for manglende billeder.  
                               I bunden finder du knapper til at vælge alle billeder eller alle billeder der er direkte matches.
                               '''
                st.markdown(beskrivelse_til_valg)

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
                
                # Store registry in session state - THIS IS CRITICAL
                st.session_state.image_keys_registry = keys_registry
                
                # DEBUG: Show registry info
                st.caption(f"🐛 DEBUG: Registry har {len(keys_registry)} keys")
                
                # Settings section - MOVED HERE BEFORE DISPLAY
                st.subheader("⚙️ Indstillinger")
                
                # Always rename alternatives (removed checkbox)
                rename_alternatives = True
                
                col_settings1, col_settings2 = st.columns(2)
                
                with col_settings1:
                    add_suggested_suffix = st.checkbox(
                        "🏷️ Tilføj '_suggested' til alternative filer",
                        help="Eksempel: IC24010-0006-53_10.jpg → IC24010-0006-53_10_suggested.jpg"
                    )
                
                with col_settings2:
                    add_prefix_to_no_prefix = st.checkbox(
                        "🔤 Tilføj præfiks til filer fundet uden præfiks",
                        help="Eksempel: 21776-0375-00_001.jpg → IC21776-0375-00_001.jpg"
                    )
                
                st.markdown("---")
                
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
                            display_name = f"📄 {image['filename']}{duplicate_suffix}"
                        else:
                            display_name = f"📷 {image['filename']}"
                        
                        # Add indicator if found without prefix
                        if image.get('match_type') == 'without_prefix':
                            display_name += " 🔍"
                            
                            # Show preview if prefix will be added
                            if add_prefix_to_no_prefix:
                                preview_name = add_prefix_to_filename(image['filename'], webkode)
                                display_name += f" → {preview_name}"
                                help_text = f"Fundet uden præfiks - vil blive omdøbt til {preview_name}"
                            else:
                                help_text = f"Fundet uden præfiks - {image['filename']} matcher {webkode} uden de første to bogstaver"
                        else:
                            help_text = "Duplikat billede fundet" if is_duplicate else None
                        
                        # Display checkbox
                        selected = st.checkbox(
                            display_name,
                            key=key,
                            value=key in st.session_state.selected_images,
                            help=help_text
                        )
                        
                        # Update selection state
                        if selected:
                            st.session_state.selected_images.add(key)
                        elif key in st.session_state.selected_images:
                            st.session_state.selected_images.remove(key)
                

                # Display missing codes with suggestions
                if results['missing']:
                    st.subheader("Foreslåede alternativer for manglende billeder")
                    
                    for webkode in sorted_missing:
                        if webkode in results.get('suggestions', {}):
                            # Show missing code with suggestions
                            st.write(f"🔍 **{webkode}** - Intet direkte match fundet")
                            suggestions = results['suggestions'][webkode]
                            st.write(f"➡️ **Fundet {len(suggestions)} alternativer:**")
                            
                            # Find keys for this webkode's suggestions from registry
                            suggestion_keys = [key for key, data in keys_registry.items() 
                                             if data['type'] == 'suggestion' and data['webkode'] == webkode]
                            
                            for key in suggestion_keys:
                                data = keys_registry[key]
                                suggestion = data['image']
                                is_duplicate = data['is_duplicate']
                                duplicate_number = data['duplicate_number']
                                
                                # Show what the file will be renamed to
                                preview_name = create_suggested_filename(
                                    suggestion['filename'], 
                                    webkode, 
                                    rename_alternatives, 
                                    add_suggested_suffix
                                )
                                
                                # Add prefix preview if needed and it's a suggestion found without prefix
                                if add_prefix_to_no_prefix and suggestion.get('match_type') == 'without_prefix':
                                    preview_name = add_prefix_to_filename(preview_name, webkode)
                                
                                # Get the original filename to show where it's from
                                original_filename = suggestion['filename']
                                
                                # Create display name with preview - ALWAYS show the renamed version
                                if is_duplicate:
                                    duplicate_suffix = f" (kopi #{duplicate_number})"
                                    display_name = f"🔄 {preview_name}{duplicate_suffix}"
                                else:
                                    display_name = f"🔄 {preview_name}"
                                
                                # Show which original file it's from
                                display_name += f" (fra {original_filename})"
                                
                                # Build help text
                                help_text = suggestion.get('suggestion_reason', 'Alternativ fundet')
                                if add_suggested_suffix or (add_prefix_to_no_prefix and suggestion.get('match_type') == 'without_prefix'):
                                    help_text += f" - Vil blive omdøbt til {preview_name}"
                                
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
                            
                # Batch selection buttons - Using simple button detection
                st.subheader("🎛️ Batch-valg")
                col1, col2, col3, col4 = st.columns(4)
                           
                with col1:
                    if st.button("✅ Vælg alle inkl. forslag", key="btn_select_all", use_container_width=True):
                        st.session_state.selected_images = set(keys_registry.keys())
                        st.session_state.debug_message = f"✅ DEBUG: Valgt {len(st.session_state.selected_images)} billeder (Vælg alle)"
                        st.session_state.last_action = f"select_all - {len(st.session_state.selected_images)} images"
                        st.rerun()
                
                with col2:
                    if st.button("🎯 Vælg kun hele matches", key="btn_select_exact", use_container_width=True):
                        exact_matches = {
                            key for key, data in keys_registry.items() 
                            if data['type'] == 'found'
                        }
                        st.session_state.selected_images = exact_matches
                        st.session_state.debug_message = f"🎯 DEBUG: Valgt {len(exact_matches)} hele matches"
                        st.session_state.last_action = f"select_exact - {len(exact_matches)} images"
                        st.rerun()
                
                with col3:
                    if st.button("📄 Fravælg dubletter", key="btn_deselect_dupes", use_container_width=True):
                        keys_to_keep = {
                            key for key, data in keys_registry.items()
                            if not data['is_duplicate'] or data['duplicate_number'] == 1
                        }
                        before_count = len(st.session_state.selected_images)
                        st.session_state.selected_images = st.session_state.selected_images & keys_to_keep
                        after_count = len(st.session_state.selected_images)
                        removed = before_count - after_count
                        st.session_state.debug_message = f"📄 DEBUG: Fjernet {removed} dubletter (før: {before_count}, efter: {after_count})"
                        st.session_state.last_action = f"deselect_dupes - removed {removed}"
                        st.rerun()
                
                with col4:
                    if st.button("❌ Fravælg alle", key="btn_deselect_all", use_container_width=True):
                        st.session_state.selected_images = set()
                        st.session_state.debug_message = f"❌ DEBUG: Fravalgt alle billeder"
                        st.session_state.last_action = "deselect_all"
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
                    
                    if selected_count <= MAX_IMAGES_PER_ZIP and st.button("📦 Pak ZIP fil", type="primary"):
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
                                    
                                    # Add prefix if requested and image was found without prefix
                                    if add_prefix_to_no_prefix and image.get('match_type') == 'without_prefix':
                                        original_filename = add_prefix_to_filename(original_filename, webkode)
                                    
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
                                    # Handle suggestions with improved renaming
                                    new_filename = create_suggested_filename(
                                        image['filename'], 
                                        webkode, 
                                        rename_alternatives, 
                                        add_suggested_suffix
                                    )
                                    
                                    # Add prefix if requested and this suggestion was found without prefix
                                    if add_prefix_to_no_prefix and image.get('match_type') == 'without_prefix':
                                        new_filename = add_prefix_to_filename(new_filename, webkode)
                                    
                                    # Handle duplicates for suggestions too
                                    if new_filename in duplicate_counter:
                                        duplicate_counter[new_filename] += 1
                                        if '.' in new_filename:
                                            name_part, ext_part = new_filename.rsplit('.', 1)
                                            final_filename = f"{name_part}_kopi{duplicate_counter[new_filename]}.{ext_part}"
                                        else:
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
                                label="💾 Download ZIP fil",
                                data=zip_data,
                                file_name=f"icrt_images_{project_code_input}_{int(time.time())}.zip",
                                mime="application/zip",
                                use_container_width=True
                            )
                            st.success("✅ ZIP fil er klar til download!")

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()