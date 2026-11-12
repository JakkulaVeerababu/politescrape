"""robots.txt parsing and matching, following RFC 9309.

The standard library's ``urllib.robotparser`` predates the RFC: it has no
wildcard support and uses the first matching rule instead of the most
specific one. This module implements the rules the way the RFC (and the large
search engines) apply them:

* the group for our own product token wins over the ``*`` group;
* groups for the same user agent are merged;
* the longest matching rule decides, and ``Allow`` wins a tie;
* ``*`` matches any run of characters and a trailing ``$`` anchors the end;
* ``/robots.txt`` itself may always be fetched.

``Crawl-delay`` is not part of the RFC but many sites publish one, so it is
read as well.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from politescrape.urls import normalize_percent_encoding, path_and_query

# The RFC asks crawlers to read at least 500 kibibytes of a robots.txt file.
MAX_ROBOTS_BYTES = 512 * 1024

_PRODUCT_TOKEN = re.compile(r"[A-Za-z_-]+")
_AGENT_KEYS = frozenset({"user-agent", "useragent", "user agent"})


def product_token(user_agent: str) -> str:
    """Return the name robots.txt groups are matched against.

    ``"my-bot/1.2 (+https://example.org)"`` becomes ``"my-bot"``.
    """
    match = _PRODUCT_TOKEN.match(user_agent.strip())
    return (match.group(0) if match else user_agent.strip()).lower()


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + (r"\Z" if anchored else ""), re.DOTALL)


@dataclass(frozen=True)
class Rule:
    """One ``Allow`` or ``Disallow`` line."""

    allow: bool
    pattern: str

    def matches(self, path: str) -> bool:
        return _compile(self.pattern).match(path) is not None


@dataclass
class Group:
    """The rules that apply to one or more user agents."""

    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


class RobotsTxt:
    """A parsed robots.txt file."""

    def __init__(self, groups: list[Group] | None = None, sitemaps: list[str] | None = None):
        self._groups = groups or []
        self.sitemaps: list[str] = sitemaps or []

    @classmethod
    def allow_all(cls) -> RobotsTxt:
        """The rules for a site without a robots.txt file: everything is allowed."""
        return cls()

    @classmethod
    def disallow_all(cls) -> RobotsTxt:
        """The rules to assume while a site's robots.txt cannot be reached."""
        return cls([Group(agents=["*"], rules=[Rule(allow=False, pattern="/")])])

    @classmethod
    def parse(cls, text: str | bytes) -> RobotsTxt:
        """Parse the contents of a robots.txt file. Lines it cannot read are skipped."""
        if isinstance(text, bytes):
            text = text[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
        else:
            text = text[:MAX_ROBOTS_BYTES]
        groups: list[Group] = []
        sitemaps: list[str] = []
        current: Group | None = None
        naming_agents = False  # True while reading consecutive User-agent lines
        for raw_line in text.lstrip("\N{ZERO WIDTH NO-BREAK SPACE}").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower()
            value = value.strip()
            if key in _AGENT_KEYS:
                if current is None or not naming_agents:
                    current = Group()
                    groups.append(current)
                current.agents.append("*" if value == "*" else product_token(value))
                naming_agents = True
            elif key == "sitemap":
                if value:
                    sitemaps.append(value)
            elif key in ("allow", "disallow"):
                naming_agents = False
                # An empty value means "no restriction", so there is nothing to record.
                if current is not None and value:
                    current.rules.append(Rule(key == "allow", normalize_percent_encoding(value)))
            elif key == "crawl-delay":
                naming_agents = False
                delay = _parse_delay(value)
                if current is not None and delay is not None:
                    current.crawl_delay = max(current.crawl_delay or 0.0, delay)
        return cls(groups, sitemaps)

    def _groups_for(self, user_agent: str) -> list[Group]:
        token = product_token(user_agent)
        specific = [group for group in self._groups if token in group.agents]
        if specific:
            return specific
        return [group for group in self._groups if "*" in group.agents]

    def can_fetch(self, user_agent: str, url: str) -> bool:
        """True when ``user_agent`` may fetch ``url`` (a full URL or a path)."""
        path = path_and_query(url) if "://" in url else (url or "/")
        path = normalize_percent_encoding(path)
        if path == "/robots.txt":
            return True
        best: Rule | None = None
        for group in self._groups_for(user_agent):
            for rule in group.rules:
                if not rule.matches(path):
                    continue
                # The longest pattern is the most specific; Allow wins a tie.
                if (
                    best is None
                    or len(rule.pattern) > len(best.pattern)
                    or (len(rule.pattern) == len(best.pattern) and rule.allow)
                ):
                    best = rule
        return best is None or best.allow

    def crawl_delay(self, user_agent: str) -> float | None:
        """The ``Crawl-delay`` (in seconds) that applies to ``user_agent``, if any."""
        delays = [
            group.crawl_delay
            for group in self._groups_for(user_agent)
            if group.crawl_delay is not None
        ]
        return max(delays) if delays else None


def _parse_delay(value: str) -> float | None:
    try:
        delay = float(value)
    except ValueError:
        return None
    return delay if math.isfinite(delay) and delay >= 0 else None
