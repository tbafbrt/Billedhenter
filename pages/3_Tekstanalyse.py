import streamlit as st
import os
import time
from auth import AuthManager
import langextract as lx
from langextract.inference import OpenAILanguageModel
import textwrap
import json
import tempfile
import pandas as pd
from typing import List, Dict, Any

# Import our custom backends (you'll need to create this file)
try:
    from langextract_backends import ClaudeLanguageModel, MistralLanguageModel
    CUSTOM_BACKENDS_AVAILABLE = True
except ImportError:
    CUSTOM_BACKENDS_AVAILABLE = False

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer - LangExtract",
    page_icon="🔍",
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
        'current_page': 'langextract',
        'extraction_results': {},
        'langextract_api_keys': {},
        'example_text': '',
        'example_extractions': []
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def show():
    """Display the LangExtract page"""
    st.title("T&A LangExtract Studio 🔍")
    
    st.markdown("""
    **Uddrag struktureret information fra tekst ved hjælp af AI**
    
    Dette værktøj bruger forskellige AI-modeller (Gemini, Claude, ChatGPT, Mistral) til at ekstraktere struktureret data 
    fra ustrukturerede tekster som rapporter, artikler, eller dokumenter.
    """)
    
    # Check if custom backends are available
    if not CUSTOM_BACKENDS_AVAILABLE:
        st.warning("""
        ⚠️ **Bemærk:** Kun Gemini og OpenAI modeller er tilgængelige. 
        For at bruge Claude og Mistral, skal `langextract_backends.py` filen oprettes med custom backends.
        """)
    
    # Sidebar for LLM configuration
    with st.sidebar:
        st.header("🤖 AI Model Konfiguration")
        
        # Available providers based on backends
        providers = ["Google Gemini", "OpenAI (ChatGPT)"]
        if CUSTOM_BACKENDS_AVAILABLE:
            providers.extend(["Anthropic (Claude)", "Mistral AI"])
        providers.append("Local (Ollama)")
        
        llm_provider = st.selectbox(
            "Vælg AI Udbyder",
            providers,
            help="Vælg hvilken AI model du vil bruge til ekstraktion"
        )
        
        # Model and API key configuration based on provider
        if llm_provider == "Google Gemini":
            st.markdown("**🔹 Google Gemini modeller**")
            model_options = ["gemini-2.5-flash", "gemini-2.5-pro"]
            selected_model = st.selectbox("Gemini Model", model_options)
            api_key = st.text_input("Gemini API Key", type="password", 
                                   help="Få din API key fra Google AI Studio")
            language_model_type = None
            use_schema_constraints = True
            fence_output = False
            
        elif llm_provider == "OpenAI (ChatGPT)":
            st.markdown("**🔹 OpenAI GPT modeller**")
            model_options = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]
            selected_model = st.selectbox("OpenAI Model", model_options)
            api_key = st.text_input("OpenAI API Key", type="password",
                                   help="Få din API key fra OpenAI Platform")
            language_model_type = OpenAILanguageModel
            use_schema_constraints = False
            fence_output = True
            
        elif llm_provider == "Anthropic (Claude)" and CUSTOM_BACKENDS_AVAILABLE:
            st.markdown("**🔹 Anthropic Claude modeller**")
            model_options = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
            selected_model = st.selectbox("Claude Model", model_options)
            api_key = st.text_input("Anthropic API Key", type="password",
                                   help="Få din API key fra Anthropic Console")
            language_model_type = ClaudeLanguageModel
            use_schema_constraints = False
            fence_output = True
            
        elif llm_provider == "Mistral AI" and CUSTOM_BACKENDS_AVAILABLE:
            st.markdown("**🔹 Mistral AI modeller**")
            model_options = ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"]
            selected_model = st.selectbox("Mistral Model", model_options)
            api_key = st.text_input("Mistral API Key", type="password",
                                   help="Få din API key fra Mistral Platform")
            language_model_type = MistralLanguageModel
            use_schema_constraints = False
            fence_output = True
            
        elif llm_provider == "Local (Ollama)":
            st.markdown("**🔹 Lokale Ollama modeller**")
            model_options = ["ollama/llama2", "ollama/mistral", "ollama/codellama"]
            selected_model = st.selectbox("Ollama Model", model_options)
            api_key = ""
            language_model_type = None
            use_schema_constraints = False
            fence_output = True
            st.info("💡 Sørg for at Ollama kører lokalt: `ollama serve`")
        
        # Advanced settings
        st.subheader("Avancerede Indstillinger")
        extraction_passes = st.slider("Ekstraktionsomgange", 1, 5, 1, 
                                     help="Flere omgange forbedrer recall for komplekse dokumenter")
        max_workers = st.slider("Maksimale Workers", 1, 20, 5, 
                               help="Antal parallelle processing tråde")
        max_char_buffer = st.slider("Maksimal Karakter Buffer", 500, 2000, 1000, 
                                   help="Kontekst vinduesstørrelse for chunking")
    
    # Main content tabs
    tab1, tab2, tab3 = st.tabs(["📝 Tekstekstraktion", "📊 Model Sammenligning", "📚 Hjælp"])
    
    with tab1:
        st.header("AI-Drevet Tekstekstraktion")
        
        # Show current configuration
        provider_emoji = {
            "Google Gemini": "🤖",
            "OpenAI (ChatGPT)": "🧠", 
            "Anthropic (Claude)": "🎭",
            "Mistral AI": "⚡",
            "Local (Ollama)": "🏠"
        }
        
        st.info(f"{provider_emoji.get(llm_provider, '🤖')} **Aktuel konfiguration**: {llm_provider} - {selected_model}")
        
        # Input methods
        st.subheader("📋 Input Metoder")
        input_method = st.radio(
            "Vælg input metode:",
            ["Direkte Tekst Input", "Fil Upload", "URL"],
            horizontal=True,
            help="Vælg hvordan du vil indtaste teksten der skal behandles"
        )
        
        input_text = ""
        
        if input_method == "Direkte Tekst Input":
            input_text = st.text_area(
                "Indtast din tekst:",
                height=200,
                placeholder="Indsæt din tekst her...",
                help="Indsæt den tekst du vil uddrage information fra"
            )
        
        elif input_method == "Fil Upload":
            uploaded_file = st.file_uploader(
                "Upload en tekstfil:",
                type=['txt', 'md'],
                help="Upload .txt eller .md filer"
            )
            
            if uploaded_file is not None:
                input_text = str(uploaded_file.read(), "utf-8")
                st.success(f"Fil indlæst: {len(input_text)} tegn")
        
        elif input_method == "URL":
            url_input = st.text_input(
                "Indtast URL:",
                placeholder="https://example.com/document.txt",
                help="URL til en tekstfil på internettet"
            )
            if url_input:
                input_text = url_input
        
        # Extraction configuration
        st.subheader("⚙️ Ekstraktionskonfiguration")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            # Prompt definition
            prompt_description = st.text_area(
                "Ekstraktions Prompt:",
                value=textwrap.dedent("""\
                Uddrag karakterer, følelser og relationer i rækkefølge af fremkomst.
                Brug nøjagtig tekst til ekstraktioner. Omformulér ikke eller overlap entiteter.
                Giv meningsfulde attributter for hver entitet for at tilføje kontekst."""),
                height=150,
                help="Beskriv hvad du vil uddrage fra teksten"
            )
        
        with col2:
            # Example templates in Danish
            example_templates = {
                "Litterær Analyse": {
                    "text": "ROMEO. Men stille! Hvilket lys gennem det vindue bryder? Det er øst, og Julie er solen.",
                    "extractions": [
                        {"class": "karakter", "text": "ROMEO", "attributes": {"følelsesmæssig_tilstand": "undren"}},
                        {"class": "følelse", "text": "Men stille!", "attributes": {"følelse": "blid ærefrygt"}},
                        {"class": "relation", "text": "Julie er solen", "attributes": {"type": "metafor"}}
                    ]
                },
                "Medicinsk Information": {
                    "text": "Patienten blev ordineret aspirin 81mg dagligt til kardiovaskulær beskyttelse.",
                    "extractions": [
                        {"class": "medicin", "text": "aspirin", "attributes": {"dosering": "81mg", "frekvens": "dagligt"}},
                        {"class": "indikation", "text": "kardiovaskulær beskyttelse", "attributes": {"type": "forebyggende"}}
                    ]
                },
                "Juridisk Dokument": {
                    "text": "Kontrakten skal opsiges den 31. december 2024, medmindre den fornyes ved gensidig samtykke.",
                    "extractions": [
                        {"class": "dato", "text": "31. december 2024", "attributes": {"type": "opsigelsesdato"}},
                        {"class": "betingelse", "text": "medmindre den fornyes ved gensidig samtykke", "attributes": {"type": "fornyelsesklausul"}}
                    ]
                }
            }
            
            selected_template = st.selectbox("Vælg eksempel skabelon:", list(example_templates.keys()))
            
            if st.button("📋 Indlæs Skabelon"):
                template = example_templates[selected_template]
                st.session_state.example_text = template["text"]
                st.session_state.example_extractions = template["extractions"]
                st.success(f"Skabelon '{selected_template}' indlæst!")
                st.rerun()
                st.write(f"🔍 Current example_extractions after template section: {st.session_state.example_extractions}")
        
        # Example configuration
        st.subheader("💡 Eksempel til Few-Shot Læring")
        
        example_text = st.text_area(
            "Eksempel Tekst:",
            value=st.session_state.get("example_text", "ROMEO. Men stille! Hvilket lys gennem det vindue bryder?"),
            height=100,
            help="Giv et eksempel på den type tekst du vil behandle"
        )
        
        # Simplified extraction examples
        if 'example_extractions' not in st.session_state:
            st.session_state.example_extractions = [
                {"class": "karakter", "text": "ROMEO", "attributes": {"følelsesmæssig_tilstand": "undren"}},
            ]
        
        # DEBUG LINE:
        st.write(f"🔍 example_extractions after initialization: {st.session_state.example_extractions}")
        
        # Display current examples
        st.write("**Aktuelle Eksempel Ekstraktioner:**")
        for i, ext in enumerate(st.session_state.example_extractions):
            st.write(f"• **{ext.get('class', 'N/A')}**: '{ext.get('text', 'N/A')}' - {ext.get('attributes', {})}")
        
        # Extract button
        if st.button("🚀 Start Ekstraktion", type="primary", use_container_width=True):
            if llm_provider != "Local (Ollama)" and not api_key:
                st.error(f"Indtast venligst din {llm_provider} API key i sidebaren.")
            elif not input_text:
                st.error("Indtast venligst input tekst.")
            elif not prompt_description:
                st.error("Indtast venligst en ekstraktions prompt.")
            else:
                try:
                    with st.spinner(f"Ekstrakterer med {llm_provider}..."):
                        # Prepare examples
                        examples = []
                        
                        # DEBUG LINES - START:
                        st.write("🔍 DEBUG INFO:")
                        st.write(f"example_text: '{example_text}'")
                        st.write(f"example_text length: {len(example_text) if example_text else 0}")
                        st.write(f"st.session_state.example_extractions: {st.session_state.example_extractions}")
                        st.write(f"Type of example_extractions: {type(st.session_state.example_extractions)}")

                        if example_text and st.session_state.example_extractions:
                            st.write("✅ Both example_text and example_extractions exist")
                            extractions = []
                            for i, ext in enumerate(st.session_state.example_extractions):
                                st.write(f"Processing extraction {i}: {ext}")
                                st.write(f"ext.get('class'): '{ext.get('class')}'")
                                st.write(f"ext.get('text'): '{ext.get('text')}'")
                                
                                if ext.get("class") and ext.get("text"):
                                    st.write(f"✅ Adding extraction {i} to examples")
                                    # ... your existing code
                                else:
                                    st.write(f"❌ Skipping extraction {i} - missing class or text")
                            
                            st.write(f"Total extractions created: {len(extractions)}")
                            st.write(f"Total examples created: {len(examples)}")
                        else:
                            st.write("❌ Missing example_text or example_extractions")
                            if not example_text:
                                st.write("Missing: example_text")
                            if not st.session_state.example_extractions:
                                st.write("Missing: example_extractions")
                        
                        # DEBUGGING LINES - SLUT
                        
                        if example_text and st.session_state.example_extractions:
                            extractions = []
                            for ext in st.session_state.example_extractions:
                                if ext.get("class") and ext.get("text"):
                                    extractions.append(
                                        lx.data.Extraction(
                                            extraction_class=ext["class"],
                                            extraction_text=ext["text"],
                                            attributes=ext["attributes"]
                                        )
                                    )
                            
                            if extractions:
                                examples.append(
                                    lx.data.ExampleData(
                                        text=example_text,
                                        extractions=extractions
                                    )
                                )
                        
                        # Prepare extraction parameters
                        extract_params = {
                            "text_or_documents": input_text,
                            "prompt_description": prompt_description,
                            "examples": examples,
                            "model_id": selected_model,
                            "extraction_passes": extraction_passes,
                            "max_workers": max_workers,
                            "max_char_buffer": max_char_buffer,
                            "fence_output": fence_output,
                            "use_schema_constraints": use_schema_constraints
                        }
                        
                        # Add API key if needed
                        if api_key:
                            extract_params["api_key"] = api_key
                        
                        # Add language model type if needed
                        if language_model_type:
                            extract_params["language_model_type"] = language_model_type
                        
                        # Run extraction
                        result = lx.extract(**extract_params)
                        
                        # Display results
                        st.success(f"✅ Ekstraktion fuldført med {llm_provider}!")
                        
                        # Metrics
                        total_extractions = len(result.extractions)
                        extraction_classes = set(ext.extraction_class for ext in result.extractions)
                        
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Udbyder", llm_provider.split()[0])
                        col2.metric("Total Ekstraktioner", total_extractions)
                        col3.metric("Unikke Klasser", len(extraction_classes))
                        col4.metric("Tekst Længde", len(input_text))
                        
                        # Display extractions by class
                        st.subheader("📋 Ekstraktions Resultater")
                        
                        class_groups = {}
                        for ext in result.extractions:
                            class_name = ext.extraction_class
                            if class_name not in class_groups:
                                class_groups[class_name] = []
                            class_groups[class_name].append(ext)
                        
                        for class_name, extractions in class_groups.items():
                            with st.expander(f"📂 {class_name.title()} ({len(extractions)} emner)", expanded=True):
                                for ext in extractions:
                                    st.markdown(f"""
                                    <div style="background: #e8f5e8; padding: 1rem; border-radius: 8px; margin: 0.5rem 0; border: 1px solid #c3e6c3;">
                                        <strong>Tekst:</strong> "{ext.extraction_text}"<br>
                                        <strong>Attributter:</strong> {json.dumps(ext.attributes, indent=2, ensure_ascii=False) if ext.attributes else 'Ingen'}<br>
                                        <strong>Position:</strong> Tegn {ext.span.start} - {ext.span.end}
                                    </div>
                                    """, unsafe_allow_html=True)
                        
                        # Visualization
                        st.subheader("📊 Interaktiv Visualisering")
                        
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
                            lx.io.save_annotated_documents([result], f.name)
                            html_content = lx.visualize(f.name)
                            st.components.v1.html(html_content, height=600, scrolling=True)
                            os.unlink(f.name)
                        
                        # Download options
                        st.subheader("💾 Download Resultater")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            # JSON download
                            results_json = {
                                "ekstraktioner": [
                                    {
                                        "klasse": ext.extraction_class,
                                        "tekst": ext.extraction_text,
                                        "attributter": ext.attributes,
                                        "position": {"start": ext.span.start, "end": ext.span.end}
                                    }
                                    for ext in result.extractions
                                ]
                            }
                            
                            st.download_button(
                                "📄 Download JSON",
                                data=json.dumps(results_json, indent=2, ensure_ascii=False),
                                file_name=f"langextract_resultater_{int(time.time())}.json",
                                mime="application/json"
                            )
                        
                        with col2:
                            # CSV download
                            df_data = []
                            for ext in result.extractions:
                                row = {
                                    "klasse": ext.extraction_class,
                                    "tekst": ext.extraction_text,
                                    "start": ext.span.start,
                                    "end": ext.span.end
                                }
                                # Add attributes as separate columns
                                for key, value in (ext.attributes or {}).items():
                                    row[f"attr_{key}"] = value
                                df_data.append(row)
                            
                            df = pd.DataFrame(df_data)
                            csv = df.to_csv(index=False, encoding='utf-8')
                            
                            st.download_button(
                                "📊 Download CSV",
                                data=csv,
                                file_name=f"langextract_resultater_{int(time.time())}.csv",
                                mime="text/csv"
                            )
                        
                        # Save results for comparison
                        if 'extraction_results' not in st.session_state:
                            st.session_state.extraction_results = {}
                        
                        st.session_state.extraction_results[f"{llm_provider}_{selected_model}_{int(time.time())}"] = {
                            "provider": llm_provider,
                            "model": selected_model,
                            "result": result,
                            "total_extractions": total_extractions,
                            "classes": len(extraction_classes),
                            "timestamp": time.time()
                        }
                
                except Exception as e:
                    st.error(f"❌ Fejl under ekstraktion: {str(e)}")
                    if "API key" in str(e).lower():
                        st.info("Sørg for at din API key er gyldig og har tilstrækkelig kvote.")
                    elif "ollama" in str(e).lower():
                        st.info("Sørg for at Ollama kører: `ollama serve`")
                    else:
                        st.info("Tjek din internetforbindelse og prøv igen.")
    
    with tab2:
        st.header("📊 Model Sammenligning")
        
        if 'extraction_results' in st.session_state and st.session_state.extraction_results:
            st.subheader("Sammenligning af Resultater")
            
            # Create comparison table
            comparison_data = []
            for key, data in st.session_state.extraction_results.items():
                comparison_data.append({
                    "Udbyder": data["provider"],
                    "Model": data["model"],
                    "Total Ekstraktioner": data["total_extractions"],
                    "Unikke Klasser": data["classes"],
                    "Tidsstempel": time.strftime("%H:%M:%S", time.localtime(data["timestamp"]))
                })
            
            df_comparison = pd.DataFrame(comparison_data)
            st.dataframe(df_comparison, use_container_width=True)
            
            # Clear results button
            if st.button("🗑️ Ryd Sammenligning"):
                st.session_state.extraction_results = {}
                st.success("Sammenligningsresultater ryddet!")
                st.rerun()
        else:
            st.info("Kør ekstraktioner med forskellige modeller for at se sammenligninger her!")
            
            # Model recommendations in Danish
            st.subheader("🎯 Model Anbefalinger")
            
            recommendations = {
                "Google Gemini": {
                    "bedst_til": "Generel brug, pålidelig struktureret output, medicinsk/videnskabelig tekst",
                    "fordele": "Indbyggede skema begrænsninger, hurtig, omkostningseffektiv",
                    "ulemper": "Kræver Google API key",
                    "anvendelse": "De fleste use cases, især når du har brug for pålidelig JSON output"
                },
                "OpenAI (ChatGPT)": {
                    "bedst_til": "Kreative opgaver, kompleks ræsonnement, samtale tekst",
                    "fordele": "Stærk ræsonnement, god til kreativt indhold",
                    "ulemper": "Dyrere, ingen indbyggede skema begrænsninger",
                    "anvendelse": "Litterær analyse, kreativ skrivning, komplekse ræsonnement opgaver"
                },
                "Anthropic (Claude)": {
                    "bedst_til": "Lange dokumenter, analytiske opgaver, sikkerhedskritiske applikationer",
                    "fordele": "Fremragende med lang kontekst, meget sikre outputs",
                    "ulemper": "Dyrere, nyere API",
                    "anvendelse": "Juridiske dokumenter, forskningsartikler, sikkerhedskritisk ekstraktion"
                },
                "Mistral AI": {
                    "bedst_til": "Europæisk compliance, flersprogede opgaver, omkostningseffektiv",
                    "fordele": "GDPR compliant, god flersproget support, konkurrencedygtige priser",
                    "ulemper": "Mindre model økosystem",
                    "anvendelse": "Europæiske data, flersproget indhold, budget-bevidste projekter"
                }
            }
            
            for provider, info in recommendations.items():
                with st.expander(f"📋 {provider}", expanded=False):
                    st.write(f"**Bedst til:** {info['bedst_til']}")
                    st.write(f"**Fordele:** {info['fordele']}")
                    st.write(f"**Ulemper:** {info['ulemper']}")
                    st.write(f"**Anvendelse:** {info['anvendelse']}")
    
    with tab3:
        st.header("📚 Hjælp og Dokumentation")
        
        st.markdown("""
        ## 🎯 Sådan Bruger Du LangExtract
        
        LangExtract er et kraftfuldt værktøj til at uddrage struktureret information fra ustrukturerede tekster ved hjælp af AI.
        
        ### 🔧 Opsætning
        
        1. **Vælg AI Udbyder** i sidebaren
        2. **Indtast API Key** for din valgte udbyder
        3. **Konfigurér model** og avancerede indstillinger
        
        ### 📝 Brug
        
        1. **Indtast tekst** via en af de tre metoder
        2. **Definér ekstraktions prompt** - beskriv hvad du vil uddrage
        3. **Giv eksempler** til few-shot læring
        4. **Kør ekstraktion** og se resultater
        
        ### 🔑 API Keys
        
        **Få API keys fra:**
        - **Google Gemini**: [Google AI Studio](https://makersuite.google.com/app/apikey)
        - **OpenAI**: [OpenAI Platform](https://platform.openai.com/api-keys)
        - **Anthropic**: [Anthropic Console](https://console.anthropic.com/)
        - **Mistral**: [Mistral Platform](https://console.mistral.ai/)
        
        ### 💡 Tips til Bedste Resultater
        
        - **Vær specifik** i dine prompts
        - **Giv gode eksempler** til few-shot læring
        - **Test forskellige modeller** for dit use case
        - **Brug flere ekstraktionsomgange** for bedre recall
        
        ### ⚠️ Begrænsninger
        
        - **API Omkostninger**: Vær opmærksom på priser for forskellige modeller
        - **Rate Limits**: Forskellige udbydere har forskellige grænser
        - **Kontekst Længde**: Nogle modeller har begrænsninger på tekstlængde
        
        ### 🏷️ Use Cases
        
        - **Litterær analyse** - Uddrag karakterer, temaer, følelser
        - **Medicinsk tekst** - Uddrag medicin, doser, symptomer
        - **Juridiske dokumenter** - Uddrag klausuler, datoer, parter
        - **Nyhedsartikler** - Uddrag fakta, begivenheder, personer
        - **Forskningsartikler** - Uddrag nøgleord, resultater, konklusioner
        """)

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()