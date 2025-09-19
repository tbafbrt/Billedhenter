import streamlit as st
import os
from auth import AuthManager

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&R Apps",
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
    st.title("Værktøjer til Test & Research 🛠️ ")
    
    st.markdown("""
    Her finder du forskellige værktøjer og funktioner der forhåbentlig gør dit arbejde lidt nemmere og mere effektivt.
    """)
    
    # Available tools section
    st.header("Tilgængelige værktøjer:")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Billedhenter 🚚")
        st.markdown("""
        Dette værktøj hjælper dig med at hente billeder fra ICRT databasen.
        """)
        
        st.subheader("Baggrundsfjerner 🧼")
        st.markdown("""
        Dette værktøj fjerner baggrunden fra billeder ved hjælp af avanceret KI-teknologi. (OBS: det loader lidt langsom når man går ind på fanen, så vær lidt tålmodig)
        """)
        
        st.subheader("Billedfil-converter 🔄")
        st.markdown("""
        Dette værktøj konverterer AVIF, WebP og PNG filer til JPG eller PNG format
        """)
        
        st.subheader("T&R TænkGPT Chatbot 💬")
        st.markdown("""
        På denne side kan du chatte med 11 forskellige sprogmodeller fra OpenAI, Anthropic og Mistral.
        """)
        
    
    with col2:
        st.subheader("Kommende værktøjer 🔮")
        st.markdown("""
        **Værktøjer under udvikling:**
        - Tekstanalyse til at genere struktureret data fra lange tekster (kan prøves men virker ikke særlig godt endnu se fanen "Tekstanalyse")
        - PDF ekstrator til at ekstraherer billeder og tekst fra PDF filer
        """)
        
    
 
   
    # Footer
    st.markdown("---")
    st.caption("T&R værktøjer")

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()