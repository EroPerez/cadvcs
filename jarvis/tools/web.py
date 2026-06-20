import platform
import subprocess
from urllib.parse import quote

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
}


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://", "ftp://")):
        url = "https://" + url
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.Popen(["xdg-open", url])
        elif system == "Darwin":
            subprocess.Popen(["open", url])
        return f"Abriendo en navegador: {url}"
    except Exception as e:
        return f"Error al abrir URL: {e}"


def web_search(query: str, engine: str = "google") -> str:
    template = SEARCH_URLS.get(engine, SEARCH_URLS["google"])
    url = template.format(quote(query))
    return open_url(url)
