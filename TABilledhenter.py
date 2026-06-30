import os
import io
import re
import time
import zipfile
import tempfile
from collections import Counter
from typing import List, Dict, Tuple, Optional

import requests
import pandas as pd
import streamlit as st

# Undgå "inotify watch limit reached" på servere med mange filer
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_RUN_ON_SAVE"] = "false"

# Maks antal billeder pr. ZIP. Holder hukommelse og WebSocket-overførsel
# under Streamlit Cloud-grænserne, så download ikke crasher.
MAX_IMAGES_PER_ZIP = 75
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp")

st.set_page_config(page_title="TA Billedhenter", page_icon="📸", layout="wide")


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def init_session_state():
    defaults = {
        "logged_in": False,
        "jwt_token": None,
        "api_authenticated": False,
        "search_results": None,
        "items": [],            # flad liste over valgbare billeder (én kilde til sandhed)
        "zip_bytes": None,      # færdigpakket ZIP klar til download
        "zip_name": None,
        "zip_signature": None,  # hvilke billeder ZIP'en blev pakket af
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# ICRT API
# ---------------------------------------------------------------------------
class ICRTImageDownloader:
    def __init__(self, jwt_token: Optional[str] = None):
        self.base_url = "https://api.icrt.io"
        self.jwt_token = jwt_token

    def authenticate_api(self, client_id: str, client_key: str) -> Tuple[bool, str]:
        """Autentificér mod ICRT API og hent et JWT-token."""
        try:
            response = requests.post(
                f"{self.base_url}/auth",
                json={"client_id": client_id, "client_key": client_key},
                timeout=30,
            )
            if "Failed" in response.text:
                return False, "Godkendelse mislykkedes. Tjek Client ID og Client Key."
            self.jwt_token = response.text  # token returneres direkte som tekst
            return True, "Godkendelse gennemført!"
        except requests.exceptions.RequestException as e:
            return False, f"Forbindelsesfejl: {e}"

    def query_graphql(self, query: str, variables: dict) -> Tuple[bool, Dict]:
        """Kør en GraphQL-forespørgsel. Returnerer (success, data/fejl)."""
        if not self.jwt_token:
            return False, {"error": "not_authenticated"}
        try:
            response = requests.post(
                f"{self.base_url}/graphql",
                json={"query": query, "variables": variables},
                headers={
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if response.status_code == 401:
                return False, {"error": "jwt_expired"}
            if response.status_code == 200:
                return True, response.json()
            return False, {"error": f"GraphQL-fejl: {response.status_code} - {response.text}"}
        except requests.exceptions.RequestException as e:
            return False, {"error": f"Forbindelsesfejl: {e}"}

    @staticmethod
    def extract_project_code(webkode: str) -> str:
        """Træk projektkoden ud af en webkode (LLDDDDD eller DDDDD)."""
        match = re.match(r"^([A-Z]{2}\d{5}|\d{5})", webkode)
        return match.group(1) if match else ""

    @staticmethod
    def extract_product_code(filename: str) -> str:
        """Træk produktkoden ud af et filnavn."""
        if "_" in filename:
            return filename.split("_")[0].strip().lower()
        if "(" in filename:
            return filename.split("(")[0].strip().lower()
        return filename.strip().lower()

    def search_images_for_codes(self, project_code: str, webkodes: List[str]) -> Optional[Dict]:
        """Find billeder for de angivne webkoder. Returnerer None ved fejl."""
        query = """
        query GetProjectMedia($icrtcode: String!) {
            project(icrtcode: $icrtcode) {
                name
                media { filename image }
            }
        }
        """
        success, response = self.query_graphql(query, {"icrtcode": project_code})

        if not success:
            if response.get("error") == "jwt_expired":
                st.session_state.api_authenticated = False
                st.session_state.jwt_token = None
                st.error("🔑 Din session er udløbet. Log ind igen med dine API-oplysninger.")
            else:
                st.error(f"Kunne ikke hente billeder: {response.get('error', 'Ukendt fejl')}")
            return None

        if "errors" in response:
            st.error(f"GraphQL-fejl: {response['errors']}")
            return None

        project_data = (response.get("data") or {}).get("project")
        if not project_data:
            st.warning(f"Intet projekt fundet med koden: {project_code}")
            return None

        media_files = project_data.get("media", [])
        st.caption(f"📊 Samlet antal billeder i projektet: {len(media_files)}")

        webkode_set = {code.strip().lower() for code in webkodes}
        results: Dict = {"found": {}, "missing": [], "suggestions": {}}

        # Match billeder mod webkoder
        for media in media_files:
            filename = media.get("filename", "")
            image_url = media.get("image", "")
            if not (filename and image_url):
                continue

            product_code = self.extract_product_code(filename)
            if product_code in webkode_set:
                original = next(
                    (w.strip() for w in webkodes if w.strip().lower() == product_code), None
                )
                if original:
                    results["found"].setdefault(original, []).append(
                        {"url": image_url, "filename": filename, "webkode": original}
                    )

        # Find manglende webkoder + foreslå variant-alternativer
        for webkode in webkodes:
            clean = webkode.strip()
            if clean in results["found"]:
                continue
            results["missing"].append(clean)

            parts = clean.split("-")
            if len(parts) < 3:
                continue
            base_product = "-".join(parts[:-1]).lower()

            suggestions = []
            for media in media_files:
                filename = media.get("filename", "")
                if not filename:
                    continue
                product_code = self.extract_product_code(filename)
                file_parts = product_code.split("-")
                if len(file_parts) < 3:
                    continue
                if "-".join(file_parts[:-1]) == base_product and product_code != clean.lower():
                    suggestions.append(
                        {
                            "url": media.get("image", ""),
                            "filename": filename,
                            "webkode": product_code,
                            "original_webkode": clean,
                        }
                    )
            if suggestions:
                results["suggestions"][clean] = suggestions

        found_images = sum(len(v) for v in results["found"].values())
        st.success(
            f"🎯 Søgning afsluttet: {found_images} billeder til {len(results['found'])} webkoder"
        )
        return results


# ---------------------------------------------------------------------------
# Input-parsing
# ---------------------------------------------------------------------------
def parse_excel_file(uploaded_file) -> Tuple[Optional[List[str]], Optional[str]]:
    """Læs webkoder fra et prisark/webskema (fane 'Priser', kolonne 'Webkode')."""
    try:
        excel_data = pd.read_excel(uploaded_file, sheet_name=None)
        if "Priser" not in excel_data:
            return None, "Fanen 'Priser' blev ikke fundet i Excel-filen"

        df = excel_data["Priser"]
        webkode_variations = {"webkode", "web kode"}

        webkode_col = header_row = None
        for row_idx in range(min(6, len(df))):
            for col_idx, cell_value in enumerate(df.iloc[row_idx].fillna("")):
                if str(cell_value).strip().lower() in webkode_variations:
                    webkode_col, header_row = col_idx, row_idx
                    break
            if webkode_col is not None:
                break

        if webkode_col is None:
            return None, "Kolonnen 'Webkode' blev ikke fundet i de første 6 rækker"

        webkodes = []
        for i in range(header_row + 1, len(df)):
            value = df.iloc[i, webkode_col]
            if pd.notna(value) and str(value).strip():
                webkodes.append(str(value).strip())

        if not webkodes:
            return None, "Ingen webkoder fundet i Excel-filen"
        return webkodes, None
    except Exception as e:
        return None, f"Fejl ved læsning af Excel-fil: {e}"


def parse_text_input(text_input: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Læs webkoder fra fritekst (adskilt af mellemrum, linjeskift eller kommaer)."""
    if not text_input.strip():
        return None, "Tekstfeltet er tomt"

    codes = [c.strip() for c in re.split(r"[\s,]+", text_input.strip()) if c.strip()]
    valid, invalid = [], []
    for code in codes:
        if re.match(r"^[A-Z]{0,2}\d{5}-\d{4}-\d{2}$", code) or (
            re.search(r"\d", code) and "-" in code
        ):
            valid.append(code)
        else:
            invalid.append(code)

    if invalid:
        shown = ", ".join(invalid[:5]) + ("..." if len(invalid) > 5 else "")
        st.warning(f"⚠️ Følgende ser ikke ud som gyldige webkoder: {shown}")
    if not valid:
        return None, "Ingen gyldige webkoder fundet. Forventet format: IC23022-0072-00"
    return valid, None


# ---------------------------------------------------------------------------
# Valg-model (én kilde til sandhed)
# ---------------------------------------------------------------------------
def build_items(results: Dict) -> List[Dict]:
    """Byg en flad, stabil liste over alle valgbare billeder.

    Hvert item har en deterministisk 'key', der bruges direkte som
    checkbox-nøgle, så valg overlever reruns uden et separat sæt.
    """
    items: List[Dict] = []

    for webkode in sorted(results["found"]):
        images = sorted(results["found"][webkode], key=lambda x: x["filename"])
        counts = Counter(img["filename"] for img in images)
        occurrence: Dict[str, int] = {}
        for img in images:
            fn = img["filename"]
            occurrence[fn] = occurrence.get(fn, 0) + 1
            is_dup = counts[fn] > 1
            items.append(
                {
                    "key": f"found::{webkode}::{fn}::{occurrence[fn]}",
                    "type": "found",
                    "webkode": webkode,
                    "image": img,
                    "is_duplicate": is_dup,
                    "dup_no": occurrence[fn] if is_dup else None,
                }
            )

    for webkode in sorted(results["missing"]):
        suggestions = sorted(
            results.get("suggestions", {}).get(webkode, []), key=lambda x: x["filename"]
        )
        counts = Counter(s["filename"] for s in suggestions)
        occurrence = {}
        for sugg in suggestions:
            fn = sugg["filename"]
            occurrence[fn] = occurrence.get(fn, 0) + 1
            is_dup = counts[fn] > 1
            items.append(
                {
                    "key": f"suggestion::{webkode}::{fn}::{occurrence[fn]}",
                    "type": "suggestion",
                    "webkode": webkode,
                    "image": sugg,
                    "is_duplicate": is_dup,
                    "dup_no": occurrence[fn] if is_dup else None,
                }
            )
    return items


def set_selection(items: List[Dict], predicate) -> None:
    """Sæt checkbox-tilstanden for alle items ud fra en predikat-funktion.

    Kaldes fra batch-knapper, der ligger OVER checkboxene, så
    session_state kan opdateres før widgets instantieres i samme run.
    """
    for item in items:
        st.session_state[item["key"]] = predicate(item)


def selected_items(items: List[Dict]) -> List[Dict]:
    return [item for item in items if st.session_state.get(item["key"], False)]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def ensure_extension(filename: str) -> str:
    """Sørg for at filnavnet har en billed-endelse (default .jpg)."""
    return filename if filename.lower().endswith(IMAGE_EXTENSIONS) else f"{filename}.jpg"


def variant_renamed_filename(filename: str, webkode: str) -> str:
    """Omdøb et alternativ-filnavn til den ønskede variant fra webkoden.

    Eks.: AB23456-0023-00_01 → AB23456-0023-50_01 hvis webkoden er ...-50.
    """
    webkode_parts = webkode.split("-")
    if len(webkode_parts) < 3 or "_" not in filename:
        return filename
    desired_variant = webkode_parts[-1]
    base_part, _, suffix_part = filename.partition("_")
    base_parts = base_part.split("-")
    if len(base_parts) < 3:
        return filename
    base_parts[-1] = desired_variant
    return "-".join(base_parts) + "_" + suffix_part


def resolve_filenames(items: List[Dict], rename_alternatives: bool) -> List[Dict]:
    """Beregn endelige, unikke filnavne for de valgte billeder."""
    used_names: Dict[str, int] = {}
    resolved: List[Dict] = []

    for item in items:
        image = item["image"]
        filename = image["filename"]
        if item["type"] == "suggestion" and rename_alternatives:
            filename = variant_renamed_filename(filename, item["webkode"])

        # Gør filnavnet unikt i ZIP'en
        if filename in used_names:
            used_names[filename] += 1
            base, _, ext = ensure_extension(filename).rpartition(".")
            final = f"{base}_kopi{used_names[filename]}.{ext}"
        else:
            used_names[filename] = 0
            final = ensure_extension(filename)

        resolved.append({"url": image["url"], "filename": final})
    return resolved


def create_download_zip(images: List[Dict]) -> bytes:
    """Pak billeder til en ZIP. Bygges på disk, så kun ét billede holdes i RAM."""
    progress_bar = st.progress(0)
    status_text = st.empty()
    failures: List[str] = []

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i, image in enumerate(images):
                status_text.text(f"Henter billede {i + 1}/{len(images)} ...")
                progress_bar.progress((i + 1) / len(images))
                try:
                    response = requests.get(image["url"], timeout=30)
                    if response.status_code == 200:
                        zip_file.writestr(image["filename"], response.content)
                    else:
                        failures.append(f"{image['filename']} (HTTP {response.status_code})")
                except requests.exceptions.RequestException as e:
                    failures.append(f"{image['filename']} ({e})")

        with open(tmp_path, "rb") as fh:
            data = fh.read()
    finally:
        progress_bar.empty()
        status_text.empty()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if failures:
        st.warning("⚠️ Kunne ikke hente: " + ", ".join(failures[:10]) +
                   ("..." if len(failures) > 10 else ""))
    return data


# ---------------------------------------------------------------------------
# UI-skærme
# ---------------------------------------------------------------------------
def login_screen():
    st.title("🔐 T&A billedhenter Login")
    st.markdown("Skriv dine loginoplysninger for at fortsætte.")

    with st.form("login_form"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        submitted = st.form_submit_button("Login")

    if not submitted:
        return
    try:
        valid_username = st.secrets["login"]["username"]
        valid_password = st.secrets["login"]["password"]
    except KeyError as e:
        st.error(f"Konfigurationsfejl: mangler nøgle {e} i Streamlit secrets.")
        return

    if username == valid_username and password == valid_password:
        st.session_state.logged_in = True
        st.rerun()
    elif username and password:
        st.error("Forkert brugernavn eller adgangskode")
    else:
        st.error("Udfyld både brugernavn og adgangskode")


def api_credentials_screen():
    st.title("🔑 API-adgang")
    st.markdown("Indsæt dine API-koder.")

    with st.form("api_credentials"):
        client_id = st.text_input("Client ID")
        client_key = st.text_input("Client Key", type="password")
        submitted = st.form_submit_button("Godkend")

    if not submitted:
        return
    if not (client_id and client_key):
        st.error("Udfyld både Client ID og Client Key")
        return

    with st.spinner("Godkender mod ICRT API ..."):
        downloader = ICRTImageDownloader()
        success, message = downloader.authenticate_api(client_id, client_key)
    if success:
        st.session_state.jwt_token = downloader.jwt_token
        st.session_state.api_authenticated = True
        st.rerun()
    else:
        st.error(message)


def render_input_section(downloader: ICRTImageDownloader) -> Tuple[Optional[List[str]], str]:
    """Vis input-faner og returnér (webkoder, projektkode)."""
    st.header("📑 Input webkoder")
    st.subheader("Du har to muligheder for at indtaste webkoderne:")
    st.text(
        "✏️ Fane 1: indsæt webkoderne direkte (copy-paste).\n"
        "🗂️ Fane 2: upload et prisark eller webskema."
    )

    tab1, tab2 = st.tabs(["✏️ Indsæt tekst", "🗂️ Upload Excel-fil"])
    webkodes: Optional[List[str]] = None

    with tab1:
        text_input = st.text_area(
            "Indsæt webkoder (adskilt af mellemrum, linjeskift eller kommaer):",
            placeholder="IC23022-0072-00 IC23022-0220-31 IC23022-0050-00",
            height=150,
        )
        if text_input:
            parsed, error = parse_text_input(text_input)
            if error:
                st.error(error)
            else:
                webkodes = parsed
                st.success(f"✅ Fundet {len(webkodes)} webkoder i teksten")

    with tab2:
        uploaded_file = st.file_uploader(
            "Filen skal have en fane 'Priser' og en kolonne 'Webkode'.",
            type=["xlsx", "xls"],
        )
        if uploaded_file:
            parsed, error = parse_excel_file(uploaded_file)
            if error:
                st.error(error)
            else:
                webkodes = parsed
                st.success(f"✅ Fundet {len(webkodes)} webkoder i Excel-filen")

    project_code = downloader.extract_project_code(webkodes[0]) if webkodes else ""
    return webkodes, project_code


def render_batch_controls(items: List[Dict]) -> None:
    """Knapper til at vælge flere ad gangen. Ligger over billedlisten."""
    st.subheader("🎛️ Vælg flere ad gangen")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("✅ Vælg alle inkl. forslag", use_container_width=True):
            set_selection(items, lambda item: True)
    with col2:
        if st.button("🎯 Vælg kun hele matches", use_container_width=True):
            set_selection(items, lambda item: item["type"] == "found")
    with col3:
        if st.button("🔄 Fravælg dubletter", use_container_width=True):
            for item in items:
                if item["is_duplicate"] and item["dup_no"] and item["dup_no"] > 1:
                    st.session_state[item["key"]] = False
    with col4:
        if st.button("❌ Fravælg alle", use_container_width=True):
            set_selection(items, lambda item: False)


def render_image_list(items: List[Dict]) -> None:
    """Vis checkboxes for fundne billeder og forslag, grupperet pr. webkode."""
    found_by_webkode: Dict[str, List[Dict]] = {}
    suggestions_by_webkode: Dict[str, List[Dict]] = {}
    for item in items:
        target = found_by_webkode if item["type"] == "found" else suggestions_by_webkode
        target.setdefault(item["webkode"], []).append(item)

    for webkode in sorted(found_by_webkode):
        group = found_by_webkode[webkode]
        st.subheader(f"📋 {webkode} ({len(group)} billeder)")
        for item in group:
            image = item["image"]
            if item["is_duplicate"]:
                label = f"🔄 {image['filename']} (kopi #{item['dup_no']})"
            else:
                label = f"📷 {image['filename']}"
            st.checkbox(label, key=item["key"])

    if suggestions_by_webkode:
        st.subheader("💡 Foreslåede alternativer for manglende billeder")
        for webkode in sorted(suggestions_by_webkode):
            group = suggestions_by_webkode[webkode]
            st.write(f"🔍 **{webkode}** — intet direkte match. {len(group)} alternativ(er):")
            for item in group:
                image = item["image"]
                suffix = f" (kopi #{item['dup_no']})" if item["is_duplicate"] else ""
                label = f"📷 {image['filename']}{suffix} (fra {image['webkode']})"
                st.checkbox(label, key=item["key"])


def render_download_section(items: List[Dict], rename_alternatives: bool, project_code: str) -> None:
    chosen = selected_items(items)
    count = len(chosen)
    st.header(f"⬇️ Hent valgte billeder ({count})")

    if count == 0:
        st.info("Vælg mindst ét billede ovenfor.")
        return

    if count > MAX_IMAGES_PER_ZIP:
        st.error(
            f"⚠️ Du har valgt **{count} billeder**, men maksimum er "
            f"**{MAX_IMAGES_PER_ZIP}** pr. download."
        )
        st.markdown(
            f"Fravælg **{count - MAX_IMAGES_PER_ZIP}** billeder, eller brug "
            f"**'Fravælg dubletter'** og download i mindre portioner."
        )
        return

    # Signatur over det aktuelle valg, så en gammel ZIP ikke downloades ved ændret valg
    signature = (tuple(sorted(item["key"] for item in chosen)), rename_alternatives)

    if st.button("📦 Pak ZIP-fil", type="primary"):
        resolved = resolve_filenames(chosen, rename_alternatives)
        with st.spinner("Pakker dine filer ..."):
            st.session_state.zip_bytes = create_download_zip(resolved)
        st.session_state.zip_name = f"icrt_images_{project_code}_{int(time.time())}.zip"
        st.session_state.zip_signature = signature

    if st.session_state.zip_bytes is not None and st.session_state.zip_signature == signature:
        size_mb = len(st.session_state.zip_bytes) / (1024 * 1024)
        st.success(f"✅ ZIP klar ({size_mb:.1f} MB)")
        st.download_button(
            "💾 Download ZIP",
            data=st.session_state.zip_bytes,
            file_name=st.session_state.zip_name,
            mime="application/zip",
            use_container_width=True,
        )
    elif st.session_state.zip_bytes is not None:
        st.info("Dit valg er ændret. Tryk **'Pak ZIP-fil'** igen for at opdatere downloaden.")


def render_results(project_code: str) -> None:
    results = st.session_state.search_results
    if not results:
        return

    st.header("📊 Filer fundet")
    col1, col2, col3 = st.columns(3)
    col1.metric("Webkoder fundet", len(results["found"]))
    col2.metric("Webkoder uden match", len(results["missing"]))
    col3.metric("Billeder i alt", sum(len(v) for v in results["found"].values()))

    items = st.session_state.items
    if not items:
        st.info("Ingen billeder at vælge imellem.")
        return

    st.header("✅ Vælg de billeder du vil hente ned")
    st.markdown(
        "Vælg både direkte matches og forslag til alternativer. "
        "Brug knapperne nedenfor til at vælge flere ad gangen."
    )

    rename_alternatives = st.checkbox(
        "🔄 Omdøb alternative filer til det ønskede variant-nummer",
        help="Eks.: AB23456-0023-00_01 → AB23456-0023-50_01 hvis du søgte efter ...-50",
    )

    render_batch_controls(items)
    render_image_list(items)
    render_download_section(items, rename_alternatives, project_code)


# ---------------------------------------------------------------------------
# Hovedapplikation
# ---------------------------------------------------------------------------
def main_application():
    st.title("🚚 TA Billedhenter")
    downloader = ICRTImageDownloader(st.session_state.jwt_token)

    webkodes, project_code = render_input_section(downloader)

    if not webkodes:
        return

    st.header("🏷️ Tjek projekt-koden")
    project_code_input = st.text_input(
        "Projektkoden hentes automatisk fra første webkode, men kan rettes hvis nødvendigt.",
        value=project_code,
        help="Format: LLDDDDD (fx IC20006) eller DDDDD",
    )

    if st.button("🔍 Find billedfiler", type="primary"):
        if not project_code_input:
            st.error("Projektkode mangler — prøv igen.")
            return
        with st.spinner("Søger efter filer ..."):
            results = downloader.search_images_for_codes(project_code_input, webkodes)
        st.session_state.search_results = results
        st.session_state.items = build_items(results) if results else []
        # Nulstil tidligere ZIP når der søges på ny
        st.session_state.zip_bytes = None
        st.session_state.zip_signature = None

    render_results(project_code_input)


def main():
    init_session_state()

    if not st.session_state.logged_in:
        login_screen()
        return
    if not st.session_state.api_authenticated:
        api_credentials_screen()
        return

    with st.sidebar:
        st.header("🕹️ Menu")
        if st.button("👋 Log ud"):
            st.session_state.clear()
            st.rerun()
        st.markdown("---")
        st.markdown("**Status:** ✅ Logget ind")
        st.markdown("**API:** 🟢 Forbundet")

    main_application()


if __name__ == "__main__":
    main()
