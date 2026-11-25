"""Search Console properties: types, permissions, and "does this URL belong to this property?".

Google rejects inspections of URLs outside the property, but we check first so a customer can never even
attempt to inspect (or learn anything about) a site they do not own, and so quota is not wasted.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit

DOMAIN_PREFIX = "sc-domain:"
# permissionLevel values from the Search Console API
USABLE_LEVELS = ("siteOwner", "siteFullUser", "siteRestrictedUser")  # all can inspect; unverified cannot
WRITE_LEVELS = ("siteOwner", "siteFullUser")  # sitemap submission needs more than restricted access


@dataclass(frozen=True)
class Property:
    site_url: str
    type: str  # "domain" | "url_prefix"
    permission: str
    verified: bool
    can_write: bool

    def as_dict(self) -> dict:
        return {
            "site_url": self.site_url,
            "type": self.type,
            "permission": self.permission,
            "verified": self.verified,
            "can_write": self.can_write,
            "label": self.site_url.removeprefix(DOMAIN_PREFIX) if self.type == "domain" else self.site_url,
        }


def parse_property(entry: dict) -> Property:
    site = str(entry.get("siteUrl", ""))
    level = str(entry.get("permissionLevel", ""))
    return Property(
        site_url=site,
        type="domain" if site.startswith(DOMAIN_PREFIX) else "url_prefix",
        permission=level,
        verified=level in USABLE_LEVELS,
        can_write=level in WRITE_LEVELS,
    )


def _host(raw: str | None) -> str:
    h = (raw or "").strip().rstrip(".").lower()
    try:
        return h.encode("idna").decode("ascii")
    except UnicodeError:
        return h


def _port(parts) -> int | None:
    try:
        port = parts.port
    except ValueError:
        return -1  # malformed: never equal to anything
    return port if port not in (None, 80 if parts.scheme == "http" else 443) else None


def url_in_property(url: str, site_url: str) -> bool:
    """True if `url` is inside the Search Console property `site_url`.

    * Domain property (``sc-domain:example.com``): any http/https URL on example.com or a subdomain of it.
      ``example.com.evil.com`` and ``notexample.com`` do not match.
    * URL-prefix property (``https://www.example.com/blog/``): same scheme, same host (``www`` matters), same port,
      and a path under the prefix. ``/blog-evil/`` is not under ``/blog/``.
    """
    try:
        u = urlsplit(url.strip())
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            return False
        host = _host(u.hostname)
        uport = _port(u)
        if uport == -1:
            return False

        if site_url.startswith(DOMAIN_PREFIX):
            domain = _host(site_url[len(DOMAIN_PREFIX):])
            return bool(domain) and (host == domain or host.endswith("." + domain))

        p = urlsplit(site_url.strip())
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        pport = _port(p)
        if pport == -1:
            return False
        prefix_path = p.path or "/"
        if not prefix_path.endswith("/"):
            prefix_path += "/"
        path = u.path or "/"
        return (
            u.scheme == p.scheme
            and host == _host(p.hostname)
            and uport == pport
            and path.startswith(prefix_path)
        )
    except ValueError:
        return False
