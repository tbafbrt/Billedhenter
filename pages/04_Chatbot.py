import streamlit as st
import os
import time
from auth import AuthManager

# Import API clients
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer - TænkGPT Chatbot",
    page_icon="🤖",
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
        'current_page': 'chatbot',
        'messages': [{"role": "assistant", "content": "Hej der! Jeg er din chatbot. Hvad kan jeg hjælpe dig med?"}]
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def add_dollar_signs(model):
    """Add pricing information to model names"""
    pricing = {
        # Mistral models
        "mistral-medium-latest": "($2.5/$7.5)",
        "mistral-large-latest": "($8/$24)",
                
        # Anthropic models
        "claude-3-5-haiku-latest": "($0.25/$1.25)", 
        "claude-3-5-sonnet-latest": "($3/$15)",
        "claude-3-7-sonnet-latest": "($4/$20)",
        "claude-3-opus-latest": "($15/$75)",
        
        # OpenAI models
        "gpt-4o-mini": "($1/$3)",
        "gpt-4.1-nano": "($1/$5)",
        "gpt-4o": "($5/$15)",
        "gpt-4.1-mini": "($5/$15)",
        "gpt-4.1": "($10/$30)"
    }
    return f"{model} {pricing.get(model, '')}"

def get_available_models():
    """Get list of available models based on installed packages"""
    models = []
    
    if MISTRAL_AVAILABLE:
        models.extend([
            "mistral-medium-latest",
            "mistral-large-latest",
        ])
    
    if ANTHROPIC_AVAILABLE:
        models.extend([
            "claude-3-5-haiku-latest", 
            "claude-3-5-sonnet-latest", 
            "claude-3-7-sonnet-latest",
            "claude-3-opus-latest",
        ])
    
    if OPENAI_AVAILABLE:
        models.extend([
            "gpt-4o-mini", 
            "gpt-4.1-nano",
            "gpt-4o", 
            "gpt-4.1-mini",
            "gpt-4.1"
        ])
    
    return models



def show():
    """Display the chatbot page"""
    st.title("T&A TænkGPT Chatbot 🤖")
    
    help_text = '''
    Det er din nye chatbot!
    Hvis du nogensinde har undret dig over hvad GPT står for så er det Gitte Peter Thomas
    '''
    
    st.markdown(help_text)
    
    # Check for missing packages
    missing_packages = []
    if not OPENAI_AVAILABLE:
        missing_packages.append("openai")
    if not ANTHROPIC_AVAILABLE:
        missing_packages.append("anthropic")
    if not MISTRAL_AVAILABLE:
        missing_packages.append("mistralai")
    
    if missing_packages:
        st.warning(f"⚠️ **Manglende pakker**: {', '.join(missing_packages)}")
        st.info(f"Installer med: `pip install {' '.join(missing_packages)}`")
    
    # Simple API key check without exposing keys
    api_keys_configured = True
    try:
        # Test if secrets exist without accessing values
        if "model_keys" not in st.secrets:
            api_keys_configured = False
    except:
        api_keys_configured = False

    if not api_keys_configured:
        st.error("❌ API keys ikke konfigureret korrekt")
        st.info("Konfigurer dine API keys i secrets.toml")
        return
    
    # Get available models
    available_models = get_available_models()
    
    if not available_models:
        st.error("❌ Ingen modeller tilgængelige. Installer påkrævede pakker og konfigurer API keys.")
        return
    
    st.markdown("""
                På denne side kan du chatte med 11 forskellige sprogmodeller fra OpenAI, Anthropic og Mistral. Den fungere nogenlunde 
                som de almindelige chatbogst når du logger ind på chatGPT Claude eller Mistral, men den er mere basic. Så ingen upload 
                af dokumenter eller den slags.<br><br>
                I menuen hvor du kan vælge model står der "(pris input / output per million tokens)" det behøver du ikke tænke så 
                meget over, de er alle meget billige, det er mere en indikation for hvor anvanceret modellen er. Til det meste behøver 
                man ikke den mest avancerede model.
        """, unsafe_allow_html=True)

    st.subheader("Vælg din foretrukne sprogmodel 🚀")

    # Model information expander
    with st.expander("Fold ud for at se en kort forklaring om de enkelte modeller du kan vælge imellem", expanded=False):
        st.markdown("""
            ##### Fra Mistral AI: 
            **Fransk virksomhed - støtt europæiske produkter :)**
            - **Mistral Large**: Nyeste resoneringsmodel til opgaver med høj kompleksitet.
            - **Mistral Medium**: Nyeste version af den billigere Midstral model.
            
            ##### Fra Anthropic Claude:
            - **Claude 3.5 Haiku**: Hurtig, god og meget økonomisk, det oplagte valg hurtige svar på almindelige spørgsmål.
            - **Claude 3.5 Sonnet**: Optimal balance mellem hastighed og dybde, til komplekse, mangefacetterede opgaver
            - **Claude 3.7 Sonnet**: Claudes mest intelligente model til dato.
            - **Claude 3 Opus**: Avancerede funktioner, der tackler de mest krævende resonneringsopgaver og dataintensive scenarier.

            ##### Fra OpenAI:
            - **GPT-4o Mini**: OpenAIs hurtigste, omkostningseffektive resonneringsmodel med stærk præstation inden for matematik, kodning og billedforståelse
            - **GPT-4o**: Standardmodel velegnet til de fleste opgaver
            - **GPT-4.1**: Smarteste model til komplekse opgaver
            - **GPT-4.1 Mini**: Prisvenlig model der balancerer hastighed og intelligens
            - **GPT-4.1 Nano**: Hurtigste, mest omkostningseffektive model til opgaver med lav latenstid
        """, unsafe_allow_html=True)

    # Model selection
    selected_model = st.selectbox(
        "Herunder kan du vælge hvilken model du vil bruge:",
        options=available_models, 
        format_func=add_dollar_signs
    )

    # Display chat messages
    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    # Get user input
    if prompt := st.chat_input("Skriv dit spørgsmål her... Lav linjeskift med shift+enter."):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        
        try:
            # Determine provider and initialize client based on selected model
            if "gpt" in selected_model:
                if not OPENAI_AVAILABLE:
                    st.error("OpenAI pakke ikke installeret")
                    return
                
                client = OpenAI(api_key=st.secrets["model_keys"]["openai_api_key"])
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
                )
                msg = response.choices[0].message.content
                
            elif "claude" in selected_model:
                if not ANTHROPIC_AVAILABLE:
                    st.error("Anthropic pakke ikke installeret")
                    return
                
                client = Anthropic(api_key=st.secrets["model_keys"]["anthropic_api_key"])
                messages = []
                for m in st.session_state.messages:
                    if m["role"] == "assistant":
                        messages.append({"role": "assistant", "content": m["content"]})
                    else:
                        messages.append({"role": "user", "content": m["content"]})
                
                response = client.messages.create(
                    model=selected_model,
                    messages=messages,
                    max_tokens=1000  # Adding required max_tokens parameter
                )
                msg = response.content[0].text
                
            elif "mistral" in selected_model:
                if not MISTRAL_AVAILABLE:
                    st.error("Mistral pakke ikke installeret")
                    return
                
                client = Mistral(api_key=st.secrets["model_keys"]["mistral_api_key"])
                messages = []
                for m in st.session_state.messages:
                    messages.append({
                        "role": m["role"],
                        "content": m["content"]
                    })
                
                # Use the chat.complete method as per Mistral documentation
                chat_response = client.chat.complete(
                    model=selected_model,
                    messages=messages
                )
                    
                # Extract the response
                msg = chat_response.choices[0].message.content
            
            else:
                st.error(f"Ukendt model: {selected_model}")
                return
                
            # Add assistant response to chat history
            st.session_state.messages.append({"role": "assistant", "content": msg})
            st.chat_message("assistant").write(msg)

        except Exception as e:
            error_msg = f"Fejl: {str(e)}"
            st.error(error_msg)
            
            # Provide helpful error messages
            if "api_key" in str(e).lower() or "unauthorized" in str(e).lower():
                st.warning("🔑 API key problem. Tjek at dine API keys er korrekte i secrets.toml")
            elif "quota" in str(e).lower() or "rate limit" in str(e).lower():
                st.warning("📊 Rate limit eller kvote overskredet. Prøv igen om lidt eller opgrader din plan.")
            elif "connection" in str(e).lower() or "network" in str(e).lower():
                st.warning("🌐 Netværksproblem. Tjek din internetforbindelse.")
            else:
                st.info("💡 Prøv at vælge en anden model eller kontakt support.")

    # Chat controls
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 2])
    

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()