#!/usr/bin/env python3
"""Fetch today's Resmi Gazete and email a plain title+link digest.

Pipeline:
  1. Download the daily archive page from resmigazete.gov.tr.
  2. Parse it into {category: [ {title, url}, ... ]} using a heading-then-links
     heuristic (the site's markup isn't guaranteed to have stable CSS classes,
     so this avoids depending on exact selectors).
  3. Render that into a simple grouped HTML list (no AI summarization).
  4. Send the email via the Resend API.

Environment variables:
  TO_EMAIL            required  recipient address
  FROM_EMAIL          required  verified sender address (Resend)
  RESEND_API_KEY       required
  GAZETTE_DATE          optional  override date as YYYY-MM-DD (default: today, Europe/Istanbul)
"""
from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
import urllib3
from bs4 import BeautifulSoup

# We deliberately retry with verify=False for this one known-broken site
# (see fetch_page); suppress the resulting per-request warning noise.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GAZETTE_BASE = "https://www.resmigazete.gov.tr"
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:")
USER_AGENT = (
    "Mozilla/5.0 (compatible; ResmiGazeteDigestBot/1.0; "
    "+https://github.com/erhanere/HR-Report)"
)


@dataclass
class GazetteItem:
    title: str
    url: str


@dataclass
class GazetteDay:
    date: str
    source_url: str
    categories: dict[str, list[GazetteItem]] = field(default_factory=dict)

    @property
    def item_count(self) -> int:
        return sum(len(items) for items in self.categories.values())


def gazette_url_for(date: datetime) -> str:
    return f"{GAZETTE_BASE}/eskiler/{date:%Y}/{date:%m}/{date:%Y%m%d}.htm"


def fetch_page(url: str) -> requests.Response:
    headers = {"User-Agent": USER_AGENT}
    try:
        return requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.SSLError:
        # resmigazete.gov.tr is known to serve an incomplete certificate
        # chain, which fails strict verification even though the content
        # itself is a public, non-sensitive government publication. Retry
        # once without verification rather than failing the whole run.
        print(
            f"WARNING: TLS verification failed for {url}; retrying without "
            "certificate verification (known incomplete chain on this site).",
            file=sys.stderr,
        )
        return requests.get(url, headers=headers, timeout=30, verify=False)


def _looks_like_heading(tag) -> bool:
    """Heuristic for section headers that aren't real <h1>-<h6> tags.

    Resmi Gazete section titles ("YÜRÜTME VE İDARE BÖLÜMÜ", "İLAN BÖLÜMÜ", ...)
    are short, upper-case, Turkish lines rendered as bold text rather than
    semantic headings.
    """
    if tag.name not in {"p", "div", "span", "strong", "b"}:
        return False
    if tag.find("a") is not None:
        return False
    text = tag.get_text(strip=True)
    if not text or text.upper() != text:
        return False
    if not (5 <= len(text) <= 100):
        return False
    return True


def parse_gazette(html: str, source_url: str, date_str: str) -> GazetteDay:
    soup = BeautifulSoup(html, "html.parser")
    day = GazetteDay(date=date_str, source_url=source_url)

    current_category = "Genel"
    seen_urls: set[str] = set()

    for tag in soup.find_all(True):
        if tag.name in HEADING_TAGS or _looks_like_heading(tag):
            text = tag.get_text(strip=True)
            if text:
                current_category = text
            continue

        if tag.name != "a":
            continue

        href = tag.get("href")
        text = tag.get_text(strip=True)
        if not href or not text or len(text) < 4:
            continue
        if href.startswith(SKIP_HREF_PREFIXES):
            continue

        absolute_url = urljoin(source_url, href)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)

        day.categories.setdefault(current_category, []).append(
            GazetteItem(title=text, url=absolute_url)
        )

    return day


def build_email_html(day: GazetteDay) -> tuple[str, str]:
    """Return (subject, html_body) — a plain grouped list, no summarization."""
    subject = f"Resmi Gazete - {day.date}"

    if day.item_count == 0:
        body = (
            f"<p>{day.date} tarihli Resmi Gazete için ayrıştırılabilen bir madde "
            f"bulunamadı.</p>"
            f'<p>Kaynak sayfa: <a href="{html.escape(day.source_url)}">'
            f"{html.escape(day.source_url)}</a></p>"
        )
        return subject, body

    sections = []
    for category, items in day.categories.items():
        rows = "\n".join(
            f'<li><a href="{html.escape(item.url)}">{html.escape(item.title)}</a></li>'
            for item in items
        )
        sections.append(
            f"<h3>{html.escape(category)}</h3>\n<ul>\n{rows}\n</ul>"
        )

    body = (
        f"<p>{day.date} tarihli Resmi Gazete "
        f'(<a href="{html.escape(day.source_url)}">kaynak</a>) — '
        f"{day.item_count} madde:</p>\n" + "\n".join(sections)
    )
    return subject, body


def send_email(subject: str, html_body: str) -> None:
    to_email = os.environ["TO_EMAIL"]
    from_email = os.environ["FROM_EMAIL"]
    api_key = os.environ["RESEND_API_KEY"]

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Resend API error {resp.status_code}: {resp.text}"
        )


def main() -> int:
    tz = ZoneInfo("Europe/Istanbul")
    date_override = os.environ.get("GAZETTE_DATE")
    target_date = (
        datetime.strptime(date_override, "%Y-%m-%d").replace(tzinfo=tz)
        if date_override
        else datetime.now(tz)
    )
    date_str = target_date.strftime("%d.%m.%Y")
    source_url = gazette_url_for(target_date)

    print(f"Fetching {source_url}", file=sys.stderr)
    resp = fetch_page(source_url)

    if resp.status_code == 404:
        day = GazetteDay(date=date_str, source_url=source_url)
    else:
        resp.raise_for_status()
        day = parse_gazette(resp.text, source_url, date_str)

    print(f"Parsed {day.item_count} items across {len(day.categories)} categories",
          file=sys.stderr)

    # Debug artifact so a bad parse is easy to diagnose from the workflow run.
    with open("gazette_items.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "date": day.date,
                "source_url": day.source_url,
                "categories": {
                    cat: [item.__dict__ for item in items]
                    for cat, items in day.categories.items()
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    subject, html_body = build_email_html(day)
    send_email(subject, html_body)
    print("Email sent.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
