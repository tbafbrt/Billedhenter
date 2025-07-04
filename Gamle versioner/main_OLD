import streamlit as st
import os
from auth import AuthManager
from pages import home, billedhenter

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

def main():
    """Main application entry point"""
    init_session_state()
    
    # Initialize auth manager
    auth = AuthManager()
    
    # Check if user is logged in
    if not st.session_state.logged_in:
        auth.login_screen()
        return
    
    # Sidebar navigation
    with st.sidebar:
        st.header("🧙‍♀️ T&A Værktøjer")
        st.markdown("---")
        
        # Navigation menu
        st.subheader("📍 Navigation")
        
        pages = {
            "🏠 Hjem": "home",
            "📸 Billedhenter": "billedhenter"
        }
        
        for page_name, page_key in pages.items():
            if st.button(page_name, use_container_width=True, 
                        type="primary" if st.session_state.current_page == page_key else "secondary"):
                st.session_state.current_page = page_key
                st.rerun()
        
        st.markdown("---")
        
        # User info and logout
        st.subheader("👤 Bruger")
        st.success("✅ Logget ind")
        
        if st.button("👋 Log ud", use_container_width=True):
            # Clear all session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        st.markdown("---")
        st.caption("T&A Værktøje v2.0")
    
    # Main content area - route to appropriate page
    if st.session_state.current_page == "home":
        home.show()
    elif st.session_state.current_page == "billedhenter":
        billedhenter.show()
    else:
        st.error("Siden blev ikke fundet")

if __name__ == "__main__":
    main()