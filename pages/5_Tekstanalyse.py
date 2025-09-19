import streamlit as st
import os
import time
import json
import hashlib
import smtplib
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO, StringIO
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import pandas as pd

# Basic imports that should always work
import requests

# Optional imports with safe fallbacks
try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False
    BeautifulSoup = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False

try:
    import langextract as lx
    LANGEXTRACT_AVAILABLE = True
except ImportError:
    LANGEXTRACT_AVAILABLE = False

# AI model imports
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

# Auth manager
from auth import AuthManager

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Configure Streamlit page
st.set_page_config(
    page_title="T&A Værktøjer - Tekstanalyse",
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
        'current_page': 'tekstanalyse',
        'gdpr_categories': get_default_gdpr_categories(),
        'custom_categories': [],
        'scoring_criteria': get_default_scoring_criteria(),
        'analyzed_documents': {},
        'batch_queue': [],
        'monitoring_enabled': False,
        'notification_settings': {}
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def get_default_gdpr_categories():
    """Default GDPR analysis categories"""
    return {
        'dataindsamling': {
            'name': 'Dataindsamling og formål',
            'description': 'Hvilke personoplysninger indsamles og til hvilket formål',
            'keywords': ['personoplysninger', 'data collection', 'personal data', 'information we collect']
        },
        'brugerrettigheder': {
            'name': 'Brugerrettigheder',
            'description': 'Rettigheder til sletning, indsigt, portabilitet og rettelse',
            'keywords': ['right to erasure', 'right to access', 'data portability', 'rectification']
        },
        'retsgrundlag': {
            'name': 'Behandlingsgrundlag',
            'description': 'Lovligt grundlag for databehandling',
            'keywords': ['legal basis', 'consent', 'legitimate interest', 'contract']
        },
        'tredjepartsdeling': {
            'name': 'Deling med tredjeparter',
            'description': 'Hvem data deles med og hvorfor',
            'keywords': ['third parties', 'sharing', 'partners', 'vendors']
        },
        'opbevaring': {
            'name': 'Opbevaringsperioder',
            'description': 'Hvor længe data opbevares',
            'keywords': ['retention', 'storage period', 'delete', 'keep data']
        },
        'sikkerhed': {
            'name': 'Datasikkerhed',
            'description': 'Sikkerhedsforanstaltninger og databeskyttelse',
            'keywords': ['security measures', 'encryption', 'protection', 'safeguards']
        },
        'børn': {
            'name': 'Børns data',
            'description': 'Særlige regler for behandling af børns personoplysninger',
            'keywords': ['children', 'minors', 'under 18', 'parental consent']
        },
        'overførsel': {
            'name': 'Internationale overførsler',
            'description': 'Overførsel af data til lande uden for EU/EØS',
            'keywords': ['international transfer', 'third countries', 'adequacy decision', 'safeguards']
        }
    }

def get_default_scoring_criteria():
    """Default scoring criteria for GDPR compliance"""
    return {
        'transparency': {
            'name': 'Transparens',
            'weight': 0.25,
            'criteria': 'Hvor klart og forståeligt er privatlivspolitikken?'
        },
        'user_rights': {
            'name': 'Brugerrettigheder',
            'weight': 0.30,
            'criteria': 'Hvor godt beskrives brugerens rettigheder?'
        },
        'data_minimization': {
            'name': 'Dataminimering',
            'weight': 0.20,
            'criteria': 'Indsamles kun nødvendige data?'
        },
        'security': {
            'name': 'Sikkerhed',
            'weight': 0.15,
            'criteria': 'Hvor gode er sikkerhedsforanstaltningerne?'
        },
        'accountability': {
            'name': 'Ansvarlighed',
            'weight': 0.10,
            'criteria': 'Påtager virksomheden sig ansvar for GDPR compliance?'
        }
    }

class WebScraper:
    """Hybrid web scraper using requests and selenium fallback"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def scrape_url(self, url: str) -> Dict[str, Any]:
        """Scrape content from URL using hybrid approach"""
        try:
            # Try requests first
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                if BEAUTIFULSOUP_AVAILABLE:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    text = self.extract_text_from_soup(soup)
                else:
                    # Fallback without BeautifulSoup
                    text = self.extract_text_simple(response.text)
                
                if len(text.strip()) > 100:  # Success if we got substantial content
                    return {
                        'success': True,
                        'content': text,
                        'method': 'requests',
                        'url': url,
                        'timestamp': datetime.now().isoformat()
                    }
            
            # Fallback to Selenium if requests failed or got minimal content
            if SELENIUM_AVAILABLE:
                return self.scrape_with_selenium(url)
            else:
                return {
                    'success': False,
                    'error': 'Requests failed and Selenium not available',
                    'url': url
                }
                
        except Exception as e:
            if SELENIUM_AVAILABLE:
                return self.scrape_with_selenium(url)
            else:
                return {
                    'success': False,
                    'error': str(e),
                    'url': url
                }
    
    def scrape_with_selenium(self, url: str) -> Dict[str, Any]:
        """Fallback scraping with Selenium"""
        if not SELENIUM_AVAILABLE:
            return {
                'success': False,
                'error': 'Selenium not available',
                'url': url
            }
            
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            driver.get(url)
            time.sleep(3)  # Wait for JS to load
            
            # Extract text content
            text = driver.execute_script("return document.body.innerText;")
            driver.quit()
            
            return {
                'success': True,
                'content': text,
                'method': 'selenium',
                'url': url,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'url': url
            }
    
    def extract_text_from_soup(self, soup) -> str:
        """Extract clean text from BeautifulSoup object"""
        if not BEAUTIFULSOUP_AVAILABLE or not soup:
            return ""
            
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.extract()
        
        # Get text and clean it
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        return text
    
    def extract_text_simple(self, html_content: str) -> str:
        """Simple text extraction without BeautifulSoup"""
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html_content)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

class GDPRAnalyzer:
    """Main GDPR analysis class using LangExtract"""
    
    def __init__(self, model_provider: str, model_name: str, api_key: str = None):
        self.model_provider = model_provider
        self.model_name = model_name
        self.api_key = api_key
        self.scraper = WebScraper()
    
    def analyze_document(self, content: str, url: str = None) -> Dict[str, Any]:
        """Analyze a document for GDPR compliance"""
        if not LANGEXTRACT_AVAILABLE:
            return {
                'success': False,
                'error': 'LangExtract is required for analysis'
            }
            
        categories = st.session_state.gdpr_categories
        
        # Create LangExtract prompt
        prompt = self.create_gdpr_prompt(categories)
        examples = self.create_gdpr_examples()
        
        try:
            # Debug output for at se hvad der sker
            st.write(f"Debug: Model provider: {self.model_provider}")
            st.write(f"Debug: Model name: {self.model_name}")
            
            # Perform extraction med korrekt OpenAI konfiguration
            extract_params = {
                "text_or_documents": content,
                "prompt_description": prompt,
                "examples": examples,
                "model_id": self.model_name,
                "extraction_passes": 1,
                "max_workers": 1,
                "max_char_buffer": 1000
            }
            
            # Configure provider-specific settings
            if self.model_provider == "OpenAI":
                st.write("Debug: Konfigurerer for OpenAI...")
                # OpenAI specific configuration based on LangExtract docs
                extract_params["fence_output"] = True
                extract_params["use_schema_constraints"] = False
                
                # Få API key
                try:
                    api_key = st.secrets["model_keys"]["openai_api_key"]
                    st.write("Debug: OpenAI API key hentet fra secrets")
                except KeyError:
                    api_key = self.api_key
                    st.write("Debug: Bruger manuel OpenAI API key")
                
                # Set environment variable to force OpenAI usage
                import os
                os.environ['OPENAI_API_KEY'] = api_key
                extract_params["api_key"] = api_key
                
                # Force OpenAI language model
                from langextract.inference import OpenAILanguageModel
                extract_params["language_model_type"] = OpenAILanguageModel
                
            elif self.model_provider == "Google Gemini":
                st.write("Debug: Konfigurerer for Google Gemini...")
                # Gemini specific configuration
                extract_params["fence_output"] = False
                extract_params["use_schema_constraints"] = True
                try:
                    api_key = st.secrets["model_keys"]["google_api_key"]
                    st.write("Debug: Google API key hentet fra secrets")
                except KeyError:
                    api_key = self.api_key
                    st.write("Debug: Bruger manuel Google API key")
                extract_params["api_key"] = api_key
                
            elif self.model_provider == "Anthropic":
                # LangExtract understøtter ikke Anthropic direkte
                return {
                    'success': False,
                    'error': 'LangExtract understøtter ikke Anthropic Claude modeller. Vælg Google Gemini eller OpenAI i stedet.'
                }
            else:
                st.error(f"Debug: Ukendt provider: {self.model_provider}")
                return {
                    'success': False,
                    'error': f'Ukendt model provider: {self.model_provider}'
                }
            
            st.write(f"Debug: Final extract_params keys: {list(extract_params.keys())}")
            st.write(f"Debug: Language model type: {extract_params.get('language_model_type', 'Default')}")
            
            result = lx.extract(**extract_params)
            
            # Process results
            analysis = self.process_langextract_results(result, content, url)
            
            return {
                'success': True,
                'analysis': analysis,
                'raw_extractions': result.extractions,
                'content_hash': hashlib.md5(content.encode()).hexdigest(),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'content_hash': hashlib.md5(content.encode()).hexdigest() if content else None
            }
    
    def create_gdpr_prompt(self, categories: Dict) -> str:
        """Create GDPR analysis prompt for LangExtract"""
        category_descriptions = []
        for key, cat in categories.items():
            category_descriptions.append(f"- {key}: {cat['name']} - {cat['description']}")
        
        prompt = f"""
Analyser denne tekst for GDPR compliance og privatlivspraksis. 
Uddrag relevante klausuler og citater for følgende kategorier:

{chr(10).join(category_descriptions)}

VIGTIGT: Du SKAL returnere valid JSON format.

For hver extraction:
- extraction_class: en af kategori nøglerne ({', '.join(categories.keys())})
- extraction_text: det præcise citat fra teksten 
- attributes med compliance_score (1-5), note (kort beskrivelse), issues (problemer eller "Ingen")

Eksempel på korrekt JSON output:
[
  {{
    "extraction_class": "dataindsamling",
    "extraction_text": "Vi indsamler navn og email",
    "attributes": {{
      "compliance_score": 4,
      "note": "Klar specifikation",
      "issues": "Ingen"
    }}
  }}
]

Returner ALTID valid JSON array format.
"""
        return prompt
    
    def create_gdpr_examples(self) -> List:
        """Create example extractions for few-shot learning"""
        example_text = """
Vi indsamler følgende personoplysninger: navn, e-mail, IP-adresse og browseroplysninger. 
Data opbevares i 2 år efter kontraktophør. Du har ret til at få slettet dine data ved henvendelse til privacy@example.com.
Data deles med vores betalingspartner Stripe og analysepartner Google Analytics.
"""
        
        examples = [
            lx.data.ExampleData(
                text=example_text,
                extractions=[
                    lx.data.Extraction(
                        extraction_class="dataindsamling",
                        extraction_text="navn, e-mail, IP-adresse og browseroplysninger",
                        attributes={
                            "compliance_score": 4,
                            "note": "Klar specifikation af indsamlede data",
                            "issues": "Ingen"
                        }
                    ),
                    lx.data.Extraction(
                        extraction_class="opbevaring",
                        extraction_text="Data opbevares i 2 år efter kontraktophør",
                        attributes={
                            "compliance_score": 5,
                            "note": "Klar opbevaringsperiode angivet",
                            "issues": "Ingen"
                        }
                    ),
                    lx.data.Extraction(
                        extraction_class="brugerrettigheder",
                        extraction_text="Du har ret til at få slettet dine data ved henvendelse til privacy@example.com",
                        attributes={
                            "compliance_score": 4,
                            "note": "Sletningsret nævnt med kontaktinfo",
                            "issues": "Andre rettigheder ikke nævnt"
                        }
                    )
                ]
            )
        ]
        
        return examples
    
    def process_langextract_results(self, result, content: str, url: str = None) -> Dict[str, Any]:
        """Process LangExtract results into structured analysis"""
        analysis = {
            'url': url,
            'content_length': len(content),
            'categories': {},
            'overall_score': 0,
            'critical_issues': [],
            'summary': ''
        }
        
        # Group extractions by category
        for extraction in result.extractions:
            category = extraction.extraction_class
            
            if category not in analysis['categories']:
                analysis['categories'][category] = {
                    'findings': [],
                    'score': 0,
                    'issues': []
                }
            
            finding = {
                'text': extraction.extraction_text,
                'attributes': extraction.attributes,
                'position': {
                    'start': getattr(extraction, 'span', {}).get('start', 0) if hasattr(extraction, 'span') and extraction.span else 0,
                    'end': getattr(extraction, 'span', {}).get('end', 0) if hasattr(extraction, 'span') and extraction.span else 0
                }
            }
            
            analysis['categories'][category]['findings'].append(finding)
            
            # Track scores and issues
            if 'compliance_score' in extraction.attributes:
                score = extraction.attributes['compliance_score']
                analysis['categories'][category]['score'] = max(
                    analysis['categories'][category]['score'], score
                )
                
                if score <= 2:
                    analysis['critical_issues'].append({
                        'category': category,
                        'issue': extraction.attributes.get('issues', 'Lav compliance score'),
                        'text': extraction.extraction_text
                    })
        
        # Calculate overall score
        scores = [cat['score'] for cat in analysis['categories'].values() if cat['score'] > 0]
        analysis['overall_score'] = sum(scores) / len(scores) if scores else 0
        
        return analysis

def create_comparison_report(analyses: Dict[str, Dict]) -> pd.DataFrame:
    """Create comparison report from multiple analyses"""
    comparison_data = []
    
    for service_name, analysis_data in analyses.items():
        if not analysis_data.get('success'):
            continue
            
        analysis = analysis_data['analysis']
        
        row = {
            'Service': service_name,
            'URL': analysis.get('url', ''),
            'Overordnet Score': f"{analysis['overall_score']:.1f}/5",
            'Kritiske Problemer': len(analysis['critical_issues']),
            'Analyseret': datetime.fromisoformat(analysis_data['timestamp']).strftime('%d/%m/%Y %H:%M')
        }
        
        # Add category scores
        for cat_key, cat_info in st.session_state.gdpr_categories.items():
            if cat_key in analysis['categories']:
                score = analysis['categories'][cat_key]['score']
                row[cat_info['name']] = f"{score}/5" if score > 0 else "Ikke fundet"
            else:
                row[cat_info['name']] = "Ikke fundet"
        
        comparison_data.append(row)
    
    return pd.DataFrame(comparison_data)

def generate_pdf_report(analyses: Dict[str, Dict], output_path: str):
    """Generate PDF report from analyses"""
    if not REPORTLAB_AVAILABLE:
        raise ImportError("ReportLab is required for PDF generation")
        
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        textColor=colors.darkblue
    )
    story.append(Paragraph("GDPR Compliance Analyse Rapport", title_style))
    story.append(Spacer(1, 12))
    
    # Summary
    story.append(Paragraph("Sammendrag", styles['Heading2']))
    summary_text = f"Analyseret {len(analyses)} services den {datetime.now().strftime('%d. %B %Y')}"
    story.append(Paragraph(summary_text, styles['Normal']))
    story.append(Spacer(1, 12))
    
    # Individual analyses
    for service_name, analysis_data in analyses.items():
        if not analysis_data.get('success'):
            continue
            
        analysis = analysis_data['analysis']
        
        story.append(Paragraph(f"Analyse af {service_name}", styles['Heading2']))
        story.append(Paragraph(f"URL: {analysis.get('url', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"Overordnet score: {analysis['overall_score']:.1f}/5", styles['Normal']))
        
        if analysis['critical_issues']:
            story.append(Paragraph("Kritiske problemer:", styles['Heading3']))
            for issue in analysis['critical_issues']:
                story.append(Paragraph(f"• {issue['category']}: {issue['issue']}", styles['Normal']))
        
        story.append(Spacer(1, 12))
    
    doc.build(story)

def show():
    """Display the tekstanalyse page"""
    st.title("T&A Tekstanalyse 🔍")
    
    st.markdown("""
    **GDPR og privatlivspolitik analysator**
    
    Dette værktøj analyserer Terms of Service og privatlivspolitikker for at identificere GDPR compliance-problemer 
    og sammenligne forskellige services' tilgang til databeskyttelse.
    """)
    
    # Check for required dependencies
    missing_deps = []
    if not LANGEXTRACT_AVAILABLE:
        missing_deps.append("langextract")
    if not BEAUTIFULSOUP_AVAILABLE:
        missing_deps.append("beautifulsoup4 (anbefalet til bedre web scraping)")
    if not SELENIUM_AVAILABLE:
        missing_deps.append("selenium + webdriver-manager (valgfrit for JavaScript sider)")
    if not REPORTLAB_AVAILABLE:
        missing_deps.append("reportlab (til PDF eksport)")
    if not SCHEDULE_AVAILABLE:
        missing_deps.append("schedule (til overvågning)")
    
    if missing_deps:
        st.warning(f"""
        ⚠️ **Manglende pakker**: 
        
        {chr(10).join(f'• {dep}' for dep in missing_deps)}
        
        **Hurtig installation:**
        ```
        pip install langextract beautifulsoup4 reportlab schedule selenium webdriver-manager
        ```
        """)
        
        if not LANGEXTRACT_AVAILABLE:
            st.error("❌ LangExtract er påkrævet for tekstanalyse. Installér med: `pip install langextract`")
            st.info("LangExtract kræver også en AI API key (OpenAI, Anthropic, Mistral eller Google)")
            return
    
    # Model selection sidebar
    with st.sidebar:
        st.header("🤖 AI Model Konfiguration")
        
        # Available providers
        providers = []
        if OPENAI_AVAILABLE:
            providers.append("OpenAI")
        if ANTHROPIC_AVAILABLE:
            providers.append("Anthropic")
        if MISTRAL_AVAILABLE:
            providers.append("Mistral")
        providers.append("Google Gemini")
        
        if not providers:
            st.error("⚠️ Ingen AI modeller tilgængelige. Installer nødvendige pakker.")
            return
        
        llm_provider = st.selectbox("Vælg AI Udbyder", providers)
        
        # Model selection based on provider
        if llm_provider == "OpenAI":
            model_options = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]  # gpt-4o-mini først for bedre stabilitet
            try:
                api_key = st.secrets["model_keys"]["openai_api_key"]
                st.success("✅ OpenAI API key hentet fra secrets")
            except KeyError:
                st.error("❌ OpenAI API key ikke fundet i secrets.toml")
                api_key = st.text_input("OpenAI API Key", type="password", help="Indtast din API key manuelt")
        elif llm_provider == "Anthropic":
            model_options = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
            st.warning("⚠️ LangExtract understøtter ikke Anthropic direkte. Vælg Google Gemini eller OpenAI i stedet.")
            api_key = None
        elif llm_provider == "Mistral":
            model_options = ["mistral-large-latest", "mistral-medium-latest"]
            st.warning("⚠️ LangExtract understøtter ikke Mistral direkte. Vælg Google Gemini eller OpenAI i stedet.")
            api_key = None
        else:  # Google Gemini
            model_options = ["gemini-2.5-flash", "gemini-2.5-pro"]
            try:
                api_key = st.secrets["model_keys"]["google_api_key"]
                st.success("✅ Google API key hentet fra secrets")
            except KeyError:
                st.error("❌ Google API key ikke fundet i secrets.toml")
                api_key = st.text_input("Google API Key", type="password", help="Indtast din API key manuelt")
        
        selected_model = st.selectbox("Vælg Model", model_options)
        
        # Analysis settings
        st.subheader("Analyse Indstillinger")
        enable_monitoring = st.checkbox("Aktivér overvågning", 
                                       help="Tjek ugentligt for opdateringer") if SCHEDULE_AVAILABLE else False
        
        if enable_monitoring:
            email_notifications = st.text_input("Email til notifikationer",
                                               help="Modtag email ved ændringer")
    
    # Main tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📄 Analyser Dokumenter", 
        "📊 Sammenlign Services", 
        "⚙️ Konfiguration", 
        "📚 Hjælp"
    ])
    
    with tab1:
        st.header("Analysér GDPR Compliance")
        
        if not LANGEXTRACT_AVAILABLE:
            st.error("LangExtract skal installeres for at analysere dokumenter.")
            st.code("pip install langextract")
            return
        
        if not api_key:
            st.warning("⚠️ Indtast din API key i sidebaren for at fortsætte")
            return
        
        # Input methods
        input_method = st.radio(
            "Vælg input metode:",
            ["URL Links", "Upload PDF/Tekst", "Direkte Tekst"],
            horizontal=True
        )
        
        analysis_data = None
        
        if input_method == "URL Links":
            st.subheader("🌐 Analysér fra URLs")
            
            # Single URL input
            single_url = st.text_input("Enkelt URL:", placeholder="https://example.com/privacy-policy")
            
            if st.button("🔍 Analysér Enkelt URL") and single_url:
                with st.spinner("Henter og analyserer indhold..."):
                    scraper = WebScraper()
                    scrape_result = scraper.scrape_url(single_url)
                    
                    if scrape_result['success']:
                        analyzer = GDPRAnalyzer(llm_provider, selected_model, api_key)
                        analysis_result = analyzer.analyze_document(
                            scrape_result['content'], 
                            single_url
                        )
                        
                        if analysis_result['success']:
                            st.session_state.analyzed_documents[single_url] = analysis_result
                            analysis_data = analysis_result
                            st.success("✅ Analyse gennemført!")
                        else:
                            st.error(f"Analyse fejlede: {analysis_result['error']}")
                    else:
                        st.error(f"Kunne ikke hente indhold: {scrape_result['error']}")
            
            # Batch URL processing
            st.markdown("---")
            st.subheader("📦 Batch Analyse")
            
            batch_urls = st.text_area(
                "Indsæt flere URLs (en per linje):",
                height=150,
                placeholder="https://example1.com/privacy\nhttps://example2.com/terms\nhttps://example3.com/cookies"
            )
            
            if st.button("🚀 Start Batch Analyse") and batch_urls:
                urls = [url.strip() for url in batch_urls.split('\n') if url.strip()]
                
                if len(urls) > 50:
                    st.error("Maksimalt 50 URLs ad gangen")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    scraper = WebScraper()
                    analyzer = GDPRAnalyzer(llm_provider, selected_model, api_key)
                    
                    for i, url in enumerate(urls):
                        status_text.text(f"Behandler {url}... ({i+1}/{len(urls)})")
                        
                        # Scrape content
                        scrape_result = scraper.scrape_url(url)
                        
                        if scrape_result['success']:
                            # Analyze content
                            analysis_result = analyzer.analyze_document(
                                scrape_result['content'], 
                                url
                            )
                            
                            if analysis_result['success']:
                                st.session_state.analyzed_documents[url] = analysis_result
                            else:
                                st.warning(f"Analyse af {url} fejlede: {analysis_result['error']}")
                        else:
                            st.warning(f"Kunne ikke hente {url}: {scrape_result['error']}")
                        
                        progress_bar.progress((i + 1) / len(urls))
                        time.sleep(1)  # Rate limiting
                    
                    status_text.text(f"Færdig! Analyseret {len(st.session_state.analyzed_documents)} dokumenter")
                    progress_bar.empty()
                    time.sleep(2)
                    status_text.empty()
        
        elif input_method == "Upload PDF/Tekst":
            st.subheader("📁 Upload Dokumenter")
            
            uploaded_files = st.file_uploader(
                "Vælg PDF eller tekstfiler:",
                type=['pdf', 'txt', 'md'],
                accept_multiple_files=True
            )
            
            if uploaded_files and st.button("📄 Analysér Uploadede Filer"):
                analyzer = GDPRAnalyzer(llm_provider, selected_model, api_key)
                
                for uploaded_file in uploaded_files:
                    with st.spinner(f"Analyserer {uploaded_file.name}..."):
                        # Extract text from file
                        if uploaded_file.type == "application/pdf":
                            # PDF handling would go here - placeholder for now
                            st.warning(f"PDF parsing ikke implementeret endnu for {uploaded_file.name}")
                            continue
                        else:
                            content = str(uploaded_file.read(), "utf-8")
                        
                        analysis_result = analyzer.analyze_document(content, uploaded_file.name)
                        
                        if analysis_result['success']:
                            st.session_state.analyzed_documents[uploaded_file.name] = analysis_result
                            st.success(f"✅ {uploaded_file.name} analyseret!")
                        else:
                            st.error(f"Analyse af {uploaded_file.name} fejlede: {analysis_result['error']}")
        
        elif input_method == "Direkte Tekst":
            st.subheader("✏️ Indtast Tekst Direkte")
            
            direct_text = st.text_area(
                "Indtast privatlivspolitik eller terms of service:",
                height=300,
                placeholder="Indsæt teksten her..."
            )
            
            document_name = st.text_input("Navn på dokument:", placeholder="Eksempel Service")
            
            if st.button("🔍 Analysér Tekst") and direct_text and document_name:
                with st.spinner("Analyserer tekst..."):
                    analyzer = GDPRAnalyzer(llm_provider, selected_model, api_key)
                    analysis_result = analyzer.analyze_document(direct_text, document_name)
                    
                    if analysis_result['success']:
                        st.session_state.analyzed_documents[document_name] = analysis_result
                        analysis_data = analysis_result
                        st.success("✅ Analyse gennemført!")
                    else:
                        st.error(f"Analyse fejlede: {analysis_result['error']}")
        
        # Display single analysis results
        if analysis_data and analysis_data['success']:
            st.markdown("---")
            st.header("📊 Analyse Resultater")
            
            analysis = analysis_data['analysis']
            
            # Overview metrics
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Overordnet Score", f"{analysis['overall_score']:.1f}/5")
            col2.metric("Kategorier Fundet", len(analysis['categories']))
            col3.metric("Kritiske Problemer", len(analysis['critical_issues']))
            col4.metric("Indhold Længde", f"{analysis['content_length']:,} tegn")
            
            # Critical issues
            if analysis['critical_issues']:
                st.subheader("🚨 Kritiske Problemer")
                for issue in analysis['critical_issues']:
                    st.error(f"**{issue['category']}**: {issue['issue']}")
            
            # Category details
            st.subheader("📋 Detaljerede Resultater")
            
            for category_key, findings in analysis['categories'].items():
                category_info = st.session_state.gdpr_categories.get(category_key, {})
                category_name = category_info.get('name', category_key)
                
                with st.expander(f"{category_name} (Score: {findings['score']}/5)", expanded=True):
                    for finding in findings['findings']:
                        st.markdown(f"""
                        **Citeret tekst**: "{finding['text']}"
                        
                        **Compliance score**: {finding['attributes'].get('compliance_score', 'N/A')}/5
                        
                        **Note**: {finding['attributes'].get('note', 'Ingen note')}
                        
                        **Position**: Tegn {finding['position']['start']}-{finding['position']['end']}
                        """)
                        
                        if finding['attributes'].get('issues') != 'Ingen':
                            st.warning(f"**Problem**: {finding['attributes'].get('issues')}")
                        
                        st.markdown("---")
    
    with tab2:
        st.header("📊 Sammenlign Services")
        
        if not st.session_state.analyzed_documents:
            st.info("🔍 Analysér først nogle dokumenter i 'Analyser Dokumenter' fanen for at sammenligne dem her.")
        else:
            # Display comparison table
            st.subheader("📋 Sammenligningstabel")
            
            comparison_df = create_comparison_report(st.session_state.analyzed_documents)
            
            if not comparison_df.empty:
                st.dataframe(comparison_df, use_container_width=True)
                
                # Export options
                st.subheader("💾 Eksportér Resultater")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    # Excel export
                    excel_buffer = BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        comparison_df.to_excel(writer, sheet_name='GDPR Sammenligning', index=False)
                        
                        # Add detailed sheets for each service
                        for service_name, analysis_data in st.session_state.analyzed_documents.items():
                            if analysis_data.get('success'):
                                analysis = analysis_data['analysis']
                                detailed_data = []
                                
                                for cat_key, findings in analysis['categories'].items():
                                    cat_info = st.session_state.gdpr_categories.get(cat_key, {})
                                    for finding in findings['findings']:
                                        detailed_data.append({
                                            'Kategori': cat_info.get('name', cat_key),
                                            'Citeret Tekst': finding['text'],
                                            'Compliance Score': finding['attributes'].get('compliance_score', ''),
                                            'Note': finding['attributes'].get('note', ''),
                                            'Problemer': finding['attributes'].get('issues', ''),
                                            'Position Start': finding['position']['start'],
                                            'Position End': finding['position']['end']
                                        })
                                
                                if detailed_data:
                                    detail_df = pd.DataFrame(detailed_data)
                                    sheet_name = service_name[:31]  # Excel sheet name limit
                                    detail_df.to_excel(writer, sheet_name=sheet_name, index=False)
                    
                    excel_buffer.seek(0)
                    
                    st.download_button(
                        "📊 Download Excel Rapport",
                        data=excel_buffer.getvalue(),
                        file_name=f"gdpr_analyse_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                
                with col2:
                    # PDF export
                    if REPORTLAB_AVAILABLE:
                        if st.button("📄 Generér PDF Rapport"):
                            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                                generate_pdf_report(st.session_state.analyzed_documents, tmp_file.name)
                                
                                with open(tmp_file.name, 'rb') as pdf_file:
                                    pdf_data = pdf_file.read()
                                
                                st.download_button(
                                    "📄 Download PDF Rapport",
                                    data=pdf_data,
                                    file_name=f"gdpr_rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                    mime="application/pdf"
                                )
                    else:
                        st.info("📄 PDF eksport kræver 'reportlab' pakken")
                
                with col3:
                    # JSON export
                    json_data = {
                        'export_timestamp': datetime.now().isoformat(),
                        'analyses': st.session_state.analyzed_documents,
                        'categories': st.session_state.gdpr_categories,
                        'scoring_criteria': st.session_state.scoring_criteria
                    }
                    
                    st.download_button(
                        "📋 Download JSON Data",
                        data=json.dumps(json_data, indent=2, ensure_ascii=False),
                        file_name=f"gdpr_data_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                        mime="application/json"
                    )
                
                # Side-by-side comparison
                st.subheader("🔄 Side-ved-side sammenligning")
                
                if len(st.session_state.analyzed_documents) >= 2:
                    service_names = list(st.session_state.analyzed_documents.keys())
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        service1 = st.selectbox("Vælg første service:", service_names, key="compare1")
                    
                    with col2:
                        service2 = st.selectbox("Vælg anden service:", 
                                               [name for name in service_names if name != service1], 
                                               key="compare2")
                    
                    if st.button("🔍 Sammenlign Services"):
                        analysis1 = st.session_state.analyzed_documents[service1]['analysis']
                        analysis2 = st.session_state.analyzed_documents[service2]['analysis']
                        
                        # Comparison overview
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.subheader(f"📊 {service1}")
                            st.metric("Overordnet Score", f"{analysis1['overall_score']:.1f}/5")
                            st.metric("Kritiske Problemer", len(analysis1['critical_issues']))
                            
                            if analysis1['critical_issues']:
                                st.write("🚨 **Kritiske problemer:**")
                                for issue in analysis1['critical_issues']:
                                    st.write(f"• {issue['issue']}")
                        
                        with col2:
                            st.subheader(f"📊 {service2}")
                            st.metric("Overordnet Score", f"{analysis2['overall_score']:.1f}/5")
                            st.metric("Kritiske Problemer", len(analysis2['critical_issues']))
                            
                            if analysis2['critical_issues']:
                                st.write("🚨 **Kritiske problemer:**")
                                for issue in analysis2['critical_issues']:
                                    st.write(f"• {issue['issue']}")
                        
                        # Category comparison
                        st.subheader("📋 Kategori Sammenligning")
                        
                        for cat_key, cat_info in st.session_state.gdpr_categories.items():
                            cat_name = cat_info['name']
                            
                            score1 = analysis1['categories'].get(cat_key, {}).get('score', 0)
                            score2 = analysis2['categories'].get(cat_key, {}).get('score', 0)
                            
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.metric(f"{cat_name} - {service1}", f"{score1}/5")
                            
                            with col2:
                                st.metric(f"{cat_name} - {service2}", f"{score2}/5")
                            
                            # Show difference
                            if score1 != score2:
                                if score1 > score2:
                                    st.success(f"✅ {service1} scorer bedre ({score1-score2} point højere)")
                                else:
                                    st.success(f"✅ {service2} scorer bedre ({score2-score1} point højere)")
                else:
                    st.info("Analysér mindst 2 services for at sammenligne dem side ved side.")
            
            # Clear all analyses
            if st.button("🗑️ Ryd Alle Analyser", type="secondary"):
                st.session_state.analyzed_documents = {}
                st.success("Alle analyser ryddet!")
                st.rerun()
    
    with tab3:
        st.header("⚙️ Konfiguration")
        st.info("Konfiguration kommer i næste version - brug standard GDPR kategorier for nu.")
        
    with tab4:
        st.header("📚 Hjælp og Dokumentation")
        
        with st.expander("🎯 Hvordan bruger jeg værktøjet?", expanded=True):
            st.markdown("""
            **Trin 1: Installér nødvendige pakker**
            ```bash
            pip install langextract beautifulsoup4 reportlab schedule
            ```
            
            **Trin 2: Konfigurér AI Model**
            1. Vælg din foretrukne AI udbyder i sidebaren
            2. Indtast din API key
            3. Vælg den ønskede model
            
            **Trin 3: Analysér Dokumenter**
            1. Gå til 'Analyser Dokumenter' fanen
            2. Vælg input metode (URL, upload, eller direkte tekst)
            3. Start analysen
            
            **Trin 4: Sammenlign Resultater**
            1. Gå til 'Sammenlign Services' fanen
            2. Se sammenligningstabellen
            3. Eksportér resultater til Excel/PDF
            """)
        
        with st.expander("🔍 Hvilke GDPR områder analyseres?"):
            for cat_key, cat_info in st.session_state.gdpr_categories.items():
                st.markdown(f"""
                **{cat_info['name']}**
                - *Beskrivelse*: {cat_info['description']}
                - *Søgeord*: {', '.join(cat_info['keywords'])}
                """)
        
        with st.expander("⚖️ Hvordan fungerer scoring?"):
            st.markdown("""
            **Compliance Score (1-5 skala):**
            - **5**: Fremragende - Opfylder fuldt GDPR kravene
            - **4**: God - Opfylder de fleste krav med mindre mangler
            - **3**: Acceptabel - Opfylder grundlæggende krav
            - **2**: Problematisk - Væsentlige mangler
            - **1**: Kritisk - Alvorlige GDPR overtredelser
            """)
        
        with st.expander("🌐 Web Scraping og Tekniske Detaljer"):
            st.markdown(f"""
            **Hybrid Web Scraping:**
            - Først forsøg med `requests` (hurtig)
            - Fallback til `selenium` hvis JavaScript er nødvendigt {'✅' if SELENIUM_AVAILABLE else '❌ Ikke installeret'}
            - BeautifulSoup til HTML parsing {'✅' if BEAUTIFULSOUP_AVAILABLE else '❌ Ikke installeret'}
            - Automatisk tekst-rensning og formatering
            
            **AI Model Support:**
            - **OpenAI**: GPT-4o, GPT-4o-mini, GPT-4-turbo {'✅' if OPENAI_AVAILABLE else '❌ Ikke installeret'}
            - **Anthropic**: Claude 3.5 Sonnet, Claude 3.5 Haiku {'✅' if ANTHROPIC_AVAILABLE else '❌ Ikke installeret'}
            - **Mistral**: Mistral Large, Mistral Medium {'✅' if MISTRAL_AVAILABLE else '❌ Ikke installeret'}
            - **Google**: Gemini 2.5 Flash, Gemini 2.5 Pro ✅
            
            **LangExtract**: {'✅ Installeret' if LANGEXTRACT_AVAILABLE else '❌ Ikke installeret - PÅKRÆVET'}
            """)
        
        with st.expander("📋 API Keys og Opsætning"):
            st.markdown("""
            **Sådan får du API keys:**
            
            **Google Gemini (anbefalet til start):**
            1. Gå til [Google AI Studio](https://makersuite.google.com/app/apikey)
            2. Log ind med Google konto
            3. Opret ny API key
            4. Kopier key til værktøjet
            
            **OpenAI:**
            1. Gå til [OpenAI Platform](https://platform.openai.com/)
            2. Opret konto og log ind
            3. Gå til API Keys sektionen
            4. Opret ny API key
            
            **Anthropic (Claude):**
            1. Gå til [Anthropic Console](https://console.anthropic.com/)
            2. Opret konto og log ind
            3. Naviger til API Keys
            4. Generér ny key
            
            **Mistral:**
            1. Gå til [Mistral Platform](https://console.mistral.ai/)
            2. Opret konto og gå til API sektionen
            3. Opret API key
            """)
        
        with st.expander("⚠️ Begrænsninger og Ansvarsfraskrivelse"):
            st.markdown("""
            **Vigtige begrænsninger:**
            
            ⚠️ **Dette værktøj er kun vejledende** og erstatter ikke juridisk rådgivning
            
            ⚠️ **AI-baseret analyse** kan indeholde fejl eller misfortolkninger
            
            ⚠️ **GDPR compliance** kræver menneskelig juridisk vurdering
            
            ⚠️ **Verificér altid resultater** med juridisk ekspertise
            
            **Anbefalet brug:**
            - Som første screening af privatlivspolitikker
            - Til identifikation af potentielle problemer
            - Som forberedelse til juridisk gennemgang
            - Til sammenligning af konkurrenters praksis
            """)
        
        # Technical requirements
        st.subheader("🔧 Tekniske Krav og Status")
        
        requirements_status = [
            ('langextract', 'LangExtract (Google) - PÅKRÆVET', LANGEXTRACT_AVAILABLE),
            ('beautifulsoup4', 'Web scraping forbedringer', BEAUTIFULSOUP_AVAILABLE),
            ('selenium + webdriver-manager', 'JavaScript scraping (valgfrit)', SELENIUM_AVAILABLE),
            ('reportlab', 'PDF generering', REPORTLAB_AVAILABLE),
            ('schedule', 'Overvågning funktioner', SCHEDULE_AVAILABLE),
            ('pandas', 'Data behandling', True),  # Should always be available via streamlit
            ('requests', 'HTTP requests', True),  # Should always be available
        ]
        
        for package, desc, available in requirements_status:
            status_icon = "✅" if available else "❌"
            st.write(f"{status_icon} **{package}**: {desc}")
        
        missing_packages = [pkg for pkg, _, avail in requirements_status if not avail]
        
        if missing_packages:
            st.error(f"⚠️ Manglende pakker: {', '.join(missing_packages)}")
            st.code(f"pip install {' '.join(missing_packages)}")
        else:
            st.success("✅ Alle pakker er installeret!")

def check_for_updates():
    """Background function to check for document updates"""
    # This function would be called by a scheduler
    # Implementation for periodic monitoring
    pass

# Main execution
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()