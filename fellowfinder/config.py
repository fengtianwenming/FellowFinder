from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SearchConfig:
    scholar_profile_url: str
    target_author_name: str | None
    keywords: list[str]
    target_paper_titles: list[str]
    target_paper_dois: list[str]
    keyword_operator: str
    fellow_titles: list[str]
    fellow_title_variants: dict[str, list[str]]
    max_profile_pages: int
    max_author_works: int
    max_citing_works_per_target: int
    max_authors_per_citing_work: int
    reset_session_every_citing_works: int
    max_workers: int
    author_search_results: int
    request_delay_seconds: float
    output_dir: Path

    @classmethod
    def from_toml(cls, payload: dict[str, Any], base_dir: Path) -> "SearchConfig":
        search = payload.get("search", {})
        keywords = [str(item).strip() for item in search.get("keywords", []) if str(item).strip()]
        target_paper_titles = [str(item).strip() for item in search.get("target_paper_titles", []) if str(item).strip()]
        target_paper_dois = [str(item).strip() for item in search.get("target_paper_dois", []) if str(item).strip()]
        fellow_titles = [str(item).strip() for item in search.get("fellow_titles", []) if str(item).strip()]
        raw_variants = search.get("fellow_title_variants", {})
        fellow_title_variants = {
            str(key).strip(): [str(item).strip() for item in value if str(item).strip()]
            for key, value in raw_variants.items()
            if str(key).strip() and isinstance(value, list)
        }
        operator = str(search.get("keyword_operator", "or")).strip().lower()
        if operator not in {"and", "or"}:
            raise ValueError("search.keyword_operator must be 'and' or 'or'")
        profile_url = str(search.get("scholar_profile_url", "")).strip()
        if not profile_url:
            raise ValueError("search.scholar_profile_url is required")
        if not keywords and not target_paper_titles and not target_paper_dois:
            raise ValueError(
                "Configure at least one of search.keywords, "
                "search.target_paper_titles, or search.target_paper_dois"
            )
        if not fellow_titles:
            raise ValueError("search.fellow_titles must not be empty")

        crawler = payload.get("crawler", {})
        output_dir = base_dir / str(payload.get("output", {}).get("dir", "output"))
        return cls(
            scholar_profile_url=profile_url,
            target_author_name=str(search.get("target_author_name", "")).strip() or None,
            keywords=keywords,
            target_paper_titles=target_paper_titles,
            target_paper_dois=target_paper_dois,
            keyword_operator=operator,
            fellow_titles=fellow_titles,
            fellow_title_variants=fellow_title_variants,
            max_profile_pages=int(crawler.get("max_profile_pages", 3)),
            max_author_works=int(crawler.get("max_author_works", 100)),
            max_citing_works_per_target=int(crawler.get("max_citing_works_per_target", 25)),
            max_authors_per_citing_work=int(crawler.get("max_authors_per_citing_work", 1)),
            reset_session_every_citing_works=int(crawler.get("reset_session_every_citing_works", 10)),
            max_workers=max(int(crawler.get("max_workers", 4)), 1),
            author_search_results=int(crawler.get("author_search_results", 5)),
            request_delay_seconds=float(crawler.get("request_delay_seconds", 1.0)),
            output_dir=output_dir,
        )


def load_config(path: Path) -> SearchConfig:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    return SearchConfig.from_toml(payload, path.parent)
