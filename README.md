# ScraperCorreos

Aplicación de escritorio en Flet para buscar webs, correos corporativos y validar resultados.

## Login con Supabase

La app consulta Supabase al arrancar. El usuario escribe un nombre y Supabase responde si está autorizado.

Tabla creada:

- `public.app_allowed_logins`

Función pública:

- `public.check_scraper_access(input_name text)`

La app necesita una configuración `scraper_config.json` junto al `.exe` o en:

`%APPDATA%\ScraperCorreos\scraper_config.json`

Ejemplo:

```json
{
  "supabase_url": "https://ziyrtaxmvxfzsondcxph.supabase.co",
  "supabase_anon_key": "ANON_PUBLIC_KEY",
  "github_repo": "guille2005/Scrapper",
  "github_release_asset": "ScraperCorreos.exe"
}
```

## Bot de Telegram

El bot está en `telegram_access_bot.py`. Se deja corriendo en tu ordenador o servidor.

Configuración en:

`%APPDATA%\ScraperCorreos\telegram_bot_config.json`

Ejemplo:

```json
{
  "telegram_bot_token": "TOKEN_DEL_BOT",
  "supabase_url": "https://ziyrtaxmvxfzsondcxph.supabase.co",
  "supabase_anon_key": "ANON_PUBLIC_KEY",
  "bot_admin_secret": "CLAVE_INTERNA_DEL_BOT"
}
```

Uso:

- Escribir `Joel` al bot crea o activa el acceso `Joel`.
- Escribir `/borrar Joel` desactiva ese acceso.

## Actualizaciones por GitHub Releases

La app puede mirar la última release de GitHub si `github_repo` está configurado.

Para construir:

```powershell
.\build_release.ps1
```

Para publicar una release:

```powershell
$env:GITHUB_TOKEN="TOKEN_DE_GITHUB"
$env:SCRAPER_GITHUB_REPO="guille2005/Scrapper"
.\publish_github_release.ps1 -Version "v0.3.1"
```

La release debe incluir el asset `ScraperCorreos.exe`.
