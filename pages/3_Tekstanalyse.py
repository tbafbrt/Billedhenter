import streamlit as st
import langextract as lx
from langextract.inference import OpenAILanguageModel
import textwrap
import json
import tempfile
import os
from typing import List, Dict, Any
import pandas as pd

# Import our custom backends (you'd save the previous code as langextract_custom_backends.py)
try:
    from langextract_custom_backends import ClaudeLanguageModel, MistralLanguageModel
    CUSTOM_BACKENDS_AVAILABLE = True
except ImportError:
    CUSTOM_BACKENDS_AVAILABLE = False
    st.warning("Custom backends not available. Save the custom backend code as 'langextract_custom_backends.py'")

# Page configuration
st.set_page_config(
    page_title="LangExtract Studio - Multi-LLM",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        color: white;
        text-align: center;
    }
    
    .llm-option {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #667eea;
        margin: 0.5rem 0;
    }
    
    .extraction-result {
        background: #e8f5e8;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #c3e6c3;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <h1>🔍 LangExtract Studio - Multi-LLM Edition</h1>
    <p>Extract structured information using Gemini, Claude, ChatGPT, Mistral, or local models</p>
</div>
""", unsafe_allow_html=True)

# Sidebar for configuration
with st.sidebar:
    st.header("⚙️ LLM Configuration")
    
    # LLM Provider selection
    llm_provider = st.selectbox(
        "Choose LLM Provider",
        ["Google Gemini", "OpenAI (ChatGPT)", "Anthropic (Claude)", "Mistral AI", "Local (Ollama)"],
        help="Select which AI model provider to use for extraction"
    )
    
    # Model and API key configuration based on provider
    if llm_provider == "Google Gemini":
        st.markdown('<div class="llm-option">Using Google Gemini models</div>', unsafe_allow_html=True)
        model_options = ["gemini-2.5-flash", "gemini-2.5-pro"]
        selected_model = st.selectbox("Gemini Model", model_options)
        api_key = st.text_input("Gemini API Key", type="password", 
                               help="Get from Google AI Studio: https://makersuite.google.com/app/apikey")
        language_model_type = None  # Default Gemini
        use_schema_constraints = True
        fence_output = False
        
    elif llm_provider == "OpenAI (ChatGPT)":
        st.markdown('<div class="llm-option">Using OpenAI GPT models</div>', unsafe_allow_html=True)
        model_options = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]
        selected_model = st.selectbox("OpenAI Model", model_options)
        api_key = st.text_input("OpenAI API Key", type="password",
                               help="Get from OpenAI Platform: https://platform.openai.com/api-keys")
        language_model_type = OpenAILanguageModel
        use_schema_constraints = False
        fence_output = True
        
    elif llm_provider == "Anthropic (Claude)":
        if CUSTOM_BACKENDS_AVAILABLE:
            st.markdown('<div class="llm-option">Using Anthropic Claude models</div>', unsafe_allow_html=True)
            model_options = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
            selected_model = st.selectbox("Claude Model", model_options)
            api_key = st.text_input("Anthropic API Key", type="password",
                                   help="Get from Anthropic Console: https://console.anthropic.com/")
            language_model_type = ClaudeLanguageModel
            use_schema_constraints = False
            fence_output = True
        else:
            st.error("Claude backend not available. Please install the custom backends.")
            selected_model = "claude-3-5-sonnet-20241022"
            api_key = ""
            language_model_type = None
            use_schema_constraints = False
            fence_output = True
            
    elif llm_provider == "Mistral AI":
        if CUSTOM_BACKENDS_AVAILABLE:
            st.markdown('<div class="llm-option">Using Mistral AI models</div>', unsafe_allow_html=True)
            model_options = ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"]
            selected_model = st.selectbox("Mistral Model", model_options)
            api_key = st.text_input("Mistral API Key", type="password",
                                   help="Get from Mistral Platform: https://console.mistral.ai/")
            language_model_type = MistralLanguageModel
            use_schema_constraints = False
            fence_output = True
        else:
            st.error("Mistral backend not available. Please install the custom backends.")
            selected_model = "mistral-large-latest"
            api_key = ""
            language_model_type = None
            use_schema_constraints = False
            fence_output = True
            
    elif llm_provider == "Local (Ollama)":
        st.markdown('<div class="llm-option">Using local Ollama models</div>', unsafe_allow_html=True)
        model_options = ["ollama/llama2", "ollama/mistral", "ollama/codellama", "ollama/vicuna"]
        selected_model = st.selectbox("Ollama Model", model_options)
        api_key = ""  # No API key needed for local models
        language_model_type = None  # LangExtract handles Ollama automatically
        use_schema_constraints = False
        fence_output = True
        st.info("💡 Make sure Ollama is running locally: `ollama serve`")
    
    # Advanced settings
    st.subheader("Advanced Settings")
    extraction_passes = st.slider("Extraction Passes", 1, 5, 1)
    max_workers = st.slider("Max Workers", 1, 20, 5)
    max_char_buffer = st.slider("Max Character Buffer", 500, 2000, 1000)

# Main content area
tab1, tab2, tab3 = st.tabs(["📝 Extract", "📊 Model Comparison", "📚 Documentation"])

with tab1:
    st.header("Multi-LLM Text Extraction")
    
    # Show current configuration
    st.info(f"🤖 **Current Setup**: {llm_provider} - {selected_model}")
    
    # Input methods
    input_method = st.radio(
        "Choose input method:",
        ["Direct Text Input", "File Upload", "URL"],
        horizontal=True
    )
    
    input_text = ""
    
    if input_method == "Direct Text Input":
        input_text = st.text_area(
            "Enter your text:",
            height=200,
            placeholder="Paste your text here..."
        )
    
    elif input_method == "File Upload":
        uploaded_file = st.file_uploader("Upload a text file:", type=['txt', 'md'])
        if uploaded_file is not None:
            input_text = str(uploaded_file.read(), "utf-8")
            st.success(f"File loaded: {len(input_text)} characters")
    
    elif input_method == "URL":
        url_input = st.text_input("Enter URL:", placeholder="https://example.com/document.txt")
        if url_input:
            input_text = url_input
    
    # Extraction configuration
    st.subheader("Extraction Configuration")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        prompt_description = st.text_area(
            "Extraction Prompt:",
            value=textwrap.dedent("""\
            Extract characters, emotions, and relationships in order of appearance.
            Use exact text for extractions. Do not paraphrase or overlap entities.
            Provide meaningful attributes for each entity to add context."""),
            height=150
        )
    
    with col2:
        # Example templates optimized for different LLMs
        example_templates = {
            "Literary Analysis": {
                "text": "ROMEO. But soft! What light through yonder window breaks? It is the east, and Juliet is the sun.",
                "extractions": [
                    {"class": "character", "text": "ROMEO", "attributes": {"emotional_state": "wonder"}},
                    {"class": "emotion", "text": "But soft!", "attributes": {"feeling": "gentle awe"}},
                    {"class": "relationship", "text": "Juliet is the sun", "attributes": {"type": "metaphor"}}
                ]
            },
            "Medical Information": {
                "text": "Patient was prescribed aspirin 81mg daily for cardiovascular protection.",
                "extractions": [
                    {"class": "medication", "text": "aspirin", "attributes": {"dosage": "81mg", "frequency": "daily"}},
                    {"class": "indication", "text": "cardiovascular protection", "attributes": {"type": "preventive"}}
                ]
            }
        }
        
        selected_template = st.selectbox("Choose example template:", list(example_templates.keys()))
        if st.button("Load Template"):
            template = example_templates[selected_template]
            st.session_state.example_text = template["text"]
            st.session_state.example_extractions = template["extractions"]
    
    # Example configuration
    st.subheader("Example for Few-Shot Learning")
    
    example_text = st.text_area(
        "Example Text:",
        value=st.session_state.get("example_text", "ROMEO. But soft! What light through yonder window breaks?"),
        height=100
    )
    
    # Simplified extraction examples for demo
    if 'example_extractions' not in st.session_state:
        st.session_state.example_extractions = [
            {"class": "character", "text": "ROMEO", "attributes": {"emotional_state": "wonder"}},
        ]
    
    # Extract button
    if st.button("🚀 Extract Information", type="primary", use_container_width=True):
        if llm_provider != "Local (Ollama)" and not api_key:
            st.error(f"Please provide your {llm_provider} API key in the sidebar.")
        elif not input_text:
            st.error("Please provide input text.")
        elif not prompt_description:
            st.error("Please provide an extraction prompt.")
        else:
            try:
                with st.spinner(f"Extracting with {llm_provider}..."):
                    # Prepare examples
                    examples = []
                    if example_text and st.session_state.example_extractions:
                        extractions = []
                        for ext in st.session_state.example_extractions:
                            if ext["class"] and ext["text"]:
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
                    
                    # Prepare extraction parameters based on LLM provider
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
                    st.success(f"✅ Extraction completed with {llm_provider}!")
                    
                    # Metrics
                    total_extractions = len(result.extractions)
                    extraction_classes = set(ext.extraction_class for ext in result.extractions)
                    
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Provider", llm_provider.split()[0])
                    col2.metric("Total Extractions", total_extractions)
                    col3.metric("Unique Classes", len(extraction_classes))
                    col4.metric("Text Length", len(input_text))
                    
                    # Display extractions by class
                    st.subheader("📋 Extraction Results")
                    
                    class_groups = {}
                    for ext in result.extractions:
                        class_name = ext.extraction_class
                        if class_name not in class_groups:
                            class_groups[class_name] = []
                        class_groups[class_name].append(ext)
                    
                    for class_name, extractions in class_groups.items():
                        with st.expander(f"📂 {class_name.title()} ({len(extractions)} items)", expanded=True):
                            for ext in extractions:
                                st.markdown(f"""
                                <div class="extraction-result">
                                    <strong>Text:</strong> "{ext.extraction_text}"<br>
                                    <strong>Attributes:</strong> {json.dumps(ext.attributes, indent=2) if ext.attributes else 'None'}<br>
                                    <strong>Position:</strong> Characters {ext.span.start} - {ext.span.end}
                                </div>
                                """, unsafe_allow_html=True)
                    
                    # Visualization
                    st.subheader("📊 Interactive Visualization")
                    
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
                        lx.io.save_annotated_documents([result], f.name)
                        html_content = lx.visualize(f.name)
                        st.components.v1.html(html_content, height=600, scrolling=True)
                        os.unlink(f.name)
                    
                    # Save results to session for comparison
                    if 'extraction_results' not in st.session_state:
                        st.session_state.extraction_results = {}
                    
                    st.session_state.extraction_results[f"{llm_provider}_{selected_model}"] = {
                        "provider": llm_provider,
                        "model": selected_model,
                        "result": result,
                        "total_extractions": total_extractions,
                        "classes": len(extraction_classes)
                    }
            
            except Exception as e:
                st.error(f"❌ Error during extraction: {str(e)}")
                if "API key" in str(e):
                    st.info("Make sure your API key is valid and has sufficient quota.")
                elif "Ollama" in str(e):
                    st.info("Make sure Ollama is running: `ollama serve`")

with tab2:
    st.header("📊 Model Comparison")
    
    if 'extraction_results' in st.session_state and st.session_state.extraction_results:
        st.subheader("Comparison Results")
        
        # Create comparison table
        comparison_data = []
        for key, data in st.session_state.extraction_results.items():
            comparison_data.append({
                "Provider": data["provider"],
                "Model": data["model"],
                "Total Extractions": data["total_extractions"],
                "Unique Classes": data["classes"],
                "Key": key
            })
        
        df_comparison = pd.DataFrame(comparison_data)
        st.dataframe(df_comparison, use_container_width=True)
        
        # Side-by-side comparison
        if len(comparison_data) >= 2:
            st.subheader("Side-by-Side Analysis")
            
            col1, col2 = st.columns(2)
            
            with col1:
                model1_key = st.selectbox("Select First Model:", list(st.session_state.extraction_results.keys()))
                if model1_key:
                    model1_data = st.session_state.extraction_results[model1_key]
                    st.write(f"**{model1_data['provider']} - {model1_data['model']}**")
                    
                    # Show extractions
                    result1 = model1_data['result']
                    class_groups1 = {}
                    for ext in result1.extractions:
                        class_name = ext.extraction_class
                        if class_name not in class_groups1:
                            class_groups1[class_name] = []
                        class_groups1[class_name].append(ext.extraction_text)
                    
                    for class_name, texts in class_groups1.items():
                        st.write(f"**{class_name}**: {', '.join(texts[:5])}")
            
            with col2:
                model2_key = st.selectbox("Select Second Model:", 
                                        [k for k in st.session_state.extraction_results.keys() if k != model1_key])
                if model2_key:
                    model2_data = st.session_state.extraction_results[model2_key]
                    st.write(f"**{model2_data['provider']} - {model2_data['model']}**")
                    
                    # Show extractions
                    result2 = model2_data['result']
                    class_groups2 = {}
                    for ext in result2.extractions:
                        class_name = ext.extraction_class
                        if class_name not in class_groups2:
                            class_groups2[class_name] = []
                        class_groups2[class_name].append(ext.extraction_text)
                    
                    for class_name, texts in class_groups2.items():
                        st.write(f"**{class_name}**: {', '.join(texts[:5])}")
        
        # Clear results button
        if st.button("🗑️ Clear Comparison Results"):
            st.session_state.extraction_results = {}
            st.rerun()
    else:
        st.info("Run extractions with different models to see comparisons here!")
        
        # Model recommendations
        st.subheader("🎯 Model Recommendations")
        
        recommendations = {
            "Google Gemini": {
                "best_for": "General purpose, reliable structured output, medical/scientific text",
                "pros": "Built-in schema constraints, fast, cost-effective",
                "cons": "Requires Google API key",
                "use_case": "Most use cases, especially when you need reliable JSON output"
            },
            "OpenAI (ChatGPT)": {
                "best_for": "Creative tasks, complex reasoning, conversational text",
                "pros": "Strong reasoning, good for creative content",
                "cons": "More expensive, no built-in schema constraints",
                "use_case": "Literature analysis, creative writing, complex reasoning tasks"
            },
            "Anthropic (Claude)": {
                "best_for": "Long documents, analytical tasks, safety-critical applications",
                "pros": "Excellent with long context, very safe outputs",
                "cons": "More expensive, newer API",
                "use_case": "Legal documents, research papers, safety-critical extraction"
            },
            "Mistral AI": {
                "best_for": "European compliance, multilingual tasks, cost-effective",
                "pros": "GDPR compliant, good multilingual support, competitive pricing",
                "cons": "Smaller model ecosystem",
                "use_case": "European data, multilingual content, budget-conscious projects"
            },
            "Local (Ollama)": {
                "best_for": "Privacy, no API costs, offline processing",
                "pros": "Free, private, offline capable",
                "cons": "Requires local setup, potentially lower accuracy",
                "use_case": "Sensitive data, no internet access, unlimited processing"
            }
        }
        
        for provider, info in recommendations.items():
            with st.expander(f"📋 {provider}", expanded=False):
                st.write(f"**Best for:** {info['best_for']}")
                st.write(f"**Pros:** {info['pros']}")
                st.write(f"**Cons:** {info['cons']}")
                st.write(f"**Use case:** {info['use_case']}")

with tab3:
    st.header("📚 Multi-LLM Documentation")
    
    st.markdown("""
    ## 🎯 How to Use Multiple LLMs with LangExtract
    
    This enhanced version of LangExtract Studio supports multiple AI providers, giving you flexibility to choose the best model for your specific use case.
    
    ### 🔧 Setup Requirements
    
    **For Custom Backends (Claude & Mistral):**
    ```bash
    pip install anthropic mistralai
    ```
    
    **Save the custom backend code** as `langextract_custom_backends.py` in the same directory as this app.
    
    ### 🔑 API Key Setup
    
    **Environment Variables (Recommended):**
    ```bash
    export OPENAI_API_KEY="your-openai-key"
    export ANTHROPIC_API_KEY="your-claude-key"  
    export MISTRAL_API_KEY="your-mistral-key"
    export LANGEXTRACT_API_KEY="your-gemini-key"
    ```
    
    **Or use the sidebar** to enter keys directly (less secure for production).
    
    ### 🏆 Model Selection Guide
    
    | Provider | Best For | Cost | Speed | Context Length |
    |----------|----------|------|-------|----------------|
    | **Gemini** | General purpose, medical | Low | Fast | 1M+ tokens |
    | **Claude** | Long documents, safety | High | Medium | 200K tokens |
    | **ChatGPT** | Creative, reasoning | Medium | Fast | 128K tokens |
    | **Mistral** | Multilingual, European | Medium | Fast | 32K tokens |
    | **Ollama** | Privacy, offline | Free | Slow | Varies |
    
    ### ⚙️ Important Settings
    
    **Schema Constraints:** Only available with Gemini models. For other providers, set:
    - `fence_output=True`
    - `use_schema_constraints=False`
    
    **Extraction Passes:** Use 2-3 passes for better recall with non-Gemini models.
    
    ### 🔍 Comparison Features
    
    - **Run multiple models** on the same text
    - **Compare extraction quality** and coverage
    - **Analyze different approaches** to the same task
    - **Choose the best model** for your specific domain
    
    ### 💡 Pro Tips
    
    1. **Start with Gemini** for reliable, structured output
    2. **Use Claude for long documents** (legal, research papers)  
    3. **Try ChatGPT for creative content** (literature, marketing)
    4. **Use Mistral for multilingual** tasks
    5. **Use Ollama for sensitive data** that can't leave your network
    
    ### 🚀 Performance Optimization
    
    - **Increase max_workers** for faster parallel processing
    - **Reduce max_char_buffer** for better accuracy on complex text
    - **Use multiple extraction_passes** for higher recall
    - **Test different models** to find the best fit for your data
    
    ## 🔗 Links
    
    - [LangExtract GitHub](https://github.com/google/langextract)
    - [Google AI Studio](https://makersuite.google.com/app/apikey) (Gemini API)
    - [OpenAI Platform](https://platform.openai.com/api-keys) (ChatGPT API)
    - [Anthropic Console](https://console.anthropic.com/) (Claude API)
    - [Mistral Platform](https://console.mistral.ai/) (Mistral API)
    - [Ollama](https://ollama.ai/) (Local models)
    """)

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666; padding: 20px;'>
    🔍 <strong>LangExtract Studio - Multi-LLM Edition</strong><br>
    Supports Gemini • Claude • ChatGPT • Mistral • Ollama<br>
    <small>Built with ❤️ using Streamlit and LangExtract</small>
</div>
""", unsafe_allow_html=True)
                "