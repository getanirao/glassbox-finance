"""Article body scraping + LLM summarization for enhanced sentiment."""
import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_SCRAPE_TIMEOUT = 15
_SUMMARIZE_TIMEOUT = 30

_SUMMARIZE_PROMPT = (
    "Summarize this financial news article in 2-3 sentences. "
    "Focus on facts that could affect the stock price. "
    "Include the direction (positive/negative/neutral) in your summary.\n\n"
    "Article:\n{text}\n\nSummary:"
)


def fetch_article(url):
    """Scrape the main body text from a news article URL.

    Returns cleaned text string, or None on failure.
    """
    if not url or not isinstance(url, str):
        return None

    # Skip video-only and non-article URLs
    if "/video/" in url:
        logger.debug("Skipping video URL: %s", url)
        return None

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_SCRAPE_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script/style elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try common article containers first
    for selector in [
        "article",
        '[role="article"]',
        ".article-body",
        ".article-content",
        ".story-body",
        ".post-content",
        ".entry-content",
        '[itemprop="articleBody"]',
    ]:
        container = soup.select_one(selector)
        if container:
            text = container.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # Fallback: main content area
    for selector in ["main", "#content", ".content", ".main"]:
        container = soup.select_one(selector)
        if container:
            text = container.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # Last resort: body text
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        text = _clean_text(text)
        if len(text) > 300:
            return text

    return None


def _clean_text(text):
    """Normalize whitespace and truncate to reasonable length."""
    text = re.sub(r"\s+", " ", text).strip()
    # Truncate at 4000 chars to fit LLM context windows
    if len(text) > 4000:
        text = text[:3997] + "..."
    return text


def _call_openai(text, api_key, model="gpt-4o-mini"):
    """Summarize via OpenAI API."""
    import json

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "You summarize financial news concisely."},
                {"role": "user", "content": _SUMMARIZE_PROMPT.format(text=text)},
            ],
            "max_tokens": 200,
            "temperature": 0.3,
        },
        timeout=_SUMMARIZE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_anthropic(text, api_key, model="claude-3-haiku-20240307"):
    """Summarize via Anthropic API."""
    import json

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 200,
            "messages": [
                {"role": "user", "content": _SUMMARIZE_PROMPT.format(text=text)},
            ],
        },
        timeout=_SUMMARIZE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_gemini(text, api_key, model="gemini-2.0-flash"):
    """Summarize via Google Gemini API."""
    import json

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [
                {"parts": [{"text": _SUMMARIZE_PROMPT.format(text=text)}]}
            ],
            "generationConfig": {
                "maxOutputTokens": 200,
                "temperature": 0.3,
            },
        },
        timeout=_SUMMARIZE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


_PROVIDERS = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
}


def summarize(text, provider="openai", api_key=None):
    """Send text to an LLM for financial summarization.

    Args:
        text: Article body text.
        provider: "openai", "anthropic", or "gemini".
        api_key: API key. Falls back to env var (LLM_API_KEY).

    Returns:
        Summary string, or the original text truncated on failure.
    """
    if not text or len(text) < 100:
        return text

    caller = _PROVIDERS.get(provider)
    if not caller:
        logger.warning("Unknown LLM provider: %s", provider)
        return text[:500]

    if not api_key:
        api_key = os.environ.get(f"{provider.upper()}_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        logger.warning("No API key for %s summarization", provider)
        return text[:500]

    try:
        summary = caller(text, api_key)
        logger.debug("Summarized %d chars -> %d chars", len(text), len(summary))
        return summary
    except Exception as exc:
        logger.warning("Summarization failed: %s", exc)
        return text[:500]


def extract_article_lead(url, max_lines=3):
    """Fetch article and return the first ~max_lines of body text.

    No LLM call, no API key — just raw text for model scoring.
    Returns string or None on failure.
    """
    body = fetch_article(url)
    if not body:
        return None
    lines = [l.strip() for l in body.split(". ") if l.strip()]
    lead = ". ".join(lines[:max_lines])
    if not lead.endswith("."):
        lead += "."
    if len(lead) > 2000:
        lead = lead[:1997] + "..."
    return lead


def summarize_article(url, provider="openai", api_key=None):
    """Fetch article from URL and summarize it.

    Returns (summary_text, original_text) tuple, or (None, None) on failure.
    """
    body = fetch_article(url)
    if not body:
        return None, None
    summary = summarize(body, provider=provider, api_key=api_key)
    return summary, body
