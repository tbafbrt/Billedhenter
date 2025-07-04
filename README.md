# T&A Portal - Multi-Page Streamlit Application

## 📁 Project Structure

```
ta-portal/
├── main.py                 # Main application entry point
├── auth.py                 # Authentication module
├── common_functions.py     # Shared functions across pages
├── requirements.txt        # Python dependencies
├── .env.template          # Environment template
├── .env                   # Your local environment (create this)
├── .vscode/
│   └── launch.json        # VS Code debug configuration
└── pages/
    ├── __init__.py        # Makes pages a Python package
    ├── home.py            # Home page
    └── billedhenter.py    # Billedhenter page
```

## 🚀 Setup Instructions

### 1. Development Setup (VS Code)

1. **Clone/create the project structure** with all the files shown above

2. **Create environment file**:
   ```bash
   cp .env.template .env
   ```

3. **Edit `.env` file** with your credentials:
   ```bash
   DEV_MODE=true
   LOGIN_USERNAME=admin
   LOGIN_PASSWORD=password123
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Run from VS Code**:
   - Press `F5` or go to Run → Start Debugging
   - Or use the integrated terminal: `streamlit run main.py`

### 2. Production Setup (Streamlit Cloud)

1. **Deploy to Streamlit Cloud** as usual

2. **Configure secrets** in Streamlit Cloud dashboard:
   ```toml
   [login]
   username = "your_production_username"
   password = "your_production_password"
   ```

## 🏗️ Architecture Overview

### Authentication System
- **Global authentication**: All pages require login
- **Development mode**: Uses `.env` file or defaults
- **Production mode**: Uses Streamlit secrets
- **Auto-detection**: Detects VS Code environment automatically

### Page System
- **Modular pages**: Each page is a separate Python module
- **Shared functions**: Common functionality in `common_functions.py`
- **Session state**: Consistent state management across pages
- **Navigation**: Sidebar navigation between pages

### Key Features
- ✅ Multi-page navigation
- ✅ Global authentication
- ✅ Development/production environment handling
- ✅ VS Code debugging support
- ✅ Shared session state
- ✅ Modular code structure

## 🔧 Development Workflow

### Adding New Pages

1. **Create new page file**: `pages/new_page.py`
   ```python
   import streamlit as st
   
   def show():
       st.title("New Page")
       st.write("Content here...")
   ```

2. **Import in main.py**:
   ```python
   from pages import home, billedhenter, new_page
   ```

3. **Add to navigation**:
   ```python
   pages = {
       "🏠 Hjem": "home",
       "📸 Billedhenter": "billedhenter",
       "🆕 New Page": "new_page"  # Add this
   }
   ```

4. **Add route in main()**:
   ```python
   elif st.session_state.current_page == "new_page":
       new_page.show()
   ```

### Using Shared Functions

Import from `common_functions.py`:
```python
from common_functions import ICRTImageDownloader, parse_excel_file
```

### Environment Variables

Development (`.env` file):
```bash
DEV_MODE=true
LOGIN_USERNAME=your_dev_username
LOGIN_PASSWORD=your_dev_password
```

Production (Streamlit secrets):
```toml
[login]
username = "production_username"
password = "production_password"
```

## 🐛 Debugging

### VS Code Debugging
- Set breakpoints in your code
- Press `F5` to start debugging
- Use integrated terminal for Streamlit logs

### Environment Issues
- Check `.env` file exists and has correct format
- Verify `DEV_MODE=true` is set for development
- Check VS Code is detecting environment correctly

### Authentication Issues
- Development: Check `.env` file credentials
- Production: Verify Streamlit secrets configuration
- Check auth module logs in terminal

## 📝 Migration Notes

Your original single-file app has been restructured:

- **Login logic** → `auth.py`
- **Billedhenter functionality** → `pages/billedhenter.py`
- **ICRT API & utilities** → `common_functions.py`
- **Navigation & routing** → `main.py`
- **Home page** → `pages/home.py`

All functionality remains the same, just better organized!

## 🔄 Running the Application

### Development (VS Code):
```bash
# Option 1: Use VS Code debugger (F5)
# Option 2: Terminal
streamlit run main.py
```

### Production:
Deploy to Streamlit Cloud as normal - the app will automatically detect production mode.

## 🎯 Next Steps

1. Test the restructured application
2. Add new pages as needed
3. Extend `common_functions.py` with shared utilities
4. Customize the home page content
5. Add more features to existing pages