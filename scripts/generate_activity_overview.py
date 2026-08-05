#!/usr/bin/env python3
"""Generate a GitHub-style contribution activity overview card."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GRAPHQL_URL = "https://api.github.com/graphql"
ACTIVITIES = (
    ("commits", "totalCommitContributions"),
    ("issues", "totalIssueContributions"),
    ("pull_requests", "totalPullRequestContributions"),
    ("reviews", "totalPullRequestReviewContributions"),
)


def contribution_counts(username: str, token: str) -> dict[str, int]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    variables = {
        "login": username,
        "from": (now - timedelta(days=365)).isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z"),
    }
    query = """
      query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
          contributionsCollection(from: $from, to: $to) {
            totalCommitContributions
            totalIssueContributions
            totalPullRequestContributions
            totalPullRequestReviewContributions
          }
        }
      }
    """
    request = Request(
        GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "FIERsity-profile-readme",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"GitHub GraphQL request failed: {error}") from error

    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {payload['errors']}")

    collection = payload["data"]["user"]["contributionsCollection"]
    return {name: int(collection[field]) for name, field in ACTIVITIES}


def percentages(counts: dict[str, int]) -> dict[str, int]:
    total = sum(counts.values())
    if total == 0:
        return {name: 0 for name in counts}

    exact = {name: value * 100 / total for name, value in counts.items()}
    rounded = {name: int(value) for name, value in exact.items()}
    remaining = 100 - sum(rounded.values())
    order = sorted(counts, key=lambda name: (exact[name] - rounded[name], counts[name]), reverse=True)
    for name in order[:remaining]:
        rounded[name] += 1
    return rounded


def label_lines(label: str, percentage: int, x: int, y: int, anchor: str) -> str:
    if percentage == 0:
        return f'<text x="{x}" y="{y}" text-anchor="{anchor}" class="label">{label}</text>'
    return (
        f'<text x="{x}" y="{y - 8}" text-anchor="{anchor}" class="value">{percentage}%</text>'
        f'<text x="{x}" y="{y + 9}" text-anchor="{anchor}" class="label">{label}</text>'
    )


def activity_svg(counts: dict[str, int], *, dark: bool) -> str:
    pct = percentages(counts)
    background = "#0d1117" if dark else "#ffffff"
    border = "#30363d" if dark else "#d0d7de"
    text = "#8b949e" if dark else "#57606a"
    axis = "#39d353" if dark else "#1f883d"
    center_x, center_y = 152, 98
    left_x, right_x, top_y, bottom_y = 78, 226, 37, 159

    bars = {
        "commits": (center_x - (center_x - left_x) * pct["commits"] / 100, center_y),
        "issues": (center_x + (right_x - center_x) * pct["issues"] / 100, center_y),
        "pull_requests": (center_x, center_y + (bottom_y - center_y) * pct["pull_requests"] / 100),
        "reviews": (center_x, center_y - (center_y - top_y) * pct["reviews"] / 100),
    }

    highlights = []
    for name, (x, y) in bars.items():
        if pct[name] == 0:
            continue
        highlight = f'<line x1="{center_x}" y1="{center_y}" x2="{x:.1f}" y2="{y:.1f}" class="bar" />'
        if abs(x - center_x) + abs(y - center_y) >= 10:
            highlight += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="endpoint" />'
        highlights.append(highlight)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="304" height="195" viewBox="0 0 304 195" role="img" aria-labelledby="title desc">
  <title id="title">Contribution activity overview</title>
  <desc id="desc">Last twelve months: {pct['commits']} percent commits, {pct['issues']} percent issues, {pct['pull_requests']} percent pull requests, and {pct['reviews']} percent code reviews.</desc>
  <style>
    .label {{ fill: {text}; font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
    .value {{ fill: {text}; font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
    .axis {{ stroke: {axis}; stroke-width: 3; stroke-linecap: round; opacity: .78; }}
    .bar {{ stroke: {axis}; stroke-width: 9; stroke-linecap: round; opacity: .38; }}
    .endpoint {{ fill: {background}; stroke: {axis}; stroke-width: 4; }}
  </style>
  <rect x="0.5" y="0.5" width="303" height="194" rx="6" fill="{background}" stroke="{border}" />
  <line x1="{left_x}" y1="{center_y}" x2="{right_x}" y2="{center_y}" class="axis" />
  <line x1="{center_x}" y1="{top_y}" x2="{center_x}" y2="{bottom_y}" class="axis" />
  {''.join(highlights)}
  <circle cx="{center_x}" cy="{center_y}" r="5" class="endpoint" />
  {label_lines('Commits', pct['commits'], 66, 98, 'end')}
  {label_lines('Issues', pct['issues'], 238, 98, 'start')}
  {label_lines('Code review', pct['reviews'], 152, 20, 'middle')}
  {label_lines('Pull requests', pct['pull_requests'], 152, 177, 'middle')}
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--counts",
        help='Use JSON counts for local preview, e.g. {"commits":95,"issues":0,"pull_requests":5,"reviews":0}',
    )
    args = parser.parse_args()

    if args.counts:
        counts = {name: int(value) for name, value in json.loads(args.counts).items()}
    else:
        username = os.environ.get("GITHUB_USERNAME", "")
        token = os.environ.get("GITHUB_TOKEN", "")
        if not username or not token:
            raise SystemExit("GITHUB_USERNAME and GITHUB_TOKEN are required")
        counts = contribution_counts(username, token)

    missing = {name for name, _ in ACTIVITIES} - counts.keys()
    if missing:
        raise SystemExit(f"Missing activity counts: {', '.join(sorted(missing))}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "activity-overview.svg").write_text(activity_svg(counts, dark=False), encoding="utf-8")
    (args.output_dir / "activity-overview-dark.svg").write_text(activity_svg(counts, dark=True), encoding="utf-8")


if __name__ == "__main__":
    main()
