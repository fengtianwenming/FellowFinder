from __future__ import annotations

from urllib.parse import urlparse

from .models import AuthorContext, AuthorMatch
from .utils import has_affiliation_overlap, normalize_text


def deduplicate_author_matches(matches: list[AuthorMatch]) -> list[AuthorMatch]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[AuthorMatch] = []
    for match in matches:
        key = (match.author_name, match.matched_title, match.evidence_url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique


def expand_fellow_title_variants(fellow_title: str, configured_variants: dict[str, list[str]] | None = None) -> list[str]:
    variants = {fellow_title}
    if configured_variants:
        for key, items in configured_variants.items():
            if normalize_text(key) == normalize_text(fellow_title):
                variants.update(items)
    return list(variants)


def contains_author_title_evidence(
    text: str,
    author: AuthorContext,
    fellow_title: str,
    configured_variants: dict[str, list[str]] | None = None,
) -> bool:
    normalized_text = normalize_text(text)
    normalized_author = normalize_text(author.author_name)
    title_variants = [normalize_text(item) for item in expand_fellow_title_variants(fellow_title, configured_variants)]
    if normalized_author not in normalized_text:
        return False
    if not any(title_variant in normalized_text for title_variant in title_variants):
        return False
    return has_affiliation_overlap(normalized_text, author)


def build_evidence_excerpt(text: str, fellow_title: str, configured_variants: dict[str, list[str]] | None = None) -> str:
    title_variants = [normalize_text(item) for item in expand_fellow_title_variants(fellow_title, configured_variants)]
    normalized_text = normalize_text(text)
    index = -1
    for title_variant in title_variants:
        index = normalized_text.find(title_variant)
        if index != -1:
            break
    if index == -1:
        return text[:240]
    start = max(index - 120, 0)
    end = min(index + 120, len(text))
    return text[start:end]


def build_author_matches(
    text: str,
    author: AuthorContext,
    fellow_titles: list[str],
    evidence_url: str,
    configured_variants: dict[str, list[str]] | None = None,
) -> list[AuthorMatch]:
    matches: list[AuthorMatch] = []
    for fellow_title in fellow_titles:
        if contains_author_title_evidence(text, author, fellow_title, configured_variants):
            matches.append(
                AuthorMatch(
                    author_name=author.author_name,
                    matched_title=fellow_title,
                    evidence_url=evidence_url,
                    evidence_text=build_evidence_excerpt(text, fellow_title, configured_variants),
                )
            )
    return matches


def is_blocked_evidence_url(url: str) -> bool:
    if not url.startswith("http"):
        return True
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return True
    blocked = {
        "wikipedia.org",
        "en.wikipedia.org",
        "researchgate.net",
        "www.researchgate.net",
        "linkedin.com",
        "www.linkedin.com",
        "grokipedia.com",
        "scholar.google.com",
        "ratemyprofessors.com",
        "www.ratemyprofessors.com",
    }
    return host in blocked or any(host.endswith("." + item) for item in blocked)
