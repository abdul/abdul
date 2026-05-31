#!/usr/bin/env python3
"""Generate languages.svg from ALL owned repos (public + private).

lowlighter/metrics cannot count private-repo languages because its in-depth
analyzer sources commits from the public events feed. This script instead
queries the GraphQL `languages` connection, which returns byte counts for
private repositories when the token carries `repo` scope, and renders a
stacked-bar SVG in the same visual register as the other profile cards.

Env:
  GH_TOKEN  GitHub token with `repo` scope (so private repos are included).
Output:
  languages.svg in the repository root.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from html import escape

GRAPHQL_URL = "https://api.github.com/graphql"
LIMIT = 12  # languages shown
OUTPUT = "languages.svg"

# GitHub Linguist colors for languages we are likely to surface. Anything not
# listed falls back to a neutral grey so the chart still renders.
COLORS = {
    "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "ActionScript": "#882B0F", "Vue": "#41b883", "Shell": "#89e051",
    "CSS": "#563d7c", "HTML": "#e34c26", "Swift": "#F05138",
    "Solidity": "#AA6746", "SCSS": "#c6538c", "Vim Script": "#199f4b",
    "HCL": "#844FBA", "C#": "#178600", "C++": "#f34b7d", "C": "#555555",
    "Go": "#00ADD8", "Rust": "#dea584", "Java": "#b07219", "Ruby": "#701516",
    "PHP": "#4F5D95", "Dockerfile": "#384d54", "Makefile": "#427819",
    "Kotlin": "#A97BFF", "Dart": "#00B4AB", "Lua": "#000080",
    "PowerShell": "#012456", "Jupyter Notebook": "#DA5B0B",
}
FALLBACK_COLOR = "#8b949e"

QUERY = """
query($endCursor:String){
  viewer{
    repositories(first:100, after:$endCursor, ownerAffiliations:OWNER, isFork:false){
      pageInfo{ hasNextPage endCursor }
      nodes{ languages(first:30, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name } } } }
    }
  }
}
"""


def graphql(token: str, cursor: str | None) -> dict:
    payload = json.dumps({"query": QUERY, "variables": {"endCursor": cursor}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "abdul-languages-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "errors" in body:
        raise RuntimeError(f"GraphQL errors: {body['errors']}")
    return body["data"]["viewer"]["repositories"]


def aggregate(token: str) -> Counter:
    totals: Counter = Counter()
    cursor = None
    while True:
        page = graphql(token, cursor)
        for repo in page["nodes"]:
            for edge in repo["languages"]["edges"]:
                totals[edge["node"]["name"]] += edge["size"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return totals


def render(totals: Counter) -> str:
    grand = sum(totals.values())
    if grand == 0:
        raise RuntimeError("No language bytes found — check token scope.")

    top = totals.most_common(LIMIT)
    shown = sum(s for _, s in top)
    items = [(name, size, 100 * size / grand) for name, size in top]
    other = grand - shown
    if other > 0:
        items.append(("Other", other, 100 * other / grand))

    width = 480
    pad = 6
    bar_y = 40
    bar_h = 10
    bar_w = width - 2 * pad
    legend_y = bar_y + bar_h + 18
    col_w = bar_w / 2
    row_h = 22
    rows = (len(items) + 1) // 2
    height = legend_y + rows * row_h

    # --- stacked bar segments (normalised to the shown total so it fills) ---
    segments = []
    x = pad
    bar_total = sum(s for _, s, _ in items)
    for name, size, _pct in items:
        seg_w = bar_w * size / bar_total
        color = COLORS.get(name, FALLBACK_COLOR)
        segments.append(
            f'<rect x="{x:.2f}" y="{bar_y}" width="{seg_w:.2f}" height="{bar_h}" '
            f'fill="{color}"><title>{escape(name)}</title></rect>'
        )
        x += seg_w

    # --- legend: two columns, dot + "Name 12.3%" ---
    legend = []
    for i, (name, _size, pct) in enumerate(items):
        col = i % 2
        row = i // 2
        lx = pad + col * col_w
        ly = legend_y + row * row_h
        color = COLORS.get(name, FALLBACK_COLOR)
        legend.append(f'<circle cx="{lx + 6:.2f}" cy="{ly:.2f}" r="5" fill="{color}"/>')
        legend.append(
            f'<text x="{lx + 18:.2f}" y="{ly + 4:.2f}" class="lang">'
            f'{escape(name)} <tspan class="pct">{pct:.1f}%</tspan></text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height:.0f}" viewBox="0 0 {width} {height:.0f}" fill="none">
  <style>
    text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
    .title {{ font-size: 16px; font-weight: 600; fill: #0366d6; }}
    .lang {{ font-size: 12px; fill: #777; }}
    .pct {{ fill: #999; }}
  </style>
  <text x="{pad}" y="22" class="title">Most Used Languages</text>
  <g>
    <clipPath id="round"><rect x="{pad}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5"/></clipPath>
    <g clip-path="url(#round)">
      {''.join(segments)}
    </g>
  </g>
  {''.join(legend)}
</svg>
"""


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: GH_TOKEN not set", file=sys.stderr)
        return 1
    try:
        totals = aggregate(token)
        svg = render(totals)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(svg)
    top = ", ".join(f"{n} {100*s/sum(totals.values()):.1f}%" for n, s in totals.most_common(5))
    print(f"wrote {OUTPUT}: {len(totals)} languages, top: {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
