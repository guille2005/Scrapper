import asyncio
import base64
import csv
import html
import json
import os
import re
import smtplib
import socket
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

import flet as ft
import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from requests.packages.urllib3.exceptions import InsecureRequestWarning

try:
    import dns.resolver
except ImportError:
    dns = None

try:
    from googlesearch import search as google_search
except ImportError:
    google_search = None

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
REQUEST_TIMEOUT = 12
SEARCH_TIMEOUT = 6
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}
SEARCH_CACHE: dict[str, list[str]] = {}
APP_VERSION = "0.3.0"
SUPABASE_URL = "https://ziyrtaxmvxfzsondcxph.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_bwOFLcHH8HTg-Tvwo5ThAw_3NxIHvCU"
GITHUB_REPO = "guille2005/Scrapper"
GITHUB_RELEASE_ASSET = "ScraperCorreos.exe"
CONTACT_KEYWORDS = (
    "contacto",
    "contact",
    "aviso",
    "legal",
    "privacidad",
    "politica",
    "nosotros",
)
BLOCKED_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "wikipedia.org",
    "einforma.com",
    "empresite.eleconomista.es",
    "axesor.es",
    "expansion.com/directorio",
    "infocif.es",
    "infoempresa.com",
    "empresia.es",
    "iberinform.es",
)
BAD_EMAIL_TLDS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "svg",
    "ico",
    "bmp",
    "tif",
    "tiff",
    "css",
    "js",
    "json",
    "xml",
    "map",
    "pdf",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "mp3",
    "mp4",
    "avi",
    "mov",
    "webm",
    "woff",
    "woff2",
    "ttf",
    "eot",
}
EMAIL_PATTERN = re.compile(
    r"""
    \b
    [a-z0-9][a-z0-9._%+\-]{0,63}
    @
    (?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+
    [a-z]{2,24}
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        folder = Path(base) / "ScraperCorreos"
    else:
        folder = Path.home() / ".scraper_correos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load_app_config() -> dict[str, str]:
    config = {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY,
        "github_repo": GITHUB_REPO,
        "github_release_asset": GITHUB_RELEASE_ASSET,
        "app_version": APP_VERSION,
    }

    for config_path in (app_base_dir() / "scraper_config.json", app_data_dir() / "scraper_config.json"):
        if not config_path.exists():
            continue
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        for key, value in file_config.items():
            if isinstance(value, str) and value.strip():
                config[key] = value.strip()

    env_map = {
        "SCRAPER_SUPABASE_URL": "supabase_url",
        "SCRAPER_SUPABASE_ANON_KEY": "supabase_anon_key",
        "SCRAPER_GITHUB_REPO": "github_repo",
        "SCRAPER_GITHUB_RELEASE_ASSET": "github_release_asset",
    }
    for env_name, config_key in env_map.items():
        value = os.environ.get(env_name)
        if value:
            config[config_key] = value.strip()

    return config


APP_CONFIG = load_app_config()


def supabase_headers(config: dict[str, str]) -> dict[str, str]:
    key = config.get("supabase_anon_key", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def check_remote_login(login_name: str) -> tuple[bool, str]:
    login_name = (login_name or "").strip()
    if not login_name:
        return False, "Escribe un nombre para entrar."

    if not APP_CONFIG.get("supabase_url") or not APP_CONFIG.get("supabase_anon_key"):
        return False, "Falta configurar Supabase en scraper_config.json."

    rpc_url = f"{APP_CONFIG['supabase_url'].rstrip('/')}/rest/v1/rpc/check_scraper_access"
    try:
        response = requests.post(
            rpc_url,
            headers=supabase_headers(APP_CONFIG),
            json={"input_name": login_name},
            timeout=10,
            verify=False,
        )
        response.raise_for_status()
        allowed = bool(response.json())
    except requests.RequestException:
        return False, "No se pudo conectar con Supabase."
    except ValueError:
        return False, "Supabase respondió con un formato inesperado."

    if allowed:
        return True, ""
    return False, "Ese nombre no tiene acceso."


def parse_version(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(number) for number in numbers[:4]) or (0,)


def latest_release_info() -> tuple[dict[str, str] | None, str]:
    repo = APP_CONFIG.get("github_repo", "").strip()
    if not repo:
        return None, "No hay repositorio de GitHub configurado."

    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        response = requests.get(api_url, timeout=12, verify=False, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        release = response.json()
    except requests.RequestException:
        return None, "No se pudo consultar GitHub."
    except ValueError:
        return None, "GitHub respondió con un formato inesperado."

    tag = str(release.get("tag_name") or "")
    if parse_version(tag) <= parse_version(APP_VERSION):
        return None, "Ya tienes la última versión."

    asset_name = APP_CONFIG.get("github_release_asset") or GITHUB_RELEASE_ASSET
    asset_url = ""
    for asset in release.get("assets", []):
        name = str(asset.get("name") or "")
        if name == asset_name or name.lower().endswith(".exe"):
            asset_url = str(asset.get("browser_download_url") or "")
            break

    return (
        {
            "version": tag,
            "html_url": str(release.get("html_url") or ""),
            "asset_url": asset_url,
        },
        "",
    )


def install_update_from_release(release: dict[str, str]) -> str:
    asset_url = release.get("asset_url", "")
    if not asset_url:
        return "La release existe, pero no encuentro el .exe para descargar."

    target_path = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else app_base_dir() / "ScraperCorreos_update.exe"
    temp_exe = Path(tempfile.gettempdir()) / "ScraperCorreos_update.exe"

    with requests.get(asset_url, stream=True, timeout=60, verify=False) as response:
        response.raise_for_status()
        with temp_exe.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 512):
                if chunk:
                    handle.write(chunk)

    if not getattr(sys, "frozen", False):
        return f"Actualización descargada para prueba: {temp_exe}"

    updater = Path(tempfile.gettempdir()) / "actualizar_scraper_correos.cmd"
    updater.write_text(
        "\n".join(
            [
                "@echo off",
                "timeout /t 2 /nobreak >nul",
                f'move /Y "{temp_exe}" "{target_path}" >nul',
                f'start "" "{target_path}"',
                'del "%~f0"',
            ]
        ),
        encoding="utf-8",
    )
    subprocess.Popen(
        ["cmd", "/c", str(updater)],
        cwd=str(target_path.parent),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    os._exit(0)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.strip().lower()


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", normalize_text(value))


def detect_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def find_column(headers: list[str], column_name: str, required: bool) -> str | None:
    normalized = {normalize_header(header): header for header in headers if header}
    header = normalized.get(normalize_header(column_name))
    if required and not header:
        raise ValueError(f"No se encontro la columna obligatoria: {column_name}")
    return header


def read_companies_from_csv(csv_path: str, require_web: bool = False) -> list[dict[str, str]]:
    last_error: Exception | None = None

    for encoding in CSV_ENCODINGS:
        try:
            with open(csv_path, "r", encoding=encoding, newline="") as csv_file:
                sample = csv_file.read(4096)
                csv_file.seek(0)
                reader = csv.DictReader(csv_file, dialect=detect_csv_dialect(sample))

                if not reader.fieldnames:
                    raise ValueError("El CSV no contiene cabeceras.")

                company_col = find_column(reader.fieldnames, "Empresa", required=True)
                web_col = find_column(reader.fieldnames, "Web", required=require_web)
                rows: list[dict[str, str]] = []

                for row in reader:
                    rows.append(
                        {
                            "Empresa": (row.get(company_col or "") or "").strip(),
                            "Web": (row.get(web_col or "") or "").strip(),
                        }
                    )

                return rows
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    raise ValueError("No se pudo leer el CSV con UTF-8, CP1252 ni Latin-1.") from last_error


def save_results_to_excel(
    results: list[dict[str, str]],
    csv_path: str,
    file_name: str,
    columns: list[str],
) -> str:
    output_path = Path(csv_path).resolve().parent / file_name
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Resultados"
    worksheet.append(columns)

    for row in results:
        worksheet.append([row.get(column, "") for column in columns])

    for index, column in enumerate(columns, start=1):
        worksheet.column_dimensions[chr(64 + index)].width = max(22, len(column) + 6)

    workbook.save(output_path)
    return str(output_path)


def ensure_url_has_scheme(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return ""
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    return f"https://{raw_url}"


def clean_email(candidate: str) -> str:
    email_address = html.unescape(candidate or "")
    email_address = unquote(email_address)
    email_address = email_address.strip().strip(".,;:()[]{}<>\"'")
    return email_address.lower()


def is_valid_email(candidate: str) -> bool:
    if not candidate or "@" not in candidate or len(candidate) > 254:
        return False

    local_part, domain = candidate.rsplit("@", 1)
    if not local_part or not domain or ".." in candidate:
        return False

    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in BAD_EMAIL_TLDS:
        return False

    return not any(candidate.endswith(f".{bad_tld}") for bad_tld in BAD_EMAIL_TLDS)


def extract_emails(page_content: str) -> list[str]:
    normalized_content = html.unescape(page_content or "")
    normalized_content = unquote(normalized_content).replace("&#64;", "@")
    emails: list[str] = []
    seen: set[str] = set()

    for match in EMAIL_PATTERN.findall(normalized_content):
        email_address = clean_email(match)
        if is_valid_email(email_address) and email_address not in seen:
            seen.add(email_address)
            emails.append(email_address)

    return emails


def fetch_page(session: requests.Session, url: str, timeout: int = REQUEST_TIMEOUT) -> tuple[str, str]:
    response = session.get(
        url,
        timeout=timeout,
        verify=False,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.url, response.text


def get_page_text(page_content: str) -> str:
    soup = BeautifulSoup(page_content or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return normalize_text(soup.get_text(" ", strip=True))


def is_internal_link(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).netloc or "").lower().removeprefix("www.")
    candidate_host = (urlparse(candidate_url).netloc or "").lower().removeprefix("www.")

    if not base_host or not candidate_host:
        return False

    return candidate_host == base_host or candidate_host.endswith(f".{base_host}")


def find_contact_links(base_url: str, page_content: str, limit: int = 5) -> list[str]:
    soup = BeautifulSoup(page_content or "", "html.parser")
    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        decoded_href = unquote(href).lower()

        if not any(keyword in decoded_href for keyword in CONTACT_KEYWORDS):
            continue

        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        if parsed.scheme not in {"http", "https"}:
            continue
        if not is_internal_link(base_url, absolute_url):
            continue
        if absolute_url in seen:
            continue

        seen.add(absolute_url)
        links.append(absolute_url)

        if len(links) >= limit:
            break

    return links


def scrape_email_from_website(raw_url: str) -> str:
    start_url = ensure_url_has_scheme(raw_url)
    if not start_url:
        return ""

    with requests.Session() as session:
        session.headers.update(HEADERS)

        try:
            final_url, home_content = fetch_page(session, start_url)
        except requests.RequestException:
            if not start_url.startswith("https://"):
                return ""
            try:
                final_url, home_content = fetch_page(
                    session,
                    start_url.replace("https://", "http://", 1),
                )
            except requests.RequestException:
                return ""

        home_emails = extract_emails(home_content)
        if home_emails:
            return home_emails[0]

        for contact_url in find_contact_links(final_url, home_content, limit=5):
            try:
                _, contact_content = fetch_page(session, contact_url)
            except requests.RequestException:
                continue

            contact_emails = extract_emails(contact_content)
            if contact_emails:
                return contact_emails[0]

    return ""


def parse_niche_keywords(raw_keywords: str) -> list[str]:
    keywords = []
    for keyword in re.split(r"[,;\n|]+", raw_keywords or ""):
        normalized = normalize_text(keyword)
        if normalized:
            keywords.append(normalized)
    return keywords


def decode_duckduckgo_url(raw_href: str) -> str:
    if not raw_href:
        return ""
    parsed = urlparse(raw_href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(uddg)
    if raw_href.startswith("//"):
        return f"https:{raw_href}"
    return raw_href


def decode_bing_url(raw_href: str) -> str:
    if not raw_href:
        return ""

    parsed = urlparse(raw_href)
    if "bing.com" not in parsed.netloc:
        return raw_href

    encoded_url = parse_qs(parsed.query).get("u", [""])[0]
    if not encoded_url:
        return raw_href

    if encoded_url.startswith("a1"):
        encoded_url = encoded_url[2:]

    try:
        padding = "=" * (-len(encoded_url) % 4)
        return base64.urlsafe_b64decode(encoded_url + padding).decode("utf-8", "ignore")
    except Exception:
        return raw_href


def is_candidate_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    full_url = f"{host}{parsed.path}".lower()
    return not any(domain in full_url for domain in BLOCKED_DOMAINS)


def is_search_result_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    search_hosts = (
        "google.",
        "bing.com",
        "duckduckgo.com",
        "brave.com",
        "microsoft.com",
    )
    return not any(search_host in host for search_host in search_hosts)


def search_duckduckgo(query: str, limit: int = 3) -> list[str]:
    search_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    urls: list[str] = []
    seen: set[str] = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)
        response = session.get(search_url, timeout=SEARCH_TIMEOUT, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

    for anchor in soup.select("a.result__a, a.result-link, a[href]"):
        url = decode_duckduckgo_url(anchor.get("href", ""))
        if not is_search_result_url(url) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break

    return urls


def search_bing(query: str, limit: int = 5) -> list[str]:
    search_url = "https://www.bing.com/search?" + urlencode({"q": query})
    urls: list[str] = []
    seen: set[str] = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)
        response = session.get(search_url, timeout=SEARCH_TIMEOUT, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

    selectors = "li.b_algo h2 a[href], ol#b_results h2 a[href], a[href]"
    for anchor in soup.select(selectors):
        url = decode_bing_url(anchor.get("href", ""))
        if not is_search_result_url(url) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break

    return urls


def search_brave(query: str, limit: int = 5) -> list[str]:
    search_url = "https://search.brave.com/search?" + urlencode({"q": query})
    urls: list[str] = []
    seen: set[str] = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)
        response = session.get(search_url, timeout=SEARCH_TIMEOUT, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

    selectors = "a[href][data-testid], a.result-header[href], a[href]"
    for anchor in soup.select(selectors):
        url = anchor.get("href", "")
        if url.startswith("/"):
            continue
        if not is_search_result_url(url) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break

    return urls


def search_google(query: str, limit: int = 5) -> list[str]:
    if google_search is None:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for url in google_search(query, num_results=limit, lang="es", timeout=SEARCH_TIMEOUT, ssl_verify=False):
        if not is_search_result_url(url) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def search_ddgs(query: str, limit: int = 5) -> list[dict[str, str]]:
    if DDGS is None:
        return []

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    with DDGS(timeout=SEARCH_TIMEOUT) as ddgs:
        for result in ddgs.text(query, max_results=limit, region="es-es"):
            url = result.get("href") or result.get("url") or ""
            if not is_search_result_url(url) or url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "url": url,
                    "title": result.get("title") or "",
                    "body": result.get("body") or "",
                }
            )
            if len(results) >= limit:
                break
    return results


def clean_company_for_domain(company: str) -> str:
    cleaned = normalize_text(company)
    cleaned = re.sub(r"\bs\s*\.?\s*a\s*\.?\s*t\s*\.?\b", " ", cleaned)
    cleaned = re.sub(r"\bs\s*\.?\s*c\s*\.?\s*a\s*\.?\b", " ", cleaned)
    cleaned = re.sub(
        r"\b(s\.?l\.?u?|s\.?a\.?|s\.?l\.?|ltd|limited|sociedad limitada|sociedad anonima)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"[^a-z0-9]+", "", cleaned)
    return cleaned


def company_prefix_slug(company: str) -> str:
    normalized = normalize_text(company)
    if re.search(r"\bs\s*\.?\s*c\s*\.?\s*a\s*\.?\b", normalized):
        return "sca"
    if re.search(r"\bs\s*\.?\s*a\s*\.?\s*t\s*\.?\b", normalized):
        return "sat"
    return ""


def expand_common_abbreviations(text: str) -> list[str]:
    variants = [text]
    expanded = re.sub(r"\bntra\b", "nuestra", text, flags=re.IGNORECASE)
    expanded = re.sub(r"\bsra\b", "senora", expanded, flags=re.IGNORECASE)
    if expanded != text:
        variants.append(expanded)
    expanded_spanish = re.sub(r"\bsenora\b", "señora", expanded, flags=re.IGNORECASE)
    if expanded_spanish not in variants:
        variants.append(expanded_spanish)
    return variants


def company_directory_slug(company: str) -> str:
    slug = normalize_text(company)
    slug = re.sub(r"\bs\s*\.?\s*a\s*\.?\s*t\s*\.?\b", "s-a-t", slug)
    slug = re.sub(r"\bs\s*\.?\s*c\s*\.?\s*a\s*\.?\b", "s-c-a", slug)
    slug = re.sub(
        r"\b(s\.?l\.?u?|s\.?a\.?|s\.?l\.?|ltd|limited|sociedad limitada|sociedad anonima)\b",
        " ",
        slug,
    )
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return re.sub(r"-+", "-", slug)


def company_domain_guesses(company: str) -> list[str]:
    slug = clean_company_for_domain(company)
    if not slug or len(slug) < 4:
        return []

    tokens = company_tokens(company)
    prefix = company_prefix_slug(company)
    slugs = [slug]
    if prefix and tokens:
        slugs.append(prefix + "".join(tokens))
        if len(tokens) >= 2:
            slugs.append(prefix + "".join(tokens[:2]))
    if len(tokens) >= 2:
        slugs.append("".join(tokens[:2]))
        slugs.append("aceites" + "".join(tokens[:2]))
    if len(tokens) >= 3:
        slugs.append("".join(tokens[-2:]))
    if tokens and " el " in f" {normalize_text(company)} ":
        slugs.append("el" + tokens[-1])

    unique_slugs: list[str] = []
    seen_slugs: set[str] = set()
    for candidate_slug in slugs:
        if candidate_slug and candidate_slug not in seen_slugs:
            seen_slugs.add(candidate_slug)
            unique_slugs.append(candidate_slug)

    domains: list[str] = []
    for suffix in ("com", "es", "net"):
        for candidate_slug in unique_slugs:
            domains.append(f"https://www.{candidate_slug}.{suffix}")
            domains.append(f"https://{candidate_slug}.{suffix}")
    return domains


def directory_url_guesses(company: str) -> list[str]:
    slug = company_directory_slug(company)
    if not slug:
        return []
    return [
        f"https://www.gustodelsur.es/empresa/{slug}/",
    ]


def search_queries_for_company(company: str, keywords: list[str]) -> list[str]:
    clean_company = re.sub(r"[,.;]", " ", company)
    clean_company = re.sub(r"\s+", " ", clean_company).strip()
    compact_company = re.sub(r"\bS\s+C\s+A\b", "SCA", clean_company, flags=re.IGNORECASE)
    compact_company = re.sub(r"\bS\s+A\s+T\b", "SAT", compact_company, flags=re.IGNORECASE)
    no_suffix = re.sub(
        r"\b(S\.?\s*L\.?|S\.?\s*A\.?)\b",
        " ",
        company,
        flags=re.IGNORECASE,
    )
    no_suffix = re.sub(r"[,.;]", " ", no_suffix)
    no_suffix = re.sub(r"\s+", " ", no_suffix).strip()
    queries = [
        company,
        clean_company,
        compact_company,
        no_suffix,
    ]
    for variant in expand_common_abbreviations(clean_company):
        queries.append(variant)
    for variant in expand_common_abbreviations(compact_company):
        queries.append(variant)
    tokens = company_tokens(company)
    if tokens:
        queries.append(" ".join(tokens))
    if len(tokens) >= 2:
        queries.append(" ".join(tokens[:2]))

    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query and query not in seen:
            seen.add(query)
            unique_queries.append(query)
    return unique_queries


def collect_search_candidates(company: str, keywords: list[str], limit: int = 12) -> list[str]:
    cache_key = f"{normalize_text(company)}|{','.join(keywords)}|{limit}"
    if cache_key in SEARCH_CACHE:
        return SEARCH_CACHE[cache_key]

    queries = search_queries_for_company(company, keywords)
    keyword_text = " ".join(keywords)
    if keyword_text:
        queries.extend(f"{query} {keyword_text}" for query in queries[:4])
    candidates: list[str] = []
    seen: set[str] = set()

    for query in queries:
        if not query:
            continue
        for searcher in (search_brave, search_google, search_bing, search_duckduckgo):
            try:
                found_urls = searcher(query, limit=limit)
            except Exception:
                continue

            for url in found_urls:
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    SEARCH_CACHE[cache_key] = candidates[:limit]
    return SEARCH_CACHE[cache_key]


def exact_search_queries(company: str) -> list[str]:
    clean_company = re.sub(r"\s+", " ", (company or "").strip())
    compact_company = re.sub(r"\bs\s*\.?\s*c\s*\.?\s*a\s*\.?", "SCA", clean_company, flags=re.IGNORECASE)
    compact_company = re.sub(r"\bs\s*\.?\s*a\s*\.?\s*t\s*\.?", "SAT", compact_company, flags=re.IGNORECASE)
    compact_company = re.sub(r"\s+", " ", compact_company).strip()
    queries = [
        clean_company,
        compact_company,
        f"{clean_company} empresa",
        f"{compact_company} empresa",
    ]

    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query and query not in seen:
            seen.add(query)
            unique_queries.append(query)
    return unique_queries


def score_search_result(url: str, title: str, body: str, company: str) -> int:
    parsed = urlparse(url)
    host = normalize_text(parsed.netloc.removeprefix("www."))
    path = normalize_text(parsed.path)
    text = normalize_text(f"{title} {body}")
    compact_host = re.sub(r"[^a-z0-9]+", "", host)
    compact_url = re.sub(r"[^a-z0-9]+", "", normalize_text(url))
    tokens = company_tokens(company)
    prefix = company_prefix_slug(company)
    slug = clean_company_for_domain(company)
    score = 0

    if prefix and tokens and (prefix + "".join(tokens)) in compact_host:
        score += 220
    if slug and slug in compact_host:
        score += 180
    if prefix and prefix in compact_url:
        score += 30

    for token in tokens:
        if token in host:
            score += 45
        elif token in path:
            score += 25
        elif token in text:
            score += 10

    full_url = f"{host}{path}"
    if any(domain in full_url for domain in BLOCKED_DOMAINS):
        score -= 120
    if any(domain in host for domain in ("facebook", "instagram", "linkedin", "tiktok", "youtube")):
        score -= 140
    if any(domain in host for domain in ("blogspot", "wordpress", "wixsite", "webnode")):
        score -= 180
    if any(domain in host for domain in ("canarias7", "lavanguardia", "elpais", "elmundo", "abc.es")):
        score -= 140
    if path in {"", "/"}:
        score += 60

    return score


def search_result_matches_company(url: str, title: str, body: str, company: str) -> bool:
    haystack = normalize_text(f"{url} {title} {body}")
    tokens = company_tokens(company)
    prefix = company_prefix_slug(company)
    compact_haystack = re.sub(r"[^a-z0-9]+", "", haystack)
    if prefix and prefix not in compact_haystack:
        return False
    if not tokens:
        return True

    matched_tokens = sum(1 for token in tokens if token in haystack)
    required_tokens = 1 if len(tokens) == 1 else 2
    return matched_tokens >= min(required_tokens, len(tokens))


def first_search_result(company: str) -> str:
    query = (company or "").strip()
    if not query:
        return ""

    ranked_results: list[tuple[int, int, str]] = []
    first_seen = ""
    order = 0

    for search_query in exact_search_queries(query):
        try:
            for result in search_ddgs(search_query, limit=5):
                order += 1
                if not first_seen:
                    first_seen = result["url"]
                if search_result_matches_company(
                    result["url"],
                    result["title"],
                    result["body"],
                    company,
                ):
                    ranked_results.append(
                        (
                            score_search_result(result["url"], result["title"], result["body"], company),
                            -order,
                            result["url"],
                        )
                    )
        except Exception:
            pass

    if ranked_results:
        ranked_results.sort(reverse=True)
        if ranked_results[0][0] > 0:
            return ranked_results[0][2]
    if first_seen:
        return first_seen

    for search_query in exact_search_queries(query):
        for searcher in (search_google, search_bing, search_duckduckgo, search_brave):
            try:
                urls = searcher(search_query, limit=5)
            except Exception:
                continue
            if urls:
                return urls[0]
    return ""


def company_tokens(company: str) -> list[str]:
    clean_company = normalize_text(company)
    clean_company = re.sub(
        r"\b(s\.?l\.?u?|s\.?a\.?|s\.?c\.?a\.?|s\.?l\.?|ltd|limited|sociedad|limitada|anonima)\b",
        " ",
        clean_company,
    )
    tokens = re.findall(r"[a-z0-9]{3,}", clean_company)
    ignored = {"del", "las", "los", "una", "con", "para", "the", "and"}
    return [token for token in tokens if token not in ignored]


def score_company_url(url: str, company: str, page_content: str = "") -> int:
    parsed = urlparse(url)
    host = normalize_text(parsed.netloc.removeprefix("www."))
    path = normalize_text(parsed.path)
    text = get_page_text(page_content) if page_content else ""
    slug = clean_company_for_domain(company)
    prefix = company_prefix_slug(company)
    tokens = company_tokens(company)
    score = 0

    compact_host = host.replace(".", "")
    if slug and slug in compact_host:
        score += 100
    if prefix and tokens and (prefix + "".join(tokens)) in compact_host:
        score += 120
    for token in tokens:
        if token in host:
            score += 30
        elif token in path:
            score += 10
        elif token in text:
            score += 4

    if any(domain in host for domain in ("facebook", "linkedin", "instagram")):
        score -= 50
    return score


def validate_url_niche(url: str, keywords: list[str]) -> tuple[bool, str]:
    if not keywords:
        return False, ""

    with requests.Session() as session:
        session.headers.update(HEADERS)
        try:
            _, content = fetch_page(session, ensure_url_has_scheme(url), timeout=SEARCH_TIMEOUT)
        except requests.RequestException:
            return False, ""

    page_text = get_page_text(content)
    matches = any(keyword in page_text for keyword in keywords)
    return matches, content


def find_company_website(company: str, niche_keywords: str) -> dict[str, str]:
    company = (company or "").strip()
    keywords = parse_niche_keywords(niche_keywords)
    if not company:
        return {
            "Web Encontrada": "",
            "Con nicho": "",
            "Sin nicho": "",
            "Validación de Nicho": "Sin resultado",
        }

    url = first_search_result(company)
    if url:
        has_niche, _ = validate_url_niche(url, keywords)
        return {
            "Web Encontrada": url,
            "Con nicho": url if has_niche else "",
            "Sin nicho": "" if has_niche else url,
            "Validación de Nicho": "Con nicho" if has_niche else "Sin nicho",
        }

    return {
        "Web Encontrada": "",
        "Con nicho": "",
        "Sin nicho": "",
        "Validación de Nicho": "Sin resultado",
    }


def verify_email_smtp(email_address: str) -> str:
    email_address = clean_email(email_address)
    if not is_valid_email(email_address):
        return "No válido"

    if dns is None:
        return "Servidor Protegido o Catch-all"

    domain = email_address.rsplit("@", 1)[1]

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        mx_hosts = sorted(
            [(answer.preference, str(answer.exchange).rstrip(".")) for answer in answers],
            key=lambda item: item[0],
        )
    except Exception:
        return "No válido"

    for _, mx_host in mx_hosts[:2]:
        try:
            with smtplib.SMTP(mx_host, 25, timeout=10) as server:
                server.set_debuglevel(0)
                server.helo("localhost")
                server.mail("verificador@example.com")
                code, _ = server.rcpt(email_address)

            if code in (250, 251):
                return "Válido"
            if code in (550, 551, 553):
                return "No válido"
            return "Servidor Protegido o Catch-all"
        except (OSError, smtplib.SMTPException, socket.timeout):
            continue

    return "Servidor Protegido o Catch-all"


def find_email_and_verify(web_url: str) -> dict[str, str]:
    email_address = scrape_email_from_website(web_url)
    status = verify_email_smtp(email_address) if email_address else ""
    return {"Correo Encontrado": email_address, "Estado de Verificación": status}


def run_complete_for_company(company: str, niche_keywords: str) -> dict[str, str]:
    website_result = find_company_website(company, niche_keywords)
    web_url = website_result["Web Encontrada"]
    email_result = find_email_and_verify(web_url) if web_url else {
        "Correo Encontrado": "",
        "Estado de Verificación": "",
    }
    return {
        "Web Encontrada": web_url,
        "Correo Encontrado": email_result["Correo Encontrado"],
        "Estado de Verificación": email_result["Estado de Verificación"],
    }


class TabState:
    def __init__(self) -> None:
        self.csv_path = ""
        self.running = False
        self.file_text: ft.Text | None = None
        self.progress: ft.ProgressBar | None = None
        self.status: ft.Text | None = None
        self.result: ft.Text | None = None
        self.select_button: ft.OutlinedButton | None = None
        self.start_button: ft.ElevatedButton | None = None
        self.niche_field: ft.TextField | None = None


def main(page: ft.Page) -> None:
    page.title = "Scraper corporativo"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.padding = 26
    page.window_width = 1080
    page.window_height = 760
    page.bgcolor = "#F7F8FA"

    def show_message(message: str, error: bool = False) -> None:
        page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color="#111827"),
            bgcolor="#FEE2E2" if error else "#DCFCE7",
        )
        page.snack_bar.open = True
        page.update()

    def update_buttons(state: TabState, needs_niche: bool = False) -> None:
        if not state.select_button or not state.start_button:
            return
        has_niche = bool((state.niche_field.value if state.niche_field else "").strip())
        state.select_button.disabled = state.running
        state.start_button.disabled = state.running or not state.csv_path or (needs_niche and not has_niche)
        state.start_button.bgcolor = "#9CA3AF" if state.start_button.disabled else "#2563EB"

    async def set_progress(state: TabState, value: float, text: str) -> None:
        if state.progress and state.status:
            state.progress.value = max(0, min(1, value))
            state.status.value = text
            page.update(state.progress, state.status)
        await asyncio.sleep(0.05)

    def section_text(text: str, size: int = 13, color: str = "#4B5563") -> ft.Text:
        return ft.Text(text, size=size, color=color, selectable=False)

    def make_button_styles() -> tuple[ft.ButtonStyle, ft.ButtonStyle]:
        outline_style = ft.ButtonStyle(
            color="#1F2937",
            side=ft.BorderSide(1, "#D1D5DB"),
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(16, 13, 16, 13),
        )
        primary_style = ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(18, 13, 18, 13),
        )
        return outline_style, primary_style

    async def check_updates_from_ui() -> None:
        show_message("Comprobando actualizaciones...")
        release, error = await asyncio.to_thread(latest_release_info)
        if not release:
            show_message(error or "No hay actualizaciones disponibles.", error=bool(error and "última" not in error))
            return

        async def install_update(_: ft.ControlEvent) -> None:
            if page.dialog:
                page.dialog.open = False
                page.update()
            show_message(f"Descargando versión {release['version']}...")
            message = await asyncio.to_thread(install_update_from_release, release)
            show_message(message)

        def open_release(_: ft.ControlEvent) -> None:
            if release.get("html_url"):
                page.launch_url(release["html_url"])

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Nueva versión {release['version']}"),
            content=ft.Text("Hay una actualización disponible para el programa."),
            actions=[
                ft.TextButton("Ver en GitHub", on_click=open_release),
                ft.ElevatedButton("Actualizar", on_click=lambda event: page.run_task(install_update, event)),
                ft.TextButton("Cancelar", on_click=lambda _: close_dialog()),
            ],
        )
        page.dialog.open = True
        page.update()

    def close_dialog() -> None:
        if page.dialog:
            page.dialog.open = False
            page.update()

    def build_job_tab(
        title: str,
        description: str,
        action_label: str,
        needs_niche: bool,
        worker_factory,
    ) -> ft.Container:
        state = TabState()
        file_picker = ft.FilePicker()
        page.services.append(file_picker)

        state.file_text = ft.Text(
            "Ningun archivo seleccionado",
            size=12,
            color="#6B7280",
            selectable=True,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        state.progress = ft.ProgressBar(
            value=0,
            width=720,
            bar_height=8,
            color="#2563EB",
            bgcolor="#E5E7EB",
            border_radius=8,
        )
        state.status = ft.Text(
            "0% - Esperando archivo CSV",
            size=13,
            color="#374151",
            text_align=ft.TextAlign.CENTER,
        )
        state.result = ft.Text("", size=12, color="#047857", selectable=True)

        if needs_niche:
            state.niche_field = ft.TextField(
                label="Palabra clave del nicho",
                hint_text="Ejemplo: aceite, clinica, maquinaria",
                width=720,
                border_radius=8,
                border_color="#D1D5DB",
                focused_border_color="#2563EB",
                color="#111827",
                bgcolor="#FFFFFF",
                filled=True,
                fill_color="#FFFFFF",
                content_padding=ft.Padding(14, 12, 14, 12),
                on_change=lambda _: (update_buttons(state, needs_niche), page.update()),
            )

        async def choose_file(_: ft.ControlEvent) -> None:
            if state.running:
                return
            files = await file_picker.pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv"],
            )
            if files:
                state.csv_path = files[0].path or ""
                state.file_text.value = state.csv_path
                state.status.value = "0% - Archivo listo para procesar"
                state.result.value = ""
                state.progress.value = 0
            update_buttons(state, needs_niche)
            page.update()

        async def run_job() -> None:
            state.running = True
            update_buttons(state, needs_niche)
            state.result.value = ""
            state.progress.value = 0
            page.update()
            await asyncio.sleep(0.05)

            try:
                await worker_factory(state)
            except Exception as exc:
                state.status.value = "No se pudo completar el proceso."
                state.result.value = str(exc)
                show_message(f"Error: {exc}", error=True)
            finally:
                state.running = False
                update_buttons(state, needs_niche)
                page.update()

        def start_job(_: ft.ControlEvent) -> None:
            if state.running or not state.csv_path:
                return
            if needs_niche and not (state.niche_field.value if state.niche_field else "").strip():
                show_message("Introduce las etiquetas del nicho antes de empezar.", error=True)
                return
            page.run_task(run_job)

        outline_style, primary_style = make_button_styles()
        state.select_button = ft.OutlinedButton(
            content="Seleccionar CSV",
            icon=ft.Icons.UPLOAD_FILE_ROUNDED,
            on_click=choose_file,
            style=outline_style,
        )
        state.start_button = ft.ElevatedButton(
            content=action_label,
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=start_job,
            disabled=True,
            bgcolor="#9CA3AF",
            color="#FFFFFF",
            style=primary_style,
        )

        controls: list[ft.Control] = [
            ft.Text(title, size=22, weight=ft.FontWeight.W_700, color="#111827"),
            section_text(description),
            ft.Container(height=8),
        ]
        if state.niche_field:
            controls.extend([state.niche_field, ft.Container(height=2)])
        controls.extend(
            [
                ft.Row(
                    controls=[state.select_button, state.start_button],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=12,
                    wrap=True,
                ),
                state.file_text,
                ft.Container(height=14),
                state.progress,
                state.status,
                state.result,
            ]
        )

        return ft.Container(
            expand=True,
            padding=ft.Padding(28, 26, 28, 26),
            bgcolor="#FFFFFF",
            border=ft.Border.all(1, "#E5E7EB"),
            border_radius=12,
            content=ft.Column(
                controls=controls,
                spacing=13,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

    async def run_website_search(state: TabState) -> None:
        niche = state.niche_field.value if state.niche_field else ""
        rows = await asyncio.to_thread(read_companies_from_csv, state.csv_path, False)
        if not rows:
            raise ValueError("El CSV no contiene filas para procesar.")

        results: list[dict[str, str]] = []
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            company = row["Empresa"] or f"Fila {index}"
            await set_progress(state, (index - 1) / total, f"{int((index - 1) / total * 100)}% - Buscando web: {company}")
            found = await asyncio.to_thread(find_company_website, company, niche)
            results.append(
                {
                    "Empresa": row["Empresa"],
                    "Con nicho": found["Con nicho"],
                    "Sin nicho": found["Sin nicho"],
                }
            )
            await set_progress(state, index / total, f"{int(index / total * 100)}% - Completado: {company}")

        output = await asyncio.to_thread(
            save_results_to_excel,
            results,
            state.csv_path,
            "Resultados_Webs.xlsx",
            ["Empresa", "Con nicho", "Sin nicho"],
        )
        state.result.value = f"Archivo generado: {output}"
        state.status.value = "100% - Proceso terminado"
        state.progress.value = 1
        show_message("Busqueda de webs finalizada.")

    async def run_email_search(state: TabState) -> None:
        rows = await asyncio.to_thread(read_companies_from_csv, state.csv_path, True)
        if not rows:
            raise ValueError("El CSV no contiene filas para procesar.")

        results: list[dict[str, str]] = []
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            company = row["Empresa"] or f"Fila {index}"
            await set_progress(state, (index - 1) / total, f"{int((index - 1) / total * 100)}% - Buscando correo: {company}")
            email_result = await asyncio.to_thread(find_email_and_verify, row["Web"])
            results.append(
                {
                    "Empresa": row["Empresa"],
                    "Web": row["Web"],
                    "Correo Encontrado": email_result["Correo Encontrado"],
                    "Estado de Verificación": email_result["Estado de Verificación"],
                }
            )
            await set_progress(state, index / total, f"{int(index / total * 100)}% - Completado: {company}")

        output = await asyncio.to_thread(
            save_results_to_excel,
            results,
            state.csv_path,
            "Resultados_Correos.xlsx",
            ["Empresa", "Web", "Correo Encontrado", "Estado de Verificación"],
        )
        state.result.value = f"Archivo generado: {output}"
        state.status.value = "100% - Proceso terminado"
        state.progress.value = 1
        show_message("Busqueda de correos finalizada.")

    async def run_complete(state: TabState) -> None:
        niche = state.niche_field.value if state.niche_field else ""
        rows = await asyncio.to_thread(read_companies_from_csv, state.csv_path, False)
        if not rows:
            raise ValueError("El CSV no contiene filas para procesar.")

        results: list[dict[str, str]] = []
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            company = row["Empresa"] or f"Fila {index}"
            await set_progress(state, (index - 1) / total, f"{int((index - 1) / total * 100)}% - Proceso completo: {company}")
            complete_result = await asyncio.to_thread(run_complete_for_company, company, niche)
            results.append(
                {
                    "Empresa": row["Empresa"],
                    "Web Encontrada": complete_result["Web Encontrada"],
                    "Correo Encontrado": complete_result["Correo Encontrado"],
                    "Estado de Verificación": complete_result["Estado de Verificación"],
                }
            )
            await set_progress(state, index / total, f"{int(index / total * 100)}% - Completado: {company}")

        output = await asyncio.to_thread(
            save_results_to_excel,
            results,
            state.csv_path,
            "Resultados_Completo.xlsx",
            ["Empresa", "Web Encontrada", "Correo Encontrado", "Estado de Verificación"],
        )
        state.result.value = f"Archivo generado: {output}"
        state.status.value = "100% - Proceso terminado"
        state.progress.value = 1
        show_message("Proceso completo finalizado.")

    tabs = ft.Tabs(
        length=3,
        expand=True,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="Buscar Webs", icon=ft.Icons.TRAVEL_EXPLORE_ROUNDED),
                        ft.Tab(label="Buscar Correos", icon=ft.Icons.ALTERNATE_EMAIL_ROUNDED),
                        ft.Tab(label="Proceso Completo", icon=ft.Icons.AUTO_AWESOME_ROUNDED),
                    ],
                    label_color="#111827",
                    unselected_label_color="#6B7280",
                    indicator_color="#2563EB",
                    divider_color="#E5E7EB",
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        build_job_tab(
                            "Buscar Webs de Empresas",
                            "Busca el primer resultado de cada empresa y comprueba si esa web contiene la palabra clave.",
                            "Buscar Webs",
                            True,
                            run_website_search,
                        ),
                        build_job_tab(
                            "Buscar Correos en Webs",
                            "Carga un CSV con Empresa y Web. La app rastrea correos y verifica el servidor de correo.",
                            "Buscar Correos",
                            False,
                            run_email_search,
                        ),
                        build_job_tab(
                            "Proceso Completo Automatizado",
                            "Carga empresas, encuentra el primer resultado web, busca emails y valida cada correo.",
                            "Ejecutar Todo",
                            False,
                            run_complete,
                        ),
                    ],
                ),
            ],
        ),
    )

    update_button = ft.OutlinedButton(
        content="Actualizar",
        icon=ft.Icons.DOWNLOAD_ROUNDED,
        on_click=lambda _: page.run_task(check_updates_from_ui),
        style=make_button_styles()[0],
    )
    header = ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Text("Scraper corporativo", size=28, weight=ft.FontWeight.W_700, color="#111827"),
                    ft.Text(
                        "Tres flujos independientes para localizar webs, extraer correos y validar resultados.",
                        size=14,
                        color="#6B7280",
                    ),
                    ft.Text(f"Versión {APP_VERSION}", size=11, color="#9CA3AF"),
                ],
                spacing=4,
                expand=True,
            ),
            update_button,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    def show_main_app() -> None:
        page.clean()
        page.add(
            ft.Container(
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[header, ft.Container(height=12), tabs],
                    spacing=10,
                ),
            )
        )
        page.update()

    login_name = ft.TextField(
        label="Nombre de acceso",
        hint_text="Introduce tu nombre",
        width=360,
        border_radius=8,
        border_color="#D1D5DB",
        focused_border_color="#2563EB",
        color="#111827",
        bgcolor="#FFFFFF",
        filled=True,
        fill_color="#FFFFFF",
        content_padding=ft.Padding(14, 12, 14, 12),
        autofocus=True,
    )
    login_status = ft.Text("", size=12, color="#B91C1C", text_align=ft.TextAlign.CENTER)
    login_button = ft.ElevatedButton(
        content="Entrar",
        icon=ft.Icons.LOGIN_ROUNDED,
        bgcolor="#2563EB",
        color="#FFFFFF",
        style=make_button_styles()[1],
    )

    async def do_login() -> None:
        login_button.disabled = True
        login_status.value = "Comprobando acceso..."
        page.update(login_button, login_status)
        allowed, message = await asyncio.to_thread(check_remote_login, login_name.value)
        if allowed:
            show_main_app()
            return
        login_status.value = message
        login_button.disabled = False
        page.update(login_button, login_status)

    def login_click(_: ft.ControlEvent) -> None:
        page.run_task(do_login)

    login_button.on_click = login_click
    login_name.on_submit = login_click

    page.add(
        ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Container(
                width=440,
                padding=ft.Padding(34, 32, 34, 32),
                bgcolor="#FFFFFF",
                border=ft.Border.all(1, "#E5E7EB"),
                border_radius=12,
                content=ft.Column(
                    controls=[
                        ft.Text("Acceso privado", size=26, weight=ft.FontWeight.W_700, color="#111827"),
                        ft.Text(
                            "Introduce un nombre autorizado desde Telegram.",
                            size=13,
                            color="#6B7280",
                        ),
                        ft.Container(height=10),
                        login_name,
                        login_button,
                        login_status,
                    ],
                    spacing=14,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    tight=True,
                ),
            ),
        )
    )


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.FLET_APP)
