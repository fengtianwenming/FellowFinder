from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TargetPaper:
    title: str
    year: str
    scholar_url: str | None = None
    openalex_id: str | None = None


@dataclass(slots=True)
class AuthorMatch:
    author_name: str
    matched_title: str
    evidence_url: str
    evidence_text: str


@dataclass(slots=True)
class AuthorContext:
    author_name: str
    author_id: str | None
    orcid: str | None
    institution_names: list[str]
    raw_affiliations: list[str]
