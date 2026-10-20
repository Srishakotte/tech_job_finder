import json
import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ..config import load_environment

load_environment()

BASE_URL = "https://teraboxlinks.com"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
})


def get_tokens(url, http_session=SESSION):
    """Get CSRF + CakePHP-style form tokens from a page."""
    response = http_session.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    def value(name):
        element = soup.find("input", {"name": name})
        return element.get("value", "") if element else ""

    return {
        "csrf": value("_csrfToken"),
        "fields": value("_Token[fields]"),
        "unlocked": value("_Token[unlocked]"),
    }


def login(http_session=SESSION):
    username = os.getenv("TERABOXLINKS_USERNAME")
    password = os.getenv("TERABOXLINKS_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "Set TERABOXLINKS_USERNAME and TERABOXLINKS_PASSWORD in .env."
        )

    tokens = get_tokens(f"{BASE_URL}/auth/signin", http_session)
    data = {
        "_method": "POST",
        "_csrfToken": tokens["csrf"],
        "username": username,
        "password": password,
        "remember_me": "0",
        "_Token[fields]": tokens["fields"],
        "_Token[unlocked]": tokens["unlocked"],
    }

    response = http_session.post(
        f"{BASE_URL}/auth/signin",
        data=data,
        allow_redirects=False,
        timeout=30,
    )

    if response.status_code != 302 or not response.headers.get("Location"):
        raise RuntimeError(
            f"Shortener login failed (HTTP {response.status_code})."
        )

    dashboard_url = urljoin(
        BASE_URL,
        response.headers["Location"],
    )
    dashboard = http_session.get(dashboard_url, timeout=30)
    dashboard.raise_for_status()

    if urlparse(dashboard.url).path.rstrip("/") == "/auth/signin":
        raise RuntimeError("Shortener login was rejected; check the credentials.")

    return True


def shorten(long_url, alias="", http_session=SESSION):
    tokens = get_tokens(f"{BASE_URL}/member/dashboard", http_session)
    data = {
        "_method": "POST",
        "_csrfToken": tokens["csrf"],
        "url": long_url,
        "alias": alias,
        "expiration[year]": "",
        "expiration[month]": "",
        "expiration[day]": "",
        "expiration[hour]": "",
        "expiration[minute]": "",
        "ad_type": "2",
        "_Token[fields]": tokens["fields"],
        "_Token[unlocked]": (
            "adcopy_challenge|"
            "adcopy_response|"
            "captcha_code|"
            "captcha_namespace|"
            "g-recaptcha-response"
        ),
    }

    response = http_session.post(
        f"{BASE_URL}/links/shorten",
        data=data,
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE_URL}/member/dashboard",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response


def _response_urls(payload):
    found = []

    def visit(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            urls = re.findall(r"https?://[^\s<>\"']+", value)
            for url in urls:
                found.append((key.lower(), url.rstrip(".,);]}>")))

    visit(payload)
    return found


def extract_short_link(response, original_url):
    """Extract the generated URL from a JSON or HTML shortening response."""
    candidates = []

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None

    if payload is not None:
        candidates.extend(_response_urls(payload))
    else:
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup.find_all(["a", "input"]):
            value = element.get("href") or element.get("value") or ""
            if value.startswith(("http://", "https://")):
                candidates.append(
                    (element.get("name", "").lower(), value.rstrip(".,);]}>"))
                )
        candidates.extend(_response_urls(soup.get_text(" ", strip=True)))

    original = original_url.rstrip("/")
    valid = []
    for key, candidate in candidates:
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        if candidate.rstrip("/") == original:
            continue
        host = parsed.hostname.lower()
        if host != "teraboxlinks.com" and not host.endswith(".teraboxlinks.com"):
            continue
        if parsed.path.rstrip("/") in {"", "/auth/signin", "/member/dashboard"}:
            continue
        valid.append((key, candidate))

    for key, candidate in valid:
        if any(term in key for term in ("short", "alias", "generated")):
            return candidate

    if valid:
        return valid[0][1]

    raise RuntimeError("The shortener response did not contain a valid short URL.")


def create_short_link(long_url, alias=""):
    http_session = requests.Session()
    http_session.headers.update(SESSION.headers)
    login(http_session)
    response = shorten(long_url, alias, http_session)
    return extract_short_link(response, long_url)


if __name__ == "__main__":
    url = input("Enter URL to shorten: ").strip()
    alias = input("Enter alias (optional): ").strip()
    print(create_short_link(url, alias))
