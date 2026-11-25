from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape


def _dt(value: str | None) -> datetime:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def sitemap_xml(rows: list[dict[str, Any]]) -> str:
    items = "".join(
        f"<url><loc>{escape(r['url'])}</loc><lastmod>{_dt(r.get('updated_at')).isoformat()}</lastmod></url>"
        for r in rows
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    )


def rss_xml(
    rows: list[dict[str, Any]], title: str, link: str, self_url: str | None = None, hub_url: str | None = None
) -> str:
    items = "".join(
        f"<item><title>{escape(r['url'])}</title><link>{escape(r['url'])}</link>"
        f'<guid isPermaLink="true">{escape(r["url"])}</guid>'
        f"<pubDate>{format_datetime(_dt(r.get('updated_at')))}</pubDate></item>"
        for r in rows
    )
    atom = ""
    if self_url:
        atom += f'<atom:link rel="self" type="application/rss+xml" href="{escape(self_url)}"/>'
    if hub_url:  # WebSub: tells subscribers which hub pushes updates for this feed
        atom += f'<atom:link rel="hub" href="{escape(hub_url)}"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>{escape(title)}</title><link>{escape(link)}</link>{atom}"
        f"<description>{escape(title)}</description>{items}</channel></rss>"
    )
