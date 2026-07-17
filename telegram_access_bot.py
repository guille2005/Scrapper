import json
import os
import re
import time
from pathlib import Path

import requests


SUPABASE_URL = "https://ziyrtaxmvxfzsondcxph.supabase.co"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    folder = Path(base) / "ScraperCorreos" if base else Path.home() / ".scraper_correos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load_config() -> dict[str, str]:
    config = {
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "supabase_url": os.environ.get("SCRAPER_SUPABASE_URL", SUPABASE_URL),
        "supabase_anon_key": os.environ.get("SCRAPER_SUPABASE_ANON_KEY", ""),
        "bot_admin_secret": os.environ.get("SCRAPER_BOT_ADMIN_SECRET", ""),
        "supabase_service_role_key": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    }

    config_path = app_data_dir() / "telegram_bot_config.json"
    if config_path.exists():
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            file_config = {}
        for key, value in file_config.items():
            if isinstance(value, str) and value.strip():
                config[key] = value.strip()

    return config


CONFIG = load_config()


def normalize_login(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().lower())


def supabase_headers() -> dict[str, str]:
    key = CONFIG["supabase_anon_key"] or CONFIG["supabase_service_role_key"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }


def add_login(name: str, telegram_user_id: int | None, telegram_username: str | None) -> bool:
    normalized = normalize_login(name)
    if not normalized:
        return False

    if CONFIG.get("bot_admin_secret"):
        url = f"{CONFIG['supabase_url'].rstrip('/')}/rest/v1/rpc/upsert_scraper_access"
        payload = {
            "admin_secret": CONFIG["bot_admin_secret"],
            "input_name": name.strip(),
            "input_telegram_user_id": telegram_user_id,
            "input_telegram_username": telegram_username,
        }
        response = requests.post(url, headers=supabase_headers(), json=payload, timeout=15)
        response.raise_for_status()
        return bool(response.json())

    url = f"{CONFIG['supabase_url'].rstrip('/')}/rest/v1/app_allowed_logins?on_conflict=normalized_login"
    payload = {
        "login_name": name.strip(),
        "normalized_login": normalized,
        "is_active": True,
        "telegram_user_id": telegram_user_id,
        "telegram_username": telegram_username,
        "created_by": "telegram",
    }
    response = requests.post(url, headers=supabase_headers(), json=payload, timeout=15)
    response.raise_for_status()
    return True


def disable_login(name: str) -> bool:
    normalized = normalize_login(name)
    if not normalized:
        return False

    if CONFIG.get("bot_admin_secret"):
        url = f"{CONFIG['supabase_url'].rstrip('/')}/rest/v1/rpc/disable_scraper_access"
        payload = {
            "admin_secret": CONFIG["bot_admin_secret"],
            "input_name": name.strip(),
        }
        response = requests.post(url, headers=supabase_headers(), json=payload, timeout=15)
        response.raise_for_status()
        return bool(response.json())

    url = f"{CONFIG['supabase_url'].rstrip('/')}/rest/v1/app_allowed_logins?normalized_login=eq.{normalized}"
    response = requests.patch(url, headers=supabase_headers(), json={"is_active": False}, timeout=15)
    response.raise_for_status()
    return True


def list_logins() -> list[dict]:
    if CONFIG.get("bot_admin_secret"):
        url = f"{CONFIG['supabase_url'].rstrip('/')}/rest/v1/rpc/list_scraper_access"
        payload = {"admin_secret": CONFIG["bot_admin_secret"]}
        response = requests.post(url, headers=supabase_headers(), json=payload, timeout=15)
        response.raise_for_status()
        return response.json()

    url = (
        f"{CONFIG['supabase_url'].rstrip('/')}/rest/v1/app_allowed_logins"
        "?select=login_name,telegram_username,created_at,updated_at"
        "&is_active=eq.true"
        "&order=login_name.asc"
    )
    response = requests.get(url, headers=supabase_headers(), timeout=15)
    response.raise_for_status()
    return response.json()


def format_logins(logins: list[dict]) -> str:
    if not logins:
        return "No hay licencias activas."

    lines = [f"Licencias activas: {len(logins)}"]
    for index, login in enumerate(logins, start=1):
        name = login.get("login_name") or "Sin nombre"
        username = login.get("telegram_username") or ""
        suffix = f" (@{username})" if username and username != "setup" else ""
        lines.append(f"{index}. {name}{suffix}")
    return "\n".join(lines)


def send_message(chat_id: int, text: str) -> None:
    token = CONFIG["telegram_bot_token"]
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


def handle_message(message: dict) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    user = message.get("from", {})
    telegram_user_id = user.get("id")
    telegram_username = user.get("username")

    if not chat_id or not text:
        return

    if text.lower() in {"/start", "/help"}:
        send_message(
            chat_id,
            "\n".join(
                [
                    "Comandos:",
                    "/licencias - ver accesos activos",
                    "/borrar Nombre - desactivar un acceso",
                    "Nombre - crear o activar un acceso",
                ]
            ),
        )
        return

    if text.lower() in {"/licencias", "/lista", "/listar"}:
        try:
            send_message(chat_id, format_logins(list_logins()))
        except Exception as exc:
            send_message(chat_id, f"No pude leer las licencias: {exc}")
        return

    if text.lower().startswith("/borrar "):
        name = text[8:].strip()
        try:
            disable_login(name)
            send_message(chat_id, f"Acceso desactivado: {name}")
        except Exception as exc:
            send_message(chat_id, f"No pude desactivar ese acceso: {exc}")
        return

    if text.startswith("/"):
        send_message(chat_id, "Comando no reconocido. Usa /help.")
        return

    try:
        add_login(text, telegram_user_id, telegram_username)
        send_message(chat_id, f"Acceso creado o activado: {text}")
    except Exception as exc:
        send_message(chat_id, f"No pude crear el acceso: {exc}")


def run_bot() -> None:
    if not CONFIG["telegram_bot_token"]:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN o telegram_bot_config.json")
    if not CONFIG["supabase_anon_key"] and not CONFIG["supabase_service_role_key"]:
        raise RuntimeError("Falta SCRAPER_SUPABASE_ANON_KEY o SUPABASE_SERVICE_ROLE_KEY")
    if not CONFIG["bot_admin_secret"] and not CONFIG["supabase_service_role_key"]:
        raise RuntimeError("Falta SCRAPER_BOT_ADMIN_SECRET o SUPABASE_SERVICE_ROLE_KEY")

    token = CONFIG["telegram_bot_token"]
    offset = 0
    print("Bot de accesos iniciado.")

    while True:
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=40,
            )
            response.raise_for_status()
            updates = response.json().get("result", [])
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                if "message" in update:
                    handle_message(update["message"])
        except Exception as exc:
            print(f"Error del bot: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    run_bot()
