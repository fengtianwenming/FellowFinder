from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup
from requests import HTTPError
from tqdm import tqdm

from .config import SearchConfig
from .matching import build_author_matches, deduplicate_author_matches, is_blocked_evidence_url
from .models import AuthorContext, AuthorMatch, TargetPaper
from .utils import first_non_empty, matches_keywords, normalize_doi, normalize_text, truncate_text


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


class FellowFinder:
    def __init__(self, config: SearchConfig) -> None:
        self.config = config
        self.session = self.create_session()
        self.author_cache: dict[str, list[AuthorMatch]] = {}

    def run(self) -> list[dict[str, Any]]:
        publications = self.fetch_target_publications()
        target_papers = self.select_target_papers(publications)
        if not target_papers:
            print("No target papers matched the configured selection rules.", file=sys.stderr)
            return []

        findings: list[dict[str, Any]] = []
        progress = tqdm(target_papers, desc="Target papers", unit="paper")
        for paper in progress:
            progress.set_postfix_str(truncate_text(paper.title, 48))
            findings.append(self.process_target_paper(paper))
        return findings

    def select_target_papers(self, publications: list[TargetPaper]) -> list[TargetPaper]:
        selected: list[TargetPaper] = []
        seen_keys: set[str] = set()
        title_filters = {normalize_text(title) for title in self.config.target_paper_titles}

        for paper in publications:
            normalized_title = normalize_text(paper.title)
            matches_explicit_title = normalized_title in title_filters if title_filters else False
            matches_keywords_filter = bool(self.config.keywords) and matches_keywords(
                paper.title,
                self.config.keywords,
                self.config.keyword_operator,
            )
            if not matches_explicit_title and not matches_keywords_filter:
                continue
            self.append_unique_target_paper(selected, seen_keys, paper)

        for doi in self.config.target_paper_dois:
            paper = self.build_target_paper_from_doi(doi)
            if paper is None:
                print(f"Skipping unresolved DOI target: {doi}", file=sys.stderr)
                continue
            self.append_unique_target_paper(selected, seen_keys, paper)

        return selected

    def append_unique_target_paper(
        self,
        selected: list[TargetPaper],
        seen_keys: set[str],
        paper: TargetPaper,
    ) -> None:
        key = paper.openalex_id or normalize_doi(paper.scholar_url or "") or normalize_text(paper.title)
        if not key or key in seen_keys:
            return
        seen_keys.add(key)
        selected.append(paper)

    def build_target_paper_from_doi(self, doi: str) -> TargetPaper | None:
        work = self.find_openalex_work_by_doi(doi)
        if not work:
            return None
        return TargetPaper(
            title=work.get("display_name", "").strip() or doi,
            year=str(work.get("publication_year", "") or ""),
            scholar_url=work.get("doi") or doi,
            openalex_id=work.get("id"),
        )

    def process_target_paper(self, paper: TargetPaper) -> dict[str, Any]:
        self.reset_search_context()
        openalex_id = paper.openalex_id
        if not openalex_id:
            openalex_work = self.find_openalex_work(paper.title)
            if not openalex_work:
                return {
                    "target_paper": paper.title,
                    "target_year": paper.year,
                    "status": "openalex_not_found",
                    "matches": [],
                }
            openalex_id = openalex_work["id"]

        paper.openalex_id = openalex_id
        citing_works = self.fetch_citing_works(openalex_id)
        matched_articles = self.process_citing_works_parallel(paper.title, citing_works)
        return {
            "target_paper": paper.title,
            "target_year": paper.year,
            "status": "ok",
            "openalex_id": paper.openalex_id,
            "matches": matched_articles,
        }

    def find_openalex_work_by_doi(self, doi: str) -> dict[str, Any] | None:
        normalized_doi = normalize_doi(doi)
        if not normalized_doi:
            return None
        url = f"https://api.openalex.org/works/https://doi.org/{quote(normalized_doi, safe='')}"
        try:
            response = self.get(url)
        except requests.RequestException:
            return None
        return response.json()

    def process_citing_works_parallel(self, target_title: str, citing_works: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not citing_works:
            return []
        matched_articles: list[tuple[int, dict[str, Any]]] = []
        desc = f"Citing {truncate_text(target_title, 28)}"
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            future_map = {
                executor.submit(process_citing_work_task, self.config, index, citing_work): index
                for index, citing_work in enumerate(citing_works)
            }
            for future in tqdm(as_completed(future_map), total=len(future_map), desc=desc, unit="article", leave=False):
                result = future.result()
                if result is None:
                    continue
                matched_articles.append(result)
        matched_articles.sort(key=lambda item: item[0])
        return [item[1] for item in matched_articles]

    def create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        return session

    def reset_search_context(self) -> None:
        self.session.close()
        self.session = self.create_session()
        self.author_cache = {}

    def fetch_target_publications(self) -> list[TargetPaper]:
        try:
            return self.fetch_scholar_publications()
        except HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == 429:
                if self.config.target_author_name:
                    print(
                        "Google Scholar returned 429. Falling back to OpenAlex author works "
                        f"for '{self.config.target_author_name}'.",
                        file=sys.stderr,
                    )
                    return self.fetch_openalex_author_publications(self.config.target_author_name)
                raise RuntimeError(
                    "Google Scholar returned HTTP 429. Add search.target_author_name in config.toml "
                    "to enable OpenAlex fallback."
                ) from exc
            raise

    def fetch_openalex_author_publications(self, author_name: str) -> list[TargetPaper]:
        author = self.find_openalex_author(author_name)
        if not author:
            raise RuntimeError(f"Could not find OpenAlex author for '{author_name}'.")
        works_url = (
            "https://api.openalex.org/works"
            f"?filter=author.id:{quote(author['id'])}&sort=publication_date:desc&per-page={self.config.max_author_works}"
        )
        response = self.get(works_url)
        papers: list[TargetPaper] = []
        seen_titles: set[str] = set()
        for item in response.json().get("results", []):
            title = item.get("display_name", "").strip()
            normalized = normalize_text(title)
            if not title or normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            papers.append(
                TargetPaper(
                    title=title,
                    year=str(item.get("publication_year", "") or ""),
                    scholar_url=item.get("id"),
                )
            )
        return papers

    def fetch_scholar_publications(self) -> list[TargetPaper]:
        parsed = urlparse(self.config.scholar_profile_url)
        query = parse_qs(parsed.query)
        user = query.get("user", [None])[0]
        if not user:
            raise ValueError("The scholar profile URL does not contain a user parameter.")

        papers: list[TargetPaper] = []
        seen_titles: set[str] = set()
        for page in range(self.config.max_profile_pages):
            start = page * 100
            profile_url = (
                "https://scholar.google.com/citations"
                f"?hl=zh-CN&user={quote(user)}&view_op=list_works&sortby=pubdate&cstart={start}&pagesize=100"
            )
            response = self.get(profile_url)
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("tr.gsc_a_tr")
            if not rows:
                break
            for row in rows:
                title_node = row.select_one("a.gsc_a_at")
                year_node = row.select_one(".gsc_a_y span")
                if not title_node:
                    continue
                title = title_node.get_text(" ", strip=True)
                normalized = normalize_text(title)
                if not title or normalized in seen_titles:
                    continue
                seen_titles.add(normalized)
                papers.append(
                    TargetPaper(
                        title=title,
                        year=year_node.get_text(strip=True) if year_node else "",
                        scholar_url=title_node.get("href"),
                    )
                )
            self.sleep()
        return papers

    def find_openalex_work(self, title: str) -> dict[str, Any] | None:
        url = f"https://api.openalex.org/works?search={quote(title)}&per-page=5"
        response = self.get(url)
        results = response.json().get("results", [])
        if not results:
            return None

        normalized_title = normalize_text(title)
        scored = []
        for item in results:
            candidate = item.get("display_name", "")
            score = SequenceMatcher(None, normalized_title, normalize_text(candidate)).ratio()
            scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best_item = scored[0]
        return best_item if best_score >= 0.72 else None

    def find_openalex_author(self, author_name: str) -> dict[str, Any] | None:
        url = f"https://api.openalex.org/authors?search={quote(author_name)}&per-page=5"
        response = self.get(url)
        results = response.json().get("results", [])
        if not results:
            return None
        normalized_author = normalize_text(author_name)
        scored = []
        for item in results:
            candidate = item.get("display_name", "")
            score = SequenceMatcher(None, normalized_author, normalize_text(candidate)).ratio()
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best_item = scored[0]
        return best_item if best_score >= 0.72 else None

    def fetch_citing_works(self, openalex_id: str) -> list[dict[str, Any]]:
        target_count = self.config.max_citing_works_per_target
        per_page = 25
        page = 1
        results: list[dict[str, Any]] = []
        while True:
            url = (
                "https://api.openalex.org/works"
                f"?filter=cites:{quote(openalex_id)}&per-page={per_page}&page={page}"
            )
            response = self.get(url)
            page_results = response.json().get("results", [])
            if not page_results:
                break
            remaining = max(target_count - len(results), 0)
            if target_count > 0:
                results.extend(page_results[:remaining])
            else:
                results.extend(page_results)
            if target_count > 0 and len(results) >= target_count:
                break
            if len(page_results) < per_page:
                break
            page += 1
            self.sleep()
        return results

    def match_fellow_authors(self, authorships: list[dict[str, Any]]) -> list[AuthorMatch]:
        matches: list[AuthorMatch] = []
        prioritized_authorships = prioritize_authorships(authorships)[: self.config.max_authors_per_citing_work]
        for authorship in prioritized_authorships:
            author_context = build_author_context(authorship)
            if not author_context.author_name:
                continue
            cache_key = author_context.author_id or author_context.orcid or author_context.author_name
            if cache_key in self.author_cache:
                cached = self.author_cache[cache_key]
                matches.extend(cached)
                if cached:
                    break
                continue
            author_matches = self.search_author_titles(author_context)
            self.author_cache[cache_key] = author_matches
            matches.extend(author_matches)
            if author_matches:
                break
            self.sleep()
        return deduplicate_author_matches(matches)

    def search_author_titles(self, author: AuthorContext) -> list[AuthorMatch]:
        try:
            found = self.search_author_titles_on_brave(author)
        except requests.RequestException:
            try:
                found = self.search_author_titles_on_bing(author)
            except requests.RequestException:
                found = []
        return deduplicate_author_matches(found)

    def search_author_titles_on_brave(self, author: AuthorContext) -> list[AuthorMatch]:
        query = build_author_query(author)
        url = f"https://search.brave.com/search?q={quote(query)}&source=web"
        response = self.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        found: list[AuthorMatch] = []
        for node in soup.select('div[data-type="web"]')[: self.config.author_search_results]:
            link_node = node.select_one("a[href]")
            snippet_node = node.select_one("div.snippet")
            title_text = link_node.get_text(" ", strip=True) if link_node else ""
            snippet_text = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            joined_text = " ".join(part for part in [title_text, snippet_text] if part)
            evidence_url = link_node.get("href", "") if link_node else ""
            if is_blocked_evidence_url(evidence_url):
                continue
            direct_matches = build_author_matches(
                joined_text,
                author,
                self.config.fellow_titles,
                evidence_url,
                self.config.fellow_title_variants,
            )
            if direct_matches:
                found.extend(direct_matches)
                break
            if not evidence_url.startswith("http"):
                continue
            page_text = self.fetch_page_text(evidence_url)
            page_matches = build_author_matches(
                page_text,
                author,
                self.config.fellow_titles,
                evidence_url,
                self.config.fellow_title_variants,
            )
            found.extend(page_matches)
            if page_matches:
                break
        return found

    def search_author_titles_on_bing(self, author: AuthorContext) -> list[AuthorMatch]:
        query = build_author_query(author)
        url = f"https://www.bing.com/search?q={quote(query)}"
        response = self.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        result_nodes = soup.select("li.b_algo")[: self.config.author_search_results]
        found: list[AuthorMatch] = []
        for node in result_nodes:
            title_node = node.select_one("h2")
            snippet_node = node.select_one(".b_caption p") or node.select_one(".b_snippet")
            link_node = node.select_one("h2 a")
            joined_text = " ".join(
                text
                for text in [
                    title_node.get_text(" ", strip=True) if title_node else "",
                    snippet_node.get_text(" ", strip=True) if snippet_node else "",
                ]
                if text
            )
            evidence_url = link_node.get("href", "") if link_node else ""
            if is_blocked_evidence_url(evidence_url):
                continue
            matches = build_author_matches(
                joined_text,
                author,
                self.config.fellow_titles,
                evidence_url,
                self.config.fellow_title_variants,
            )
            found.extend(matches)
            if matches:
                break
            if evidence_url.startswith("http"):
                page_text = self.fetch_page_text(evidence_url)
                page_matches = build_author_matches(
                    page_text,
                    author,
                    self.config.fellow_titles,
                    evidence_url,
                    self.config.fellow_title_variants,
                )
                found.extend(page_matches)
                if page_matches:
                    break
        return found

    def fetch_page_text(self, url: str) -> str:
        try:
            response = self.get(url)
        except requests.RequestException:
            return ""
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text(" ", strip=True)

    def get(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response

    def sleep(self) -> None:
        if self.config.request_delay_seconds > 0:
            time.sleep(self.config.request_delay_seconds)


def process_citing_work_task(config: SearchConfig, index: int, citing_work: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    worker = FellowFinder(config)
    author_matches = worker.match_fellow_authors(citing_work.get("authorships", []))
    if not author_matches:
        return None
    return (
        index,
        {
            "citing_title": citing_work.get("display_name", ""),
            "citing_year": citing_work.get("publication_year"),
            "citing_url": first_non_empty(
                citing_work.get("primary_location", {}).get("landing_page_url"),
                citing_work.get("doi"),
                citing_work.get("id"),
            ),
            "authors": [auth.get("author", {}).get("display_name", "") for auth in citing_work.get("authorships", [])],
            "matched_authors": [
                {
                    "author_name": match.author_name,
                    "matched_title": match.matched_title,
                    "evidence_url": match.evidence_url,
                    "evidence_text": match.evidence_text,
                }
                for match in author_matches
            ],
        },
    )


def build_author_context(authorship: dict[str, Any]) -> AuthorContext:
    author = authorship.get("author", {})
    institutions = authorship.get("institutions", [])
    institution_names = [item.get("display_name", "").strip() for item in institutions if item.get("display_name")]
    raw_affiliations = [item.strip() for item in authorship.get("raw_affiliation_strings", []) if item and item.strip()]
    return AuthorContext(
        author_name=author.get("display_name", "").strip(),
        author_id=author.get("id"),
        orcid=author.get("orcid"),
        institution_names=institution_names,
        raw_affiliations=raw_affiliations,
    )


def build_author_query(author: AuthorContext) -> str:
    parts = [f'"{author.author_name}"']
    if author.institution_names:
        parts.append(f'"{author.institution_names[0]}"')
    parts.append("fellow")
    return " ".join(parts)


def prioritize_authorships(authorships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(authorships) <= 2:
        return authorships
    prioritized = [authorships[-1], authorships[0]]
    prioritized.extend(authorships[1:-1])
    seen_ids: set[int] = set()
    unique: list[dict[str, Any]] = []
    for item in prioritized:
        marker = id(item)
        if marker in seen_ids:
            continue
        seen_ids.add(marker)
        unique.append(item)
    return unique
