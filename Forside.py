import streamlit as st
import os
from auth import AuthManager

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer",
    page_icon="🧙‍♀️",
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
        'current_page': 'home'
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def show():
    """Display the home page"""
    st.title("Værktøjer til Test & Analyse 🛠️ ")
    
    st.markdown("""
    Her finder du forskellige værktøjer og funktioner der forhåbentlig gør dit arbejde lidt nemmere og mere effektivt.
    """)
    
    # Available tools section
    st.header("Tilgængelige værktøjer:")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Billedhenter 🚚")
        st.markdown("""
        **Funktioner:**
        - Søg og download billeder fra ICRT database
            - Upload Excel filer med webkoder
            - Indtast webkoder manuelt
            - Copy Paste webkoder direkte fra excel-ark
        - Finder forslag til alternative billeder (fx. IC23022-0104-00 som alternativ til IC23022-0104-51)
        - Omdøber alternative billeder inden download (fx. omdøber IC23022-0104-00 til IC23022-0104-51 så du ikk ebehøver at gøre det efter donwloadet)
        - Download billeder som ZIP-fil
      
        """)
        
        st.subheader("Baggrundsfjerner 🪄")
        st.markdown("""
        **Funktioner:**
        - Upload billder et eller flere billeder
        - Vælg mellem forskellige lokale KI-modeller til baggrundsfjernelse
        - Vælg kvalitet og format på de behandlede billeder
        - Se preview af billeder med fjernet baggrund
        - Download billeder enkeltvis eller som ZIP-fil      
        """)
        
    
    with col2:
        st.subheader("Kommende værktøjer 🔮")
        st.markdown("""
        **Værktøjer under udvikling:**

        """)
        st.info("Flere værktøjer kommer snart!")
    
 
   
    # Footer
    st.markdown("---")
    st.caption("T&A værktøjer")

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()