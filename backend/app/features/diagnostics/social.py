"""Social platforms: what they generally allow search engines to index.

This is GUIDANCE, not a verdict. The live check of the page (noindex, robots, canonical) is the evidence; these notes explain
the usual reason behind it and what the customer can do. Wording is deliberately hedged ("usually", "often"): platforms change
their rules, and a page may behave differently for a logged-out crawler than for a logged-in visitor.

The same list exists in the frontend (frontend/src/features/submission/lib/social.ts) so the Submit page can warn before a
customer submits. tests/test_social.py fails if the two lists drift apart.
"""
from urllib.parse import urlsplit

# name -> (hosts, advice). Hosts match exactly or as a subdomain.
PLATFORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "facebook": (
        ("facebook.com", "fb.com", "fb.watch"),
        "Facebook posts are usually not indexed: they are often marked noindex or need a login, and share links redirect to the real post.",
    ),
    "instagram": (
        ("instagram.com",),
        "Instagram posts are rarely indexed, and links in them are nofollow.",
    ),
    "x": (
        ("x.com", "twitter.com"),
        "Public X posts are sometimes indexed, but X often asks crawlers to log in, and links in posts are nofollow.",
    ),
    "linkedin": (
        ("linkedin.com",),
        "Public LinkedIn posts and articles can be indexed, but a post must be public, and links in posts are nofollow.",
    ),
    "youtube": (
        ("youtube.com", "youtu.be"),
        "Public YouTube videos are indexable, but links in descriptions and comments are nofollow.",
    ),
    "reddit": (
        ("reddit.com",),
        "Public Reddit threads are indexable, but links in them are nofollow and low-quality or removed posts are not kept.",
    ),
    "pinterest": (
        ("pinterest.com",),
        "Public Pinterest pins can be indexed, but links on them are nofollow.",
    ),
    "tiktok": (
        ("tiktok.com",),
        "TikTok pages are rarely indexed individually, and links on them are nofollow.",
    ),
}


def platform_for(url: str) -> tuple[str, str] | None:
    """(platform name, advice) if `url` is on a known social platform, else None."""
    try:
        host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    for name, (hosts, advice) in PLATFORMS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name, advice
    return None
