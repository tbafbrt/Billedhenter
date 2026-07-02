import os
import base64

import requests
import streamlit as st
from auth import AuthManager

# Import API clients. Fanger den fulde fejl (ikke kun ImportError), så vi kan
# vise præcist hvorfor en udbyder mangler i deployment — fx en gammel mistralai
# 0.x uden `Mistral`-klassen.
IMPORT_ERRORS = {}

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception as e:
    OPENAI_AVAILABLE = False
    IMPORT_ERRORS["openai"] = str(e)

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except Exception as e:
    ANTHROPIC_AVAILABLE = False
    IMPORT_ERRORS["anthropic"] = str(e)

# Mistral kaldes via REST (requests) i stedet for mistralai-SDK'et: deployment
# endte med inkompatible SDK-versioner, hvor hverken `Mistral` eller
# `MistralClient` kunne importeres. API'et er OpenAI-kompatibelt, og requests er
# altid installeret — så Mistral er altid tilgængelig.
MISTRAL_AVAILABLE = True
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Fix for inotify watch limit reached error
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

st.set_page_config(page_title="T&R Værktøjer - TænkGPT Chatbot", page_icon="💬", layout="wide")

MAX_TOKENS = 4096
GREETING = {"role": "assistant", "content": "Hej der! Jeg er din chatbot. Hvad kan jeg hjælpe dig med?"}
SYSTEM_PROMPT = (
    "Du er en hjælpsom assistent for medarbejdere i Forbrugerrådet Tænk. "
    "Svar klart og præcist på dansk, medmindre brugeren skriver på et andet sprog."
)

# Model-register: model-id -> udbyder + pris (input/output pr. mio. tokens).
# Claude-modellerne er de aktuelle (de gamle claude-3-* er udgået og fejler).
MODELS = {
    # Mistral (-latest-aliaser auto-opdaterer til nyeste version)
    "mistral-large-latest":  {"provider": "mistral",   "price": "$8/$24"},
    "mistral-medium-latest": {"provider": "mistral",   "price": "$2.5/$7.5"},
    # Anthropic Claude
    "claude-haiku-4-5":      {"provider": "anthropic", "price": "$1/$5"},
    "claude-sonnet-4-6":     {"provider": "anthropic", "price": "$3/$15"},
    "claude-opus-4-8":       {"provider": "anthropic", "price": "$5/$25"},
    # OpenAI
    "gpt-4o-mini":           {"provider": "openai",    "price": "$1/$3"},
    "gpt-4.1-nano":          {"provider": "openai",    "price": "$1/$5"},
    "gpt-4o":                {"provider": "openai",    "price": "$5/$15"},
    "gpt-4.1-mini":          {"provider": "openai",    "price": "$5/$15"},
    "gpt-4.1":               {"provider": "openai",    "price": "$10/$30"},
}

# Hvilke udbydere kan hvad med vedhæftninger
DOC_SUPPORT = {
    "anthropic": {"text", "image", "pdf"},
    "openai":    {"text", "image"},
    "mistral":   {"text"},
}


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def init_session_state():
    defaults = {
        "logged_in": False,
        "current_page": "chatbot",
        "messages": [dict(GREETING)],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# Modeller
# ---------------------------------------------------------------------------
def get_available_models():
    """Modeller hvis udbyder-pakke er installeret, i rækkefølgen Mistral → Claude → OpenAI."""
    available = {"mistral": MISTRAL_AVAILABLE, "anthropic": ANTHROPIC_AVAILABLE, "openai": OPENAI_AVAILABLE}
    return [m for m, info in MODELS.items() if available.get(info["provider"])]


def format_model(model):
    return f"{model} ({MODELS[model]['price']})"


# ---------------------------------------------------------------------------
# Vedhæftninger
# ---------------------------------------------------------------------------
def read_attachment(uploaded_file):
    """Læs en uploadet fil til en attachment-dict, eller None."""
    if not uploaded_file:
        return None
    raw = uploaded_file.getvalue()
    ext = uploaded_file.name.lower().rsplit(".", 1)[-1]
    if ext in ("txt", "md", "csv"):
        return {"kind": "text", "name": uploaded_file.name, "text": raw.decode("utf-8", "replace")}
    if ext == "pdf":
        return {"kind": "pdf", "name": uploaded_file.name,
                "b64": base64.b64encode(raw).decode(), "mime": "application/pdf"}
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/jpeg")
    return {"kind": "image", "name": uploaded_file.name,
            "b64": base64.b64encode(raw).decode(), "mime": mime}


def api_history(messages):
    """Historik til API'et: drop den indledende assistant-hilsen (Claude kræver at samtalen starter med user)."""
    msgs = list(messages)
    if msgs and msgs[0]["role"] == "assistant":
        msgs = msgs[1:]
    return msgs


# ---------------------------------------------------------------------------
# Byg provider-specifikke beskeder
# ---------------------------------------------------------------------------
def build_claude_messages(history, attachment):
    out = []
    for i, m in enumerate(history):
        last = i == len(history) - 1
        if last and m["role"] == "user" and attachment:
            blocks = []
            if attachment["kind"] == "pdf":
                blocks.append({"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf", "data": attachment["b64"]}})
            elif attachment["kind"] == "image":
                blocks.append({"type": "image", "source": {
                    "type": "base64", "media_type": attachment["mime"], "data": attachment["b64"]}})
            elif attachment["kind"] == "text":
                blocks.append({"type": "text",
                               "text": f"Vedhæftet dokument ({attachment['name']}):\n\n{attachment['text']}"})
            blocks.append({"type": "text", "text": m["content"]})
            out.append({"role": "user", "content": blocks})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def build_openai_messages(history, attachment):
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for i, m in enumerate(history):
        last = i == len(history) - 1
        if last and m["role"] == "user" and attachment and attachment["kind"] == "image":
            out.append({"role": "user", "content": [
                {"type": "text", "text": m["content"]},
                {"type": "image_url", "image_url": {"url": f"data:{attachment['mime']};base64,{attachment['b64']}"}},
            ]})
        elif last and m["role"] == "user" and attachment and attachment["kind"] == "text":
            out.append({"role": "user",
                        "content": f"Vedhæftet dokument ({attachment['name']}):\n\n{attachment['text']}\n\n{m['content']}"})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def build_mistral_messages(history, attachment):
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for i, m in enumerate(history):
        last = i == len(history) - 1
        if last and m["role"] == "user" and attachment and attachment["kind"] == "text":
            out.append({"role": "user",
                        "content": f"Vedhæftet dokument ({attachment['name']}):\n\n{attachment['text']}\n\n{m['content']}"})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


# ---------------------------------------------------------------------------
# Streaming-generatorer (yield tekst-bidder → st.write_stream)
# ---------------------------------------------------------------------------
def stream_claude(model, messages):
    client = Anthropic(api_key=st.secrets["model_keys"]["anthropic_api_key"])
    with client.messages.stream(
        model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, messages=messages
    ) as stream:
        for text in stream.text_stream:
            yield text


def stream_openai(model, messages):
    client = OpenAI(api_key=st.secrets["model_keys"]["openai_api_key"])
    response = client.chat.completions.create(model=model, messages=messages, stream=True)
    for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def stream_mistral(model, messages):
    api_key = st.secrets["model_keys"]["mistral_api_key"]
    response = requests.post(
        MISTRAL_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages},
        timeout=60,
    )
    response.raise_for_status()
    yield response.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def render_intro(available_models):
    st.title("T&R TænkGPT Chatbot 💬")
    st.markdown(
        "Det er din nye chatbot! Hvis du nogensinde har undret dig over hvad GPT står for, "
        "så er det Gitte Peter Thomas."
    )
    st.markdown(
        f"""
        På denne side kan du chatte med **{len(available_models)} forskellige sprogmodeller** fra
        OpenAI, Anthropic og Mistral. Den fungerer nogenlunde som når du logger ind på ChatGPT,
        Claude eller Mistral. Du kan også **vedhæfte et dokument** (PDF, billede eller tekst) og
        få modellen til at analysere det.

        I model-menuen står prisen som *(input / output per million tokens)* — det behøver du ikke
        tænke så meget over; de er alle billige. Det er mest en indikation af hvor avanceret modellen
        er. Til det meste behøver man ikke den mest avancerede.
        """
    )


def render_model_help():
    with st.expander("Fold ud for en kort forklaring om de enkelte modeller", expanded=False):
        st.markdown(
            """
            ##### Fra Mistral AI (fransk — støt europæiske produkter 🙂)
            - **Mistral Large**: Nyeste ræsonneringsmodel til opgaver med høj kompleksitet.
            - **Mistral Medium**: Nyeste version af den billigere Mistral-model.

            ##### Fra Anthropic (Claude)
            - **Claude Haiku 4.5**: Hurtig og økonomisk — oplagt til hurtige svar på almindelige spørgsmål.
            - **Claude Sonnet 4.6**: God balance mellem hastighed og dybde til de fleste opgaver.
            - **Claude Opus 4.8**: Anthropics mest kapable model til de mest krævende opgaver.

            ##### Fra OpenAI
            - **GPT-4o Mini / GPT-4.1 Nano**: Hurtige, økonomiske modeller til enkle opgaver.
            - **GPT-4o / GPT-4.1 Mini**: Solide standardmodeller til de fleste opgaver.
            - **GPT-4.1**: Den smarteste til komplekse opgaver.
            """
        )


def show():
    # Centrér og afgræns både hovedkolonnen OG den nederste chat-input-container,
    # så tekstfeltet ikke fylder hele bunden. Chat-inputtet bor i en separat
    # bund-container (stBottom), som ikke rammes af .block-container alene.
    st.markdown(
        """
        <style>
        .block-container { max-width: 820px; margin: 0 auto; padding-top: 2.5rem; }
        [data-testid="stBottomBlockContainer"] { max-width: 820px; margin: 0 auto; }
        [data-testid="stBottom"] > div { max-width: 820px; margin: 0 auto; }
        .stChatFloatingInputContainer { max-width: 820px; margin: 0 auto; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Tjek pakker og API-nøgler
    missing = [name for name, ok in
               [("openai", OPENAI_AVAILABLE), ("anthropic", ANTHROPIC_AVAILABLE), ("mistralai", MISTRAL_AVAILABLE)]
               if not ok]
    if missing:
        st.warning(f"⚠️ Følgende udbydere er ikke tilgængelige: {', '.join(missing)}")
        for pkg in missing:
            reason = IMPORT_ERRORS.get(pkg)
            if reason:
                st.caption(f"`{pkg}`: {reason}")
        st.info(f"Tjek at pakkerne er installeret: `pip install {' '.join(missing)}`")

    if "model_keys" not in st.secrets:
        st.error("❌ API-nøgler er ikke konfigureret. Tilføj dem i secrets.toml under [model_keys].")
        return

    available_models = get_available_models()
    if not available_models:
        st.error("❌ Ingen modeller tilgængelige. Installer pakkerne og konfigurer API-nøgler.")
        return

    render_intro(available_models)

    st.subheader("Vælg din foretrukne sprogmodel 🚀")
    render_model_help()

    selected_model = st.selectbox(
        "Vælg model:", options=available_models, format_func=format_model
    )
    provider = MODELS[selected_model]["provider"]

    uploaded_file = st.file_uploader(
        "📎 Vedhæft et dokument (valgfrit) — gælder dit næste spørgsmål",
        type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md", "csv"],
    )
    attachment = read_attachment(uploaded_file)

    # Vis chat-historik
    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("Skriv dit spørgsmål her... Lav linjeskift med shift+enter."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
            if attachment:
                st.caption(f"📎 {attachment['name']}")

        # Kan den valgte model håndtere vedhæftningen?
        attachment_for_call = attachment
        if attachment and attachment["kind"] not in DOC_SUPPORT[provider]:
            if attachment["kind"] == "pdf":
                st.warning("📄 PDF understøttes kun af Claude-modellerne. Vælg en Claude-model, "
                           "eller upload teksten som .txt.")
            elif attachment["kind"] == "image":
                st.warning("🖼️ Billeder understøttes ikke af den valgte model. Vælg en Claude- eller GPT-model.")
            attachment_for_call = None

        history = api_history(st.session_state.messages)

        try:
            with st.chat_message("assistant"):
                if provider == "anthropic":
                    messages = build_claude_messages(history, attachment_for_call)
                    full = st.write_stream(stream_claude(selected_model, messages))
                elif provider == "openai":
                    messages = build_openai_messages(history, attachment_for_call)
                    full = st.write_stream(stream_openai(selected_model, messages))
                else:  # mistral
                    messages = build_mistral_messages(history, attachment_for_call)
                    full = st.write_stream(stream_mistral(selected_model, messages))
            st.session_state.messages.append({"role": "assistant", "content": full})
        except Exception as e:
            msg = str(e)
            st.error(f"Fejl: {msg}")
            low = msg.lower()
            if "api_key" in low or "unauthorized" in low or "authentication" in low:
                st.warning("🔑 API-nøgle-problem. Tjek nøglerne i secrets.toml.")
            elif "quota" in low or "rate limit" in low:
                st.warning("📊 Rate limit eller kvote overskredet. Prøv igen om lidt.")
            elif "connection" in low or "network" in low:
                st.warning("🌐 Netværksproblem. Tjek din internetforbindelse.")
            else:
                st.info("💡 Prøv en anden model, eller kontakt support.")

    # Kontroller
    st.markdown("---")
    if st.button("🗑️ Ryd chat"):
        st.session_state.messages = [dict(GREETING)]
        st.rerun()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
init_session_state()
auth = AuthManager()

if not st.session_state.logged_in:
    auth.login_screen()
else:
    show()
