"""URL normalisation and reachability checks."""

import html
import re
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 awesome-bot"
)

TRACKING_PARAM = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|si)$", re.I)
CASE_INSENSITIVE_HOSTS = {"github.com", "gitlab.com", "youtube.com", "reddit.com"}
SHORTENERS = {
    "a.co", "amzn.to", "bit.ly", "buff.ly", "cutt.ly", "goo.gl", "is.gd", "ow.ly",
    "rebrand.ly", "shorturl.at", "t.co", "tinyurl.com", "youtu.be",
}
# Statuses that usually mean "a bot was blocked" or "try later", not "the page is gone".
INCONCLUSIVE_STATUSES = {401, 403, 405, 406, 408, 425, 429, 451, 500, 502, 503, 504, 520, 521, 522, 523, 524, 999}


def is_valid_url(url):
    if not url or any(c.isspace() or c in "`\"<>\\" for c in url):
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname) and "." in parts.hostname


def host_of(url):
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_shortener(url):
    return host_of(url) in SHORTENERS


def normalize_url(url):
    """Comparison key for duplicate detection: scheme, www., trailing slash and tracking params ignored."""
    parts = urlsplit(url.strip())
    host = host_of(url)
    if host.startswith("m.") and host[2:] in CASE_INSENSITIVE_HOSTS:
        host = host[2:]
    path = parts.path.rstrip("/")
    if host in CASE_INSENSITIVE_HOSTS:
        path = path.lower()
    if host == "github.com" and path.endswith(".git"):
        path = path[:-4]
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAM.match(k)
    ))
    return host + path + (f"?{query}" if query else "")


@dataclass
class LinkCheck:
    ok: object  # True = reachable, False = broken, None = could not tell
    status: object = None
    final_url: str = ""
    title: str = ""
    description: str = ""
    error: str = ""

    def summary(self):
        if self.ok:
            return f"reachable (HTTP {self.status})"
        return self.error or "unknown"


def check_url(url, timeout=20):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(400_000) if "html" in content_type else b""
            title, description = extract_meta(body.decode(charset, "replace"))
            return LinkCheck(True, response.status, response.geturl(), title, description)
    except urllib.error.HTTPError as e:
        if e.code in INCONCLUSIVE_STATUSES:
            return LinkCheck(None, e.code, url, error=f"HTTP {e.code}, possibly bot protection")
        return LinkCheck(False, e.code, url, error=f"HTTP {e.code}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.gaierror):
            return LinkCheck(False, None, url, error="domain does not resolve")
        if isinstance(e.reason, ssl.SSLError):
            return LinkCheck(None, None, url, error=f"TLS error: {e.reason}")
        return LinkCheck(None, None, url, error=f"connection failed: {e.reason}")
    except (TimeoutError, socket.timeout):
        return LinkCheck(None, None, url, error="timed out")
    except (ConnectionError, ssl.SSLError, ValueError) as e:
        return LinkCheck(None, None, url, error=f"connection failed: {e}")


META_TAG = re.compile(r"<meta\s[^>]*>", re.I)
ATTR = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _clean(text, limit=300):
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()[:limit]


def extract_meta(page):
    match = TITLE.search(page)
    title = _clean(match.group(1)) if match else ""
    description = ""
    for tag in META_TAG.findall(page):
        attrs = {k.lower(): (a if a is not None else b) for k, a, b in ATTR.findall(tag)}
        key = (attrs.get("name") or attrs.get("property") or "").lower()
        if key in ("description", "og:description") and attrs.get("content"):
            description = _clean(attrs["content"])
            if key == "description":
                break
    return title, description
