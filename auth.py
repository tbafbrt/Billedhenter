import streamlit as st
import time
import os

class AuthManager:
    """Handles authentication for the entire application"""
    
    def __init__(self):
        self.is_dev_mode = self._check_dev_mode()
    
    def _check_dev_mode(self) -> bool:
        """Check if running in development mode (VS Code)"""
        # Check for development environment indicators
        return (
            os.getenv('VSCODE_PID') is not None or  # VS Code environment
            os.getenv('DEV_MODE') == 'true' or      # Manual dev mode flag
            'localhost' in os.getenv('STREAMLIT_SERVER_ADDRESS', '') or
            os.path.exists('.env')  # Local .env file exists
        )
    
    def _get_credentials(self):
        """Get credentials from secrets or environment"""
        if self.is_dev_mode:
            # Development mode - use environment variables or defaults
            return {
                'username': os.getenv('LOGIN_USERNAME', 'admin'),
                'password': os.getenv('LOGIN_PASSWORD', 'password123')
            }
        else:
            # Production mode - use Streamlit secrets
            try:
                return {
                    'username': st.secrets["login"]["username"],
                    'password': st.secrets["login"]["password"]
                }
            except KeyError as e:
                st.error(f"Login configuration error: Missing key {e}")
                st.error("Please check your Streamlit secrets configuration.")
                return None
    
    def login_screen(self):
        """Display login screen"""
        st.title("🔐 T&A Værktøjer Login")
        
        # Show development mode indicator
        if self.is_dev_mode:
            st.info("🛠️ **Development Mode** - Bruger lokale loginoplysninger")
            with st.expander("👨‍💻 Development Info", expanded=False):
                st.code("""
                Standard udvikling login:
                Username: admin
                Password: password123
                
                Eller sæt environment variables:
                LOGIN_USERNAME=your_username
                LOGIN_PASSWORD=your_password
                """)
        
        st.markdown("Skriv dine loginoplysninger for at fortsætte.")
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                credentials = self._get_credentials()
                
                if credentials is None:
                    return  # Error already shown in _get_credentials
                
                if username == credentials['username'] and password == credentials['password']:
                    st.session_state.logged_in = True
                    st.success("Login successful!")
                    time.sleep(1)
                    st.rerun()
                elif username and password:
                    st.error("Invalid username or password")
                else:
                    st.error("Please enter both username and password")
        
        # Debug section for development
        if self.is_dev_mode:
            with st.expander("🔧 Debug: Login Configuration", expanded=False):
                credentials = self._get_credentials()
                if credentials:
                    st.write("✅ Credentials loaded successfully")
                    st.write(f"✅ Username: '{credentials['username']}'")
                    st.write("✅ Password: [HIDDEN]")
                else:
                    st.write("❌ Failed to load credentials")
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return st.session_state.get('logged_in', False)
    
    def logout(self):
        """Logout user and clear session"""
        for key in list(st.session_state.keys()):
            del st.session_state[key]