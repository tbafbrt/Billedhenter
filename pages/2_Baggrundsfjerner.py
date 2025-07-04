import streamlit as st
import os
from auth import AuthManager
from rembg import remove, new_session
from PIL import Image
import numpy as np
from io import BytesIO
import base64
import traceback
import time
import zipfile

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="Baggrundsfjerner",
    page_icon="🖼️",
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
        'current_page': 'background_remover',
        'processed_images': [],
        'processing_complete': False
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# Constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_IMAGE_SIZE = None  # No limit - use original resolution

def convert_image(img, bg_color=(255, 255, 255), format="JPEG", quality=85):
    """Convert PIL image to bytes for download"""
    if img.mode == 'RGBA':
        if bg_color is not None:
            # Create colored background
            background = Image.new('RGB', img.size, bg_color)
            # Composite image onto background
            background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
            img = background
        # If bg_color is None, keep transparency (PNG only)
    
    buf = BytesIO()
    if format == "JPEG":
        # Ensure RGB mode for JPEG
        if img.mode != 'RGB':
            if img.mode == 'RGBA':
                # Create white background if still RGBA
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background
            else:
                img = img.convert('RGB')
        img.save(buf, format=format, quality=quality)
    else:  # PNG
        img.save(buf, format=format)
    
    byte_im = buf.getvalue()
    return byte_im

def resize_image(image, max_size):
    """Resize image while maintaining aspect ratio"""
    width, height = image.size
    if width <= max_size and height <= max_size:
        return image
    
    if width > height:
        new_width = max_size
        new_height = int(height * (max_size / width))
    else:
        new_height = max_size
        new_width = int(width * (max_size / height))
    
    return image.resize((new_width, new_height), Image.LANCZOS)

@st.cache_data
def process_single_image(image_bytes, filename, model_name="isnet-general-use"):
    """Process a single image with caching"""
    try:
        image = Image.open(BytesIO(image_bytes))
        # Create session with selected model and process the image
        session = new_session(model_name)
        fixed = remove(image, session=session)
        return {
            'filename': filename,
            'original': image,
            'processed': fixed,
            'success': True,
            'error': None
        }
    except Exception as e:
        return {
            'filename': filename,
            'original': None,
            'processed': None,
            'success': False,
            'error': str(e)
        }

def create_batch_zip(processed_images, bg_color=(255, 255, 255), format="JPEG", quality=85):
    """Create ZIP file with all processed images"""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for img_data in processed_images:
            if img_data['success']:
                # Create filename without extension, add _processed with appropriate extension
                base_name = os.path.splitext(img_data['filename'])[0]
                file_extension = ".jpg" if format == "JPEG" else ".png"
                zip_filename = f"{base_name}_processed{file_extension}"
                
                # Convert image to bytes and add to ZIP
                img_bytes = convert_image(img_data['processed'], bg_color, format, quality)
                zip_file.writestr(zip_filename, img_bytes)
    
    return zip_buffer.getvalue()

def process_batch_images(uploaded_files, model_name="isnet-general-use"):
    """Process multiple images with progress tracking"""
    processed_images = []
    
    # Overall progress
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_files = len(uploaded_files)
    
    for i, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"Processing {uploaded_file.name}... ({i+1}/{total_files})")
        
        # Check file size
        if uploaded_file.size > MAX_FILE_SIZE:
            processed_images.append({
                'filename': uploaded_file.name,
                'original': None,
                'processed': None,
                'success': False,
                'error': f"File too large ({uploaded_file.size/1024/1024:.1f}MB > {MAX_FILE_SIZE/1024/1024:.1f}MB)"
            })
        else:
            # Process the image with selected model
            result = process_single_image(uploaded_file.getvalue(), uploaded_file.name, model_name)
            processed_images.append(result)
        
        # Update progress
        progress_bar.progress((i + 1) / total_files)
    
    status_text.text(f"Processing complete! Processed {total_files} images.")
    time.sleep(1)  # Brief pause to show completion
    progress_bar.empty()
    status_text.empty()
    
    return processed_images

def show():
    """Display the background remover page"""
    st.title("Baggrundsfjerner 🪄")
    
    st.markdown("""
    Fjern baggrunden fra dine billeder automatisk! Upload et eller flere billeder og få dem processet med KI.
    """)
    
    # File upload section
    st.header("Upload billeder 🛸")
    
    uploaded_files = st.file_uploader(
        "Vælg billeder der skal behandles",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        help="Du kan vælge flere billeder ad gangen for batch processing"
    )
    
    # Information about limitations
    with st.expander("ℹ️ Begrænsninger og retningslinjer"):
        st.markdown("""
        - **Maksimal filstørrelse:** 10MB per billede
        - **Understøttede formater:** PNG, JPG, JPEG
        - **Original kvalitet:** Billeder behandles i fuld original opløsning
        - **Behandlingstid:** Afhænger af billedstørrelse, antal billeder og valgt model
        - **Hukommelse:** Meget store billeder (>4000x4000) kan tage længere tid at behandle
        - **Kvalitet:** Bedste resultater opnås med billeder hvor hovedmotivet er tydeligt adskilt fra baggrunden
        """)
    
    # Settings section
    st.header("Indstillinger ⚙️")
    
    # Model options
    model_options = {
        "Standard (u2net)": "u2net",
        "Personer (u2net_human_seg)": "u2net_human_seg", 
        "Tøj (u2net_cloth_seg)": "u2net_cloth_seg",
        "Høj kvalitet (isnet-general-use)": "isnet-general-use",
        "Hurtig (silueta)": "silueta"
    }
    
    # Background color options
    background_options = {
        "Hvid": (255, 255, 255),
        "Sort": (0, 0, 0),
        "Gennemsigtig (kun PNG)": None,
        "Tilpasset farve": "custom"
    }
    
    # Output format options
    format_options = {
        "JPG (mindre filer)": "JPEG",
        "PNG (gennemsigtighed)": "PNG"
    }
    
    # Quality options
    quality_options = {
        "Høj kvalitet (95%)": 95,
        "Standard (85%)": 85,
        "Komprimeret (70%)": 70
    }
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Model selection
        selected_model_name = st.selectbox(
            "🤖 KI Model",
            options=list(model_options.keys()),
            index=3,  # This selects "Høj kvalitet (isnet-general-use)" as default
            help="Vælg KI model baseret på dit billedtype"
        )
        selected_model = model_options[selected_model_name]
        
        # Background color
        background_choice = st.selectbox(
            "🎨 Baggrund",
            options=list(background_options.keys()),
            help="Vælg baggrundsfarve (gennemsigtig kun for PNG)"
        )
        
        # Custom color picker if selected
        if background_choice == "Tilpasset farve":
            custom_color = st.color_picker("Vælg baggrundsfave", "#FFFFFF")
            # Convert hex to RGB
            bg_color = tuple(int(custom_color[i:i+2], 16) for i in (1, 3, 5))
        else:
            bg_color = background_options[background_choice]
    
    with col2:
        # Output format
        output_format_name = st.selectbox(
            "📁 Format",
            options=list(format_options.keys()),
            help="JPG er mindre filer, PNG bevarer gennemsigtighed"
        )
        output_format = format_options[output_format_name]
        
        # Quality (only for JPEG)
        if output_format == "JPEG":
            quality_name = st.selectbox(
                "📊 Kvalitet",
                options=list(quality_options.keys()),
                help="Højere kvalitet giver større filer"
            )
            quality = quality_options[quality_name]
        else:
            quality = 95  # Default for PNG (not used)
    
    # Show model info
    with st.expander("🔍 Model information"):
        model_info = {
            "u2net": "Generel KI model - god til de fleste billedtyper",
            "u2net_human_seg": "Optimeret til personer og menneskelige motiver",
            "u2net_cloth_seg": "Specialiseret til tøj og tekstiler",
            "isnet-general-use": "Høj kvalitet model - mere præcis men langsommere",
            "silueta": "Hurtig model - mindre præcis men hurtigere"
        }
        st.info(f"**{selected_model_name}:** {model_info[selected_model]}")
    
    # Warning for transparency
    if bg_color is None and output_format == "JPEG":
        st.warning("⚠️ JPG format understøtter ikke gennemsigtighed. Skift til PNG eller vælg en baggrundsfave.")
    
    if uploaded_files:
        st.header("🔄 Behandling")
        
        # Show upload summary
        total_size = sum(f.size for f in uploaded_files)
        valid_files = [f for f in uploaded_files if f.size <= MAX_FILE_SIZE]
        oversized_files = [f for f in uploaded_files if f.size > MAX_FILE_SIZE]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📁 Antal filer", len(uploaded_files))
        with col2:
            st.metric("✅ Gyldige filer", len(valid_files))
        with col3:
            st.metric("📊 Total størrelse", f"{total_size/1024/1024:.1f}MB")
        
        # Show warnings for oversized files
        if oversized_files:
            st.warning(f"⚠️ {len(oversized_files)} filer er for store og vil blive sprunget over:")
            for f in oversized_files:
                st.write(f"- {f.name} ({f.size/1024/1024:.1f}MB)")
        
        # Process button
        if st.button("🚀 Start behandling", type="primary", disabled=len(valid_files) == 0):
            # Validate settings
            if bg_color is None and output_format == "JPEG":
                st.error("❌ JPG format kan ikke have gennemsigtig baggrund. Vælg PNG format eller en baggrundsfave.")
            else:
                with st.spinner("Behandler billeder..."):
                    processed_images = process_batch_images(uploaded_files, selected_model)
                    st.session_state.processed_images = processed_images
                    st.session_state.processing_complete = True
                    # Store settings in session state
                    st.session_state.bg_color = bg_color
                    st.session_state.output_format = output_format
                    st.session_state.quality = quality
    
    # Display results
    if st.session_state.processing_complete and st.session_state.processed_images:
        st.header("✅ Resultater")
        
        processed_images = st.session_state.processed_images
        successful_images = [img for img in processed_images if img['success']]
        failed_images = [img for img in processed_images if not img['success']]
        
        # Summary
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🎯 Succesfulde", len(successful_images))
        with col2:
            st.metric("❌ Fejlede", len(failed_images))
        with col3:
            if successful_images:
                st.metric("📦 Klar til download", len(successful_images))
        
        # Batch download section
        if successful_images:
            st.subheader("📦 Batch Download")
            
            # Get settings from session state
            bg_color = st.session_state.get('bg_color', (255, 255, 255))
            output_format = st.session_state.get('output_format', 'JPEG')
            quality = st.session_state.get('quality', 85)
            
            zip_data = create_batch_zip(successful_images, bg_color, output_format, quality)
            file_extension = "jpg" if output_format == "JPEG" else "png"
            st.download_button(
                label="⬇️ Download alle behandlede billeder (ZIP)",
                data=zip_data,
                file_name=f"processed_images_{int(time.time())}.zip",
                mime="application/zip",
                type="primary"
            )
            
            st.markdown("---")
        
        # Individual results
        st.subheader("🖼️ Individuelle resultater")
        
        # Show successful images
        if successful_images:
            for img_data in successful_images:
                with st.expander(f"✅ {img_data['filename']}", expanded=False):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**Original billede:**")
                        st.image(img_data['original'], use_container_width=True)
                    
                    with col2:
                        st.write("**Behandlet billede:**")
                        st.image(img_data['processed'], use_container_width=True)
                    
                    # Individual download
                    bg_color = st.session_state.get('bg_color', (255, 255, 255))
                    output_format = st.session_state.get('output_format', 'JPEG')
                    quality = st.session_state.get('quality', 85)
                    
                    base_name = os.path.splitext(img_data['filename'])[0]
                    file_extension = ".jpg" if output_format == "JPEG" else ".png"
                    download_filename = f"{base_name}_processed{file_extension}"
                    mime_type = "image/jpeg" if output_format == "JPEG" else "image/png"
                    
                    st.download_button(
                        label=f"⬇️ Download {download_filename}",
                        data=convert_image(img_data['processed'], bg_color, output_format, quality),
                        file_name=download_filename,
                        mime=mime_type,
                        key=f"download_{img_data['filename']}"
                    )
        
        # Show failed images
        if failed_images:
            st.subheader("❌ Billeder der ikke kunne behandles")
            for img_data in failed_images:
                st.error(f"**{img_data['filename']}**: {img_data['error']}")
        
        # Clear results button
        if st.button("🔄 Nulstil og start forfra"):
            st.session_state.processed_images = []
            st.session_state.processing_complete = False
            st.rerun()
    
    # Help section
    st.header("Hjælp og tips ❓")
    
    with st.expander("**Sådan får du de bedste resultater 📖**"):
        st.markdown("""
        **Billedkvalitet:**
        - Brug billeder med høj opløsning
        - Sørg for god kontrast mellem motiv og baggrund
        - Undgå meget støjede eller uskarpe billeder
        
        **Motiver der fungerer godt:**
        - Mennesker og dyr
        - Objekter med tydelige kanter
        - Produktbilleder
        - Logoer og grafik
        
        **Motiver der kan være udfordrende:**
        - Gennemsigtige objekter
        - Hår med mange fine detaljer
        - Motiver der blander sig med baggrunden
        """)
    
    with st.expander("**Tekniske specifikationer 🔧**"):
        st.markdown("""
        **KI Modeller:** 5 forskellige modeller optimeret til forskellige billedtyper  
        **Behandlingstid:** 1-15 sekunder per billede afhængigt af størrelse og model  
        **Maksimal opløsning:** Billeder behandles i original opløsning  
        **Output formater:** JPG (med baggrund) eller PNG (med gennemsigtighed)  
        **Kvalitetsindstillinger:** 70%, 85%, eller 95% JPEG kvalitet
        """)

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()