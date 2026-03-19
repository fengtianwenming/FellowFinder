from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_outputs(findings: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "findings.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(findings, handle, ensure_ascii=False, indent=2)

    csv_path = output_dir / "findings.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "target_paper",
                "target_year",
                "citing_title",
                "citing_year",
                "citing_url",
                "matched_author",
                "matched_title",
                "evidence_url",
                "evidence_text",
            ],
        )
        writer.writeheader()
        for item in findings:
            for article in item.get("matches", []):
                for author_match in article.get("matched_authors", []):
                    writer.writerow(
                        {
                            "target_paper": item.get("target_paper", ""),
                            "target_year": item.get("target_year", ""),
                            "citing_title": article.get("citing_title", ""),
                            "citing_year": article.get("citing_year", ""),
                            "citing_url": article.get("citing_url", ""),
                            "matched_author": author_match.get("author_name", ""),
                            "matched_title": author_match.get("matched_title", ""),
                            "evidence_url": author_match.get("evidence_url", ""),
                            "evidence_text": author_match.get("evidence_text", ""),
                        }
                    )


def print_summary(findings: list[dict[str, Any]]) -> None:
    total_targets = len(findings)
    total_matches = sum(len(item.get("matches", [])) for item in findings)
    print(f"Target papers checked: {total_targets}")
    print(f"Citing articles with fellow-title evidence: {total_matches}")
    for item in findings:
        print(f"- {item.get('target_paper', '')}: {len(item.get('matches', []))} matched citing articles")
