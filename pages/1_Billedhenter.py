import streamlit as st
import os
import time
from auth import AuthManager
from common_functions import (
    ICRTImageDownloader,
    api_credentials_screen,
    parse_excel_file,
    parse_text_input,
    create_download_zip,
)

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer - Billedhenter",
    page_icon="📸",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'logged_in': False,
        'jwt_token': None,
        'api_authenticated': False,
        'search_results': {},
        'image_keys_registry': {},
        'current_page': 'billedhenter',
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def clear_checkbox_states():
    """Clear all checkbox state keys from session_state.

    Called when a new search starts so old checkbox states don't leak in.
    """
    keys_to_clear = [
        k for k in list(st.session_state.keys())
        if k.startswith('img_') or k.startswith('suggestion_')
    ]
    for k in keys_to_clear:
        del st.session_state[k]


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------
def split_filename(filename: str):
    """Split filename into (base, extension). Extension is '' if none."""
    if '.' in filename:
        base, ext = filename.rsplit('.', 1)
        return base, ext
    return filename, ''


def rename_to_variant(original_filename: str, searched_webkode: str) -> str:
    """Replace the variant (last segment) in a filename to match the searched webkode.

    Example: rename_to_variant('IC24010-0006-00_10.jpg', 'IC24010-0006-53')
             -> 'IC24010-0006-53_10.jpg'
    """
    if '-' not in searched_webkode:
        return original_filename

    searched_parts = searched_webkode.split('-')
    if len(searched_parts) < 3:
        return original_filename

    desired_variant = searched_parts[-1]
    base, ext = split_filename(original_filename)

    # Split off any trailing "_xx" suffix(es)
    if '_' in base:
        parts = base.split('_')
        webkode_part = parts[0]
        suffix_parts = parts[1:]
    else:
        webkode_part = base
        suffix_parts = []

    # Replace the last segment of the webkode_part with desired_variant
    if '-' in webkode_part and len(webkode_part.split('-')) >= 3:
        components = webkode_part.split('-')
        components[-1] = desired_variant
        new_webkode = '-'.join(components)
    else:
        # Filename doesn't match an expected webkode pattern; leave alone
        return original_filename

    new_base = new_webkode + (('_' + '_'.join(suffix_parts)) if suffix_parts else '')
    return new_base + (('.' + ext) if ext else '')


def add_suggested_suffix(filename: str) -> str:
    """Append '_suggested' before the extension."""
    base, ext = split_filename(filename)
    return base + '_suggested' + (('.' + ext) if ext else '')


def add_prefix(filename: str, searched_webkode: str) -> str:
    """Add the 2-letter prefix from searched_webkode to the filename if missing."""
    if len(searched_webkode) <= 2 or not searched_webkode[:2].isalpha():
        return filename
    prefix = searched_webkode[:2].upper()
    base, ext = split_filename(filename)
    if base.upper().startswith(prefix):
        return filename
    return prefix + base + (('.' + ext) if ext else '')


def build_final_filename(
    original_filename: str,
    searched_webkode: str,
    match_type: str,
    is_suggestion: bool,
    rename_alternatives: bool,
    add_suggested: bool,
    add_prefix_to_no_prefix: bool,
) -> str:
    """Build the final filename for download based on all the user's settings.

    Order of operations:
    1. If suggestion + rename_alternatives: rewrite the variant number
    2. If suggestion + add_suggested: append '_suggested'
    3. If match_type == 'without_prefix' + add_prefix_to_no_prefix: prepend the prefix
    """
    name = original_filename

    if is_suggestion and rename_alternatives:
        name = rename_to_variant(name, searched_webkode)

    if is_suggestion and add_suggested:
        name = add_suggested_suffix(name)

    if match_type == 'without_prefix' and add_prefix_to_no_prefix:
        name = add_prefix(name, searched_webkode)

    return name


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------
def build_registry(results: dict) -> dict:
    """Build a registry of {checkbox_key: metadata} for all images + suggestions.

    Keys are deterministic across reruns as long as `results` is unchanged,
    because we sort everything and use a global counter through the sorted list.
    """
    registry = {}
    counter = 0

    # Found images
    for webkode, images in sorted(results.get('found', {}).items()):
        sorted_images = sorted(images, key=lambda x: x['filename'])

        # Count duplicates within this webkode
        filename_counts = {}
        for image in sorted_images:
            filename_counts[image['filename']] = filename_counts.get(image['filename'], 0) + 1

        filename_occurrence = {}
        for image in sorted_images:
            filename = image['filename']
            filename_occurrence[filename] = filename_occurrence.get(filename, 0) + 1

            counter += 1
            key = f"img_{counter}_{webkode}_{filename}"

            registry[key] = {
                'type': 'found',
                'webkode': webkode,
                'image': image,
                'is_duplicate': filename_counts[filename] > 1,
                'duplicate_number': filename_occurrence[filename] if filename_counts[filename] > 1 else None,
            }

    # Suggestions
    for webkode in sorted(results.get('missing', [])):
        suggestions = results.get('suggestions', {}).get(webkode, [])
        if not suggestions:
            continue

        sorted_suggestions = sorted(suggestions, key=lambda x: x['filename'])

        filename_counts = {}
        for s in sorted_suggestions:
            filename_counts[s['filename']] = filename_counts.get(s['filename'], 0) + 1

        filename_occurrence = {}
        for idx, suggestion in enumerate(sorted_suggestions):
            filename = suggestion['filename']
            filename_occurrence[filename] = filename_occurrence.get(filename, 0) + 1

            key = f"suggestion_{webkode}_{idx}_{filename}"

            registry[key] = {
                'type': 'suggestion',
                'webkode': webkode,
                'image': suggestion,
                'is_duplicate': filename_counts[filename] > 1,
                'duplicate_number': filename_occurrence[filename] if filename_counts[filename] > 1 else None,
            }

    return registry


def get_selected_keys(registry: dict) -> set:
    """Return set of registry keys currently checked (single source of truth)."""
    return {key for key in registry if st.session_state.get(key, False)}


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
def show():
    st.title("T&A Billedhenter 🚚")
    st.write(
        """Her kan du hente billeder fra ICRT databasen ved at indsætte webkoder eller uploade et prisark.  
        Du kan også vælge at omdøbe alternative billeder inden download, så du slipper for at gøre det manuelt bagefter.
        """
    )

    # Initialize downloader
    downloader = ICRTImageDownloader()
    downloader.jwt_token = st.session_state.jwt_token

    # Check API authentication
    if not st.session_state.api_authenticated:
        api_credentials_screen()
        return

    # API status in sidebar
    with st.sidebar:
        st.markdown("---")
        st.subheader("🔗 API Status")
        st.success("✅ ICRT API Forbundet")
        if st.button("🔄 Genindlæs API", key="refresh_api"):
            st.session_state.api_authenticated = False
            st.session_state.jwt_token = None
            st.rerun()

    # --- Input section -----------------------------------------------------
    st.header("Input webkoder 📋")
    st.subheader("Her har du to muligheder for at tilføje webkoderne til dine billeder:")
    st.text(
        "✏️ I første fane er der en tekstboks du direkte kan copy-paste webkoderne du skal bruge billeder til ind\n"
        "🗂️ I den anden fane kan du uploade et prisark eller webskema med prisark"
    )

    tab1, tab2 = st.tabs(["✏️ Indsæt tekst", "🗂️ Upload Excel fil"])

    webkodes = None
    project_code = ""

    with tab1:
        st.markdown("Indsæt webkoder direkte fra clipboard")
        text_input = st.text_area(
            "Indsæt webkoder her (adskilt af mellemrum, linjeskift eller kommaer):",
            placeholder="IC23022-0072-00 IC23022-0220-31 IC23022-0050-00\nIC23022-0072-10 IC23022-0054-00",
            height=150,
            help="Du kan indsætte webkoder adskilt af mellemrum, linjeskift eller kommaer",
        )
        if text_input:
            webkodes, error = parse_text_input(text_input)
            if error:
                st.error(error)
            else:
                st.success(f"✅ Fundet {len(webkodes)} webkoder i tekst input")
                if webkodes:
                    project_code = downloader.extract_project_code(webkodes[0])

    with tab2:
        st.markdown("Upload dit prisark eller webskema")
        uploaded_file = st.file_uploader(
            "Her kan du bruge både prisark og webskema, filen skal bare have en fane der hedder 'Priser' og en kolonneoverskrift i række 3 der hedder 'Webkode'",
            type=['xlsx', 'xls'],
        )
        if uploaded_file:
            webkodes, error = parse_excel_file(uploaded_file)
            if error:
                st.error(error)
            else:
                st.success(f"✅ Fundet {len(webkodes)} webkoder i Excel-fil")
                if webkodes:
                    project_code = downloader.extract_project_code(webkodes[0])

    if not webkodes:
        return

    # --- Project code & search --------------------------------------------
    st.header("Tjek projekt-koden 🏷️")
    project_code_input = st.text_input(
        "Projektkoden bliver hentet automatisk fra den første webkode, men kan tilpasses hvis ikke den bliver genkendt rigtigt.",
        value=project_code,
        help="Format: LLDDDDD (e.g., IC20006) or DDDDD",
    )

    if st.button("🔍 Find billedfiler", type="primary"):
        if not project_code_input:
            st.error("Projectkode ikke fundet, prøv igen")
            return

        # Clear old checkbox states before new search
        clear_checkbox_states()
        st.session_state.image_keys_registry = {}

        with st.spinner("Søger efter filer..."):
            results = downloader.search_images_for_codes(project_code_input, webkodes)
            st.session_state.search_results = results

    # --- Results -----------------------------------------------------------
    if not st.session_state.search_results:
        return

    results = st.session_state.search_results

    # Summary metrics
    st.header("📊 Filer fundet")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Fundet", len(results['found']))
    with col2:
        st.metric("Mangler", len(results['missing']))
    with col3:
        total_images = sum(len(images) for images in results['found'].values())
        st.metric("Fundet billeder i alt", total_images)

    if not (results['found'] or results['missing']):
        return

    # Build / refresh the registry
    registry = build_registry(results)
    st.session_state.image_keys_registry = registry

    # --- Batch selection buttons (BEFORE checkboxes render) ----------------
    st.header("✅ Vælg de billeder du vil hente ned")
    st.markdown(
        """Herunder kan du vælge de billeder du vil hente ned.  
        Du kan vælge både billeder der matcher direkte og forslag til alternativer for manglende billeder.  
        Brug knapperne herunder til at vælge eller fravælge flere ad gangen.
        """
    )

    st.subheader("🎛️ Batch-valg")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        btn_select_all = st.button(
            "✅ Vælg alle inkl. forslag", key="btn_select_all", use_container_width=True
        )
    with col2:
        btn_select_exact = st.button(
            "🎯 Vælg kun hele matches", key="btn_select_exact", use_container_width=True
        )
    with col3:
        btn_deselect_dupes = st.button(
            "🔄 Fravælg dubletter", key="btn_deselect_dupes", use_container_width=True
        )
    with col4:
        btn_deselect_all = st.button(
            "❌ Fravælg alle", key="btn_deselect_all", use_container_width=True
        )

    # Process button clicks by directly updating each checkbox's session_state key.
    # This is essential: the checkboxes use `key=` and read from st.session_state[key],
    # so we MUST update those keys (not a separate selected_images set) for the
    # change to be visible when checkboxes re-render.
    if btn_select_all:
        for key in registry:
            st.session_state[key] = True
        st.rerun()

    if btn_select_exact:
        for key, data in registry.items():
            st.session_state[key] = (data['type'] == 'found')
        st.rerun()

    if btn_deselect_dupes:
        for key, data in registry.items():
            if data['is_duplicate'] and data['duplicate_number'] and data['duplicate_number'] > 1:
                st.session_state[key] = False
        st.rerun()

    if btn_deselect_all:
        for key in registry:
            st.session_state[key] = False
        st.rerun()

    st.markdown("---")

    # --- Rename settings (rendered before image list so user sees previews) -
    st.subheader("⚙️ Indstillinger for omdøbning")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        rename_alternatives = st.checkbox(
            "🔁 Omdøb alternative filer til søgt variant",
            value=True,
            help="Eksempel: IC24010-0006-00_10.jpg → IC24010-0006-53_10.jpg hvis du søgte efter -53",
        )
    with col_b:
        add_suggested = st.checkbox(
            "🏷️ Tilføj '_suggested' til alternative filer",
            value=False,
            help="Eksempel: IC24010-0006-53_10.jpg → IC24010-0006-53_10_suggested.jpg",
        )
    with col_c:
        add_prefix_to_no_prefix = st.checkbox(
            "🔤 Tilføj præfiks til filer fundet uden præfiks",
            value=False,
            help="Eksempel: 21776-0375-00_001.jpg → IC21776-0375-00_001.jpg",
        )

    st.markdown("---")

    # --- Render direct matches ---------------------------------------------
    for webkode in sorted(results['found'].keys()):
        images_for_code = results['found'][webkode]
        st.subheader(f"📋 {webkode} ({len(images_for_code)} billeder)")

        webkode_keys = [
            key for key, data in registry.items()
            if data['type'] == 'found' and data['webkode'] == webkode
        ]

        for key in webkode_keys:
            data = registry[key]
            image = data['image']
            match_type = image.get('match_type', 'direct')

            # Build display name
            preview_name = build_final_filename(
                image['filename'],
                webkode,
                match_type,
                is_suggestion=False,
                rename_alternatives=rename_alternatives,
                add_suggested=add_suggested,
                add_prefix_to_no_prefix=add_prefix_to_no_prefix,
            )

            if data['is_duplicate']:
                dup_suffix = f" (kopi #{data['duplicate_number']})"
            else:
                dup_suffix = ""

            if preview_name != image['filename']:
                display_name = f"📷 {image['filename']}{dup_suffix} → {preview_name}"
                help_text = f"Vil blive omdøbt til: {preview_name}"
            else:
                display_name = f"📷 {image['filename']}{dup_suffix}"
                help_text = "Duplikat billede fundet" if data['is_duplicate'] else None

            if match_type == 'without_prefix':
                display_name += " 🔍"
                hint = "Fundet uden præfiks"
                help_text = (help_text + " · " + hint) if help_text else hint

            # Ensure key exists in session_state with default False
            if key not in st.session_state:
                st.session_state[key] = False

            # Render checkbox WITHOUT value= so the widget uses st.session_state[key] only.
            # This is the critical fix that makes the batch buttons work.
            st.checkbox(display_name, key=key, help=help_text)

    # --- Render suggestions ------------------------------------------------
    if results['missing']:
        st.subheader("💡 Foreslåede alternativer for manglende billeder")
        for webkode in sorted(results['missing']):
            if webkode not in results.get('suggestions', {}):
                st.write(f"• **{webkode}** - Ingen alternativer fundet")
                continue

            suggestions = results['suggestions'][webkode]
            st.write(f"🔍 **{webkode}** - Intet direkte match fundet")
            st.write(f"➡️ **Fundet {len(suggestions)} alternativer:**")

            suggestion_keys = [
                key for key, data in registry.items()
                if data['type'] == 'suggestion' and data['webkode'] == webkode
            ]

            for key in suggestion_keys:
                data = registry[key]
                suggestion = data['image']
                match_type = suggestion.get('match_type', 'direct')

                preview_name = build_final_filename(
                    suggestion['filename'],
                    webkode,
                    match_type,
                    is_suggestion=True,
                    rename_alternatives=rename_alternatives,
                    add_suggested=add_suggested,
                    add_prefix_to_no_prefix=add_prefix_to_no_prefix,
                )

                if data['is_duplicate']:
                    dup_suffix = f" (kopi #{data['duplicate_number']})"
                else:
                    dup_suffix = ""

                display_name = f"🔄 {preview_name}{dup_suffix} (fra {suggestion['filename']})"
                help_text = suggestion.get('suggestion_reason', 'Alternativ fundet')
                if preview_name != suggestion['filename']:
                    help_text += f" · Vil blive omdøbt til {preview_name}"

                if key not in st.session_state:
                    st.session_state[key] = False

                st.checkbox(display_name, key=key, help=help_text)

    # --- Download section --------------------------------------------------
    selected_keys = get_selected_keys(registry)
    selected_count = len(selected_keys)

    if selected_count == 0:
        return

    st.header(f"⬇️ Hent valgte billeder ({selected_count})")

    MAX_IMAGES_PER_ZIP = 300

    if selected_count > MAX_IMAGES_PER_ZIP:
        st.error("⚠️ **For mange billeder valgt!**")
        st.warning(
            f"Du har valgt **{selected_count} billeder**, men maksimum er "
            f"**{MAX_IMAGES_PER_ZIP} billeder** per download."
        )
        st.info("💡 **Løsninger:**")
        st.markdown(
            """
            - **Fravælg nogle billeder** og prøv igen
            - **Brug 'Fravælg dubletter'** for at reducere antallet
            - **Download i mindre portioner** - vælg færre billeder ad gangen
            """
        )
        excess = selected_count - MAX_IMAGES_PER_ZIP
        st.markdown(f"🎯 **Du skal fravælge {excess} billeder for at fortsætte**")
        return

    # Size estimate
    if selected_count <= 100:
        st.info(f"🟢 **ZIP størrelse**: lille (~{selected_count * 0.2:.1f}MB estimeret)")
    elif selected_count <= 200:
        st.info(f"🟡 **ZIP størrelse**: medium (~{selected_count * 0.2:.1f}MB estimeret)")
    else:
        st.info(f"🟠 **ZIP størrelse**: stor (~{selected_count * 0.2:.1f}MB estimeret)")

    if not st.button("📦 Pak ZIP fil", type="primary"):
        return

    # Build list of images to download
    selected_images = []
    used_filenames = {}  # tracks duplicate filenames for download

    for key in selected_keys:
        data = registry[key]
        image = data['image']
        webkode = data['webkode']
        match_type = image.get('match_type', 'direct')
        is_suggestion = (data['type'] == 'suggestion')

        final_filename = build_final_filename(
            image['filename'],
            webkode,
            match_type,
            is_suggestion=is_suggestion,
            rename_alternatives=rename_alternatives,
            add_suggested=add_suggested,
            add_prefix_to_no_prefix=add_prefix_to_no_prefix,
        )

        # De-duplicate filenames at the ZIP-level
        if final_filename in used_filenames:
            used_filenames[final_filename] += 1
            base, ext = split_filename(final_filename)
            final_filename = f"{base}_kopi{used_filenames[final_filename]}" + (
                f".{ext}" if ext else ""
            )
        else:
            used_filenames[final_filename] = 0

        selected_images.append({
            'url': image['url'],
            'filename': final_filename,
            'webkode': webkode,
        })

    with st.spinner("Pakker dine filer..."):
        zip_data = create_download_zip(selected_images)

    st.download_button(
        label="💾 Download ZIP fil",
        data=zip_data,
        file_name=f"icrt_images_{project_code_input}_{int(time.time())}.zip",
        mime="application/zip",
        use_container_width=True,
    )
    st.success("✅ ZIP fil er klar til download!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()
