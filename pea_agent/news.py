from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from pea_agent.models import NewsItem

_RISK_TERMS = {
    "bankruptcy": "possible insolvency / bankruptcy",
    "fraud": "possible fraud allegation",
    "accounting scandal": "possible accounting scandal",
    "profit warning": "profit warning",
    "investigation": "regulatory or legal investigation",
    "delisted": "possible delisting",
    "removed from the cac 40": "reported CAC 40 removal",
    "cac 40 exclusion": "reported CAC 40 removal",
}


def _risk_flags(text: str) -> tuple[str, ...]:
    normalized = text.lower()
    return tuple(description for term, description in _RISK_TERMS.items() if term in normalized)


def _symbol_matches(text: str, symbols: tuple[str, ...]) -> tuple[str, ...]:
    normalized = text.upper()
    matched = []
    for symbol in symbols:
        ticker = symbol.upper().split(".", 1)[0]
        if re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", normalized):
            matched.append(symbol)
    return tuple(matched)


def search_market_news(symbols: tuple[str, ...], max_results: int = 8) -> tuple[NewsItem, ...]:
    try:
        from ddgs import DDGS
    except ImportError as error:
        raise RuntimeError("Install the 'ddgs' package to enable web search.") from error
    query = "CAC 40 France markets " + " ".join(symbols[:8])
    try:
        results = DDGS().text(query, max_results=max_results)
        items = []
        for result in results:
            title = str(result.get("title", "")).strip()
            summary = str(result.get("body", "")).strip()
            url = str(result.get("href", "")).strip()
            combined = f"{title} {summary}"
            items.append(
                NewsItem(
                    title=title or url,
                    summary=summary,
                    url=url,
                    source=urlparse(url).hostname or "Web search",
                    kind="market_search",
                    related_symbols=_symbol_matches(combined, symbols),
                    risk_flags=_risk_flags(combined),
                )
            )
        return tuple(items)
    except Exception as error:
        raise RuntimeError(f"Market news search failed: {error}") from error


def _validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"URL must be a public http(s) address without embedded credentials: {url}")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except OSError as error:
        raise ValueError(f"Could not resolve URL host {parsed.hostname}: {error}") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError(f"URL host must resolve only to public IP addresses: {parsed.hostname}")


def fetch_user_urls(urls: tuple[str, ...], symbols: tuple[str, ...], timeout: float = 10.0) -> tuple[NewsItem, ...]:
    items = []
    session = requests.Session()
    session.headers.update({"User-Agent": "PEA-Portfolio-Market-Analytics-Agent/0.1"})
    for url in urls:
        clean_url = url.strip()
        if not clean_url:
            continue
        _validate_public_http_url(clean_url)
        try:
            response = session.get(clean_url, timeout=timeout, allow_redirects=False)
            if response.is_redirect:
                raise ValueError(f"Redirected URL is not fetched automatically: {clean_url}")
            response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(f"Could not fetch user-provided URL {clean_url}: {error}") from error
        if len(response.content) > 2_000_000:
            raise ValueError(f"URL response exceeds the 2 MB limit: {clean_url}")
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else clean_url
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        summary = text[:1200]
        combined = f"{title} {summary}"
        items.append(
            NewsItem(
                title=title,
                summary=summary or "No readable article text found.",
                url=clean_url,
                source=urlparse(clean_url).hostname or "User URL",
                kind="user_url",
                related_symbols=_symbol_matches(combined, symbols),
                risk_flags=_risk_flags(combined),
            )
        )
    return tuple(items)


def analyze_user_text(text: str, symbols: tuple[str, ...]) -> tuple[NewsItem, ...]:
    clean_text = text.strip()
    if not clean_text:
        return ()
    return (
        NewsItem(
            title="User-provided market notes",
            summary=clean_text[:2000],
            url="",
            source="User input",
            kind="user_text",
            related_symbols=_symbol_matches(clean_text, symbols),
            risk_flags=_risk_flags(clean_text),
        ),
    )
