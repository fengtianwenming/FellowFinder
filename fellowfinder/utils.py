from __future__ import annotations

import re
from typing import Any

from .models import AuthorContext


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None


def truncate_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def matches_keywords(title: str, keywords: list[str], operator: str) -> bool:
    normalized_title = normalize_text(title)
    normalized_keywords = [normalize_text(keyword) for keyword in keywords]
    if operator == "and":
        return all(keyword in normalized_title for keyword in normalized_keywords)
    return any(keyword in normalized_title for keyword in normalized_keywords)


def has_affiliation_overlap(normalized_text: str, author: AuthorContext) -> bool:
    institution_tokens = [normalize_text(name) for name in author.institution_names if name.strip()]
    affiliation_tokens = [normalize_text(name) for name in author.raw_affiliations if name.strip()]
    for token in institution_tokens + affiliation_tokens:
        if len(token) >= 6 and token in normalized_text:
            return True
    return not institution_tokens and not affiliation_tokens
