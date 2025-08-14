import streamlit as st
import os
import time
from auth import AuthManager
from PIL import Image
import io
import zipfile
from pathlib import Path

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer - Billedfil-converter",
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
        'current_page': 'billedfil_converter',
        'conversion_results': [],
        'converted_files': []
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def convert_images(uploaded_files, output_format, quality, max_width, max_height):
    """Convert uploaded images and provide download"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    converted_files = []
    conversion_results = []
    
    for idx, uploaded_file in enumerate(uploaded_files):
        try:
            status_text.text(f"Konverterer {uploaded_file.name}...")
            progress_bar.progress((idx + 1) / len(uploaded_files))
            
            # Try to open the image with better error handling
            try:
                image = Image.open(uploaded_file)
                # Force load the image to catch any format issues early
                image.load()
            except Exception as img_error:
                # Special handling for AVIF files
                if uploaded_file.name.lower().endswith('.avif'):
                    raise Exception(f"AVIF format ikke understøttet på dette system. Prøv at installere pillow-avif-plugin eller konverter først til WebP.")
                else:
                    raise Exception(f"Kan ikke læse billedfil: {str(img_error)}")
            
            # Convert RGBA to RGB if saving as JPEG
            if output_format == "JPEG" and image.mode in ("RGBA", "LA", "P"):
                # Create white background
                background = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
                image = background
            
            # Resize if requested
            if max_width and max_height:
                image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            # Prepare output filename
            original_name = Path(uploaded_file.name).stem
            extension = "jpg" if output_format == "JPEG" else "png"
            output_filename = f"{original_name}.{extension}"
            
            # Convert and save to bytes
            img_bytes = io.BytesIO()
            save_kwargs = {"format": output_format}
            if output_format == "JPEG" and quality:
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            
            image.save(img_bytes, **save_kwargs)
            img_bytes.seek(0)
            
            converted_files.append((output_filename, img_bytes.getvalue()))
            
            # Track conversion info
            original_size = len(uploaded_file.getvalue())
            new_size = len(img_bytes.getvalue())
            conversion_results.append({
                "original": uploaded_file.name,
                "converted": output_filename,
                "original_size": original_size,
                "new_size": new_size,
                "size_change": ((new_size - original_size) / original_size) * 100,
                "original_format": uploaded_file.type,
                "new_format": output_format
            })
            
        except Exception as e:
            st.error(f"Fejl ved konvertering af {uploaded_file.name}: {str(e)}")
            conversion_results.append({
                "original": uploaded_file.name,
                "converted": "❌ Fejlede",
                "error": str(e)
            })
    
    progress_bar.progress(1.0)
    status_text.text("Konvertering færdig!")
    time.sleep(1)
    progress_bar.empty()
    status_text.empty()
    
    # Store results in session state
    st.session_state.conversion_results = conversion_results
    st.session_state.converted_files = converted_files
    
    return converted_files, conversion_results

def display_conversion_results(results):
    """Display conversion results in a table"""
    st.subheader("📊 Konverteringsresultater")
    
    successful_conversions = 0
    failed_conversions = 0
    
    for result in results:
        if "error" in result:
            failed_conversions += 1
            st.error(f"❌ {result['original']} → Fejlede: {result['error']}")
        else:
            successful_conversions += 1
            original_size_mb = result['original_size'] / (1024 * 1024)
            new_size_mb = result['new_size'] / (1024 * 1024)
            size_change = result['size_change']
            
            size_icon = "📉" if size_change < 0 else "📈"
            size_text = "mindre" if size_change < 0 else "større"
            
            st.success(
                f"✅ **{result['original']}** → **{result['converted']}**\n\n"
                f"📏 Størrelse: {original_size_mb:.2f}MB → {new_size_mb:.2f}MB "
                f"({abs(size_change):.1f}% {size_text}) {size_icon}"
            )
    
    # Summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("✅ Succesfulde", successful_conversions)
    with col2:
        st.metric("❌ Fejlede", failed_conversions)
    with col3:
        st.metric("📁 Total filer", len(results))

def create_zip_file(files):
    """Create a ZIP file containing all converted images"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, file_data in files:
            zip_file.writestr(filename, file_data)
    
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def show():
    """Display the image converter page"""
    st.title("T&A Billedfil-converter 🖼️")
    
    st.markdown("""
    **Konverter AVIF, WebP og PNG billeder til JPG eller PNG format**
    
    Dette værktøj hjælper dig med at konvertere moderne billedformater (AVIF, WebP) og PNG billeder til mere kompatible formater (JPG, PNG) 
    der virker på alle platforme og enheder. Særligt nyttigt til at konvertere store PNG filer til mindre JPG filer.
    """)
    
    # Format information box
    with st.expander("ℹ️ Format Information", expanded=False):
        format_info = {
            "PNG": "Standard format med gennemsigtighed support, men store filer",
            "AVIF": "Moderne format med fremragende kompression og kvalitet",
            "WebP": "Google's web-format med god kompression og bred support", 
            "JPEG": "Standard format med god kompatibilitet, mindre filstørrelse",
        }
        
        for fmt, desc in format_info.items():
            st.write(f"**{fmt}**: {desc}")
    
    # Main content area
    st.header("📤 Upload Billeder")
    
    # File uploader with PNG support added
    uploaded_files = st.file_uploader(
        "Vælg AVIF, WebP eller PNG filer",
        type=['avif', 'webp', 'png'],
        accept_multiple_files=True,
        help="Du kan uploade flere filer på én gang"
    )
    
    if not uploaded_files:
        # Show format info when no files uploaded
        st.info("""
        **📋 Understøttede formater:**
        - **PNG**: Standard format med gennemsigtighed support ✅
        - **WebP**: Google's web-format med god kompression ✅
        - **AVIF**: Moderne format med fremragende kompression (kræver system support)
        
        ⚠️ **AVIF Note**: Hvis AVIF filer ikke virker, prøv at installere: `pip install pillow-avif-plugin`
        """)
    
    # Conversion settings - moved to main area
    st.header("⚙️ Konverteringsindstillinger")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Output format selection
        output_format = st.selectbox(
            "Output Format",
            ["JPEG", "PNG"],
            help="Vælg hvilket format dine billeder skal konverteres til"
        )
        
        # Quality setting for JPEG
        if output_format == "JPEG":
            quality = st.slider(
                "JPEG Kvalitet",
                min_value=1,
                max_value=100,
                value=85,
                help="Højere værdier = bedre kvalitet, større filstørrelse"
            )
        else:
            quality = None
    
    with col2:
        # Optional resize
        resize_images = st.checkbox("🔧 Ændre størrelse på billeder")
        if resize_images:
            subcol1, subcol2 = st.columns(2)
            with subcol1:
                max_width = st.number_input("Maks bredde", min_value=100, value=1920)
            with subcol2:
                max_height = st.number_input("Maks højde", min_value=100, value=1080)
        else:
            max_width = max_height = None
    
    if uploaded_files:
        st.success(f"✅ Uploadede {len(uploaded_files)} fil(er)")
        
        # Show preview of uploaded files
        with st.expander("👁️ Forhåndsvisning af uploadede billeder", expanded=True):
            # Calculate columns based on number of files
            num_cols = min(len(uploaded_files), 4)
            cols = st.columns(num_cols)
            
            for idx, uploaded_file in enumerate(uploaded_files[:4]):  # Show max 4 previews
                with cols[idx % num_cols]:
                    try:
                        image = Image.open(uploaded_file)
                        st.image(image, caption=uploaded_file.name, use_container_width=True)
                        
                        # File info
                        file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
                        st.write(f"📏 **Størrelse**: {image.size[0]}x{image.size[1]}")
                        st.write(f"📁 **Filstørrelse**: {file_size_mb:.2f}MB")
                        st.write(f"🎨 **Format**: {uploaded_file.type}")
                        
                    except Exception as e:
                        st.error(f"Fejl ved indlæsning af {uploaded_file.name}: {str(e)}")
            
            if len(uploaded_files) > 4:
                st.info(f"... og {len(uploaded_files) - 4} flere filer")
        
        # Conversion settings summary
        st.subheader("🔧 Konverteringsopsummering")
        settings_text = f"**Format**: {output_format}"
        if output_format == "JPEG" and quality:
            settings_text += f" (kvalitet: {quality}%)"
        if resize_images:
            settings_text += f" | **Størrelse**: Maks {max_width}x{max_height}px"
        st.info(settings_text)
        
        # Convert button
        if st.button("🔄 Konverter Billeder", type="primary", use_container_width=True):
            converted_files, conversion_results = convert_images(
                uploaded_files, output_format, quality, max_width, max_height
            )
            
            # Display results
            if conversion_results:
                display_conversion_results(conversion_results)
                
                # Download section
                if converted_files:
                    st.header("💾 Download Konverterede Filer")
                    
                    if len(converted_files) == 1:
                        # Single file download
                        filename, file_data = converted_files[0]
                        file_extension = "jpeg" if output_format == "JPEG" else "png"
                        
                        st.download_button(
                            label=f"📥 Download {filename}",
                            data=file_data,
                            file_name=filename,
                            mime=f"image/{file_extension}",
                            use_container_width=True
                        )
                    else:
                        # Multiple files - create ZIP
                        zip_data = create_zip_file(converted_files)
                        
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            st.download_button(
                                label=f"📥 Download Alle ({len(converted_files)} filer som ZIP)",
                                data=zip_data,
                                file_name=f"konverterede_billeder_{int(time.time())}.zip",
                                mime="application/zip",
                                use_container_width=True,
                                type="primary"
                            )
                        with col2:
                            zip_size_mb = len(zip_data) / (1024 * 1024)
                            st.metric("ZIP Størrelse", f"{zip_size_mb:.2f} MB")
    
    # Help section
    st.header("❓ Hjælp og Information")
    
    with st.expander("**Understøttede formater og anvendelse 📖**"):
        st.markdown("""
        **Input formater:**
        - **PNG**: Standard format med gennemsigtighed - ofte store filer
        - **AVIF**: Meget moderne format med fremragende kompression og kvalitet
        - **WebP**: Google's web-format med god kompression og stigende support
        
        **Output formater:**
        - **JPEG**: Bedste kompatibilitet, meget mindre filstørrelse, ingen gennemsigtighed
        - **PNG**: Understøtter gennemsigtighed, større filstørrelse, perfekt til grafik
        
        **Hvornår bruges hvad:**
        - **PNG → JPEG**: Ideelt til fotografier hvor gennemsigtighed ikke er nødvendig (stor filreduktion!)
        - **PNG → PNG**: Til komprimering eller størrelse ændring af grafikfiler
        - **AVIF/WebP → JPEG/PNG**: Til kompatibilitet med ældre systemer
        """)
        
    with st.expander("**PNG til JPEG fordele 💡**"):
        st.markdown("""
        **Filstørrelse reduction:**
        - PNG filer kan være 5-10 gange større end JPEG
        - Perfekt til fotografier uden gennemsigtighed
        - Betydelig pladsbesparelse på disk og hurtigere upload/download
        
        **Hvornår beholde PNG:**
        - Logoer og grafik med gennemsigtighed
        - Billeder med skarpe kanter og tekst
        - Når højeste kvalitet er vigtigere end filstørrelse
        
        **Hvornår konvertere til JPEG:**
        - Fotografier og realistiske billeder
        - Når filstørrelse er vigtig (web, email, storage)
        - Når gennemsigtighed ikke er nødvendig
        """)
    
    with st.expander("**Kvalitets- og størrelsesindstillinger 🔧**"):
        st.markdown("""
        **JPEG Kvalitet:**
        - **90-100%**: Høj kvalitet, store filer - til professionelt brug
        - **80-90%**: God kvalitet, moderate filer - til de fleste formål  
        - **70-80%**: Acceptabel kvalitet, små filer - til web og deling
        - **Under 70%**: Synlig kvalitetstab - kun til miniaturebilleder
        
        **Størrelsesændring:**
        - Bevarer billedforholdet (proportioner)
        - Reducerer kun størrelsen, forstørrer ikke
        - Hjælper med at reducere filstørrelse betydeligt
        """)
    
#    with st.expander("**Tekniske begrænsninger ⚠️**"):
#        st.markdown("""
#        **AVIF Support**: Kræver system-specifikke biblioteker. Hvis AVIF ikke virker:
#        ```bash
#        pip install pillow-avif-plugin
#        ```
#        Eller konverter AVIF til WebP først med andre værktøjer.
#        
#        **Filstørrelse**: Maksimalt 200MB per fil (Streamlit begrænsning)
#        
#        **Antal filer**: Ingen fast grænse, men mange store filer kan tage lang tid
#        
#        **Behandlingstid**: Afhænger af filstørrelse og antal - typisk 1-5 sekunder per billede
#        
#        **Hukommelse**: Store billeder (>10MB) kan tage længere tid at behandle
#        
#        **Browser support**: Alle moderne browsere understøtter JPEG og PNG output
#        """)
     
    # Clear results
    if st.session_state.conversion_results:
        st.markdown("---")
        if st.button("🔄 Nulstil og start forfra"):
            st.session_state.conversion_results = []
            st.session_state.converted_files = []
            st.rerun()

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()