#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path


USERNAME = os.getenv("GITHUB_USERNAME", "KaueASB")
YEAR = int(os.getenv("YEAR", "2026"))

OUTPUT_JSON = Path(os.getenv("OUTPUT_JSON", "stats.json"))
OUTPUT_SVG = Path(os.getenv("OUTPUT_SVG", "stats.svg"))

WIDTH = 520
HEIGHT = 245

# Tema semelhante ao visual escuro do GitHub Readme Stats.
BG = "#0d1117"
BORDER = "#30363d"
TEXT = "#f0f6fc"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
GREEN = "#3fb950"


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        die(f"Command not found: {command[0]}")
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        die(f"Command failed: {' '.join(command)}")

    return result.stdout


def gh_api(path: str) -> dict:
    output = run(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            path,
        ]
    )

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        die(f"GitHub API returned invalid JSON for: {path}")


def current_user() -> str:
    data = gh_api("/user")
    login = data.get("login")

    if not login:
        die("Could not determine authenticated GitHub user.")

    return login


def github_search_count(endpoint: str, query: str) -> int:
    encoded = urllib.parse.quote(query, safe="")

    data = gh_api(
        f"/search/{endpoint}?q={encoded}&per_page=1"
    )

    total = data.get("total_count")

    if not isinstance(total, int):
        die(
            "GitHub Search API did not return total_count "
            f"for query: {query}"
        )

    return total


def github_graphql(query: str, variables: dict) -> dict:
    command = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={query}",
    ]

    for key, value in variables.items():
        command.extend(
            [
                "-F",
                f"{key}={value}",
            ]
        )

    output = run(command)

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        die("GraphQL returned invalid JSON.")


def get_contribution_calendar(
    username: str,
    year: int,
) -> dict:
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year}-12-31T23:59:59Z"

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        login

        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalPullRequestReviewContributions
          totalRepositoriesWithContributedCommits
          restrictedContributionsCount

          contributionCalendar {
            totalContributions
          }
        }
      }
    }
    """

    data = github_graphql(
        query,
        {
            "login": username,
            "from": start,
            "to": end,
        },
    )

    if data.get("errors"):
        die(json.dumps(data["errors"], indent=2))

    collection = (
        data
        .get("data", {})
        .get("user", {})
        .get("contributionsCollection")
    )

    if not collection:
        die("Could not retrieve contributionsCollection.")

    return collection


def github_search_items(
    endpoint: str,
    query: str,
) -> list[dict]:
    """
    Busca todos os resultados disponíveis para uma query usando
    a paginação da GitHub Search API.

    A Search API limita o conjunto pesquisável a 1000 resultados,
    mas isso é suficiente para nossa finalidade de PRs atualmente.
    """

    encoded = urllib.parse.quote(query, safe="")

    items: list[dict] = []
    page = 1
    per_page = 100

    while True:
        data = gh_api(
            f"/search/{endpoint}"
            f"?q={encoded}"
            f"&per_page={per_page}"
            f"&page={page}"
        )

        page_items = data.get("items", [])

        if not page_items:
            break

        items.extend(page_items)

        if len(items) >= data.get("total_count", 0):
            break

        if len(page_items) < per_page:
            break

        page += 1

    return items


def get_repository_breakdown(
    username: str,
    year: int,
) -> list[dict]:
    start = f"{year}-01-01"
    end = f"{year}-12-31"

    query = (
        f"is:pr author:{username} "
        f"created:{start}..{end}"
    )

    items = github_search_items(
        "issues",
        query,
    )

    counts: dict[str, int] = {}

    for item in items:
        repo_url = item.get("repository_url", "")

        prefix = "https://api.github.com/repos/"

        if repo_url.startswith(prefix):
            repo = repo_url[len(prefix):]
        else:
            repo = repo_url

        if repo:
            counts[repo] = counts.get(repo, 0) + 1

    return [
        {
            "repository": repo,
            "prs_authored": count,
        }
        for repo, count in sorted(
            counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )
    ]


def collect_stats(
    username: str,
    year: int,
) -> dict:
    start = f"{year}-01-01"
    end = f"{year}-12-31"

    # ---------------------------------------------------------
    # Commits authored — all time
    # ---------------------------------------------------------

    commits_all_time_query = f"author:{username}"

    commits_all_time = github_search_count(
        "commits",
        commits_all_time_query,
    )

    # ---------------------------------------------------------
    # Commits authored — current year
    # ---------------------------------------------------------

    commits_year_query = (
        f"author:{username} "
        f"author-date:{start}..{end}"
    )

    commits_year = github_search_count(
        "commits",
        commits_year_query,
    )

    # ---------------------------------------------------------
    # PRs authored
    # ---------------------------------------------------------

    prs_authored_query = (
        f"is:pr author:{username} "
        f"created:{start}..{end}"
    )

    prs_authored = github_search_count(
        "issues",
        prs_authored_query,
    )

    # ---------------------------------------------------------
    # PRs merged
    # ---------------------------------------------------------

    prs_merged_query = (
        f"is:pr is:merged author:{username} "
        f"merged:{start}..{end}"
    )

    prs_merged = github_search_count(
        "issues",
        prs_merged_query,
    )

    # ---------------------------------------------------------
    # PRs currently open
    # ---------------------------------------------------------

    prs_open_query = (
        f"is:pr is:open author:{username} "
        f"created:{start}..{end}"
    )

    prs_open = github_search_count(
        "issues",
        prs_open_query,
    )

    # ---------------------------------------------------------
    # PRs closed but not merged
    # ---------------------------------------------------------

    prs_closed_unmerged_query = (
        f"is:pr is:closed author:{username} "
        f"created:{start}..{end} "
        f"-is:merged"
    )

    prs_closed_unmerged = github_search_count(
        "issues",
        prs_closed_unmerged_query,
    )

    # ---------------------------------------------------------
    # GitHub contribution calendar
    # ---------------------------------------------------------

    contributions = get_contribution_calendar(
        username,
        year,
    )

    # ---------------------------------------------------------
    # Breakdown by repository
    # ---------------------------------------------------------

    repository_breakdown = get_repository_breakdown(
        username,
        year,
    )

    return {
        "username": username,
        "year": year,

        # -----------------------------------------------------
        # Contribution calendar
        # -----------------------------------------------------
        #
        # IMPORTANT:
        #
        # total = total GitHub contributions in the calendar.
        #
        # It is NOT the number of commits.
        #
        "contributions": {
            "total": contributions[
                "contributionCalendar"
            ]["totalContributions"],

            "restricted": contributions[
                "restrictedContributionsCount"
            ],

            "commits_from_github": contributions[
                "totalCommitContributions"
            ],

            "pull_requests_from_github": contributions[
                "totalPullRequestContributions"
            ],

            "reviews_from_github": contributions[
                "totalPullRequestReviewContributions"
            ],

            "issues_from_github": contributions[
                "totalIssueContributions"
            ],

            "repositories_with_commits": contributions[
                "totalRepositoriesWithContributedCommits"
            ],
        },

        # -----------------------------------------------------
        # Commits found through GitHub Search
        # -----------------------------------------------------

        "commits": {
            "all_time": commits_all_time,
            "year": commits_year,
        },

        # -----------------------------------------------------
        # Pull requests
        # -----------------------------------------------------

        "pull_requests": {
            "authored": prs_authored,
            "merged": prs_merged,
            "open": prs_open,
            "closed_unmerged": prs_closed_unmerged,
        },

        # -----------------------------------------------------
        # Repositories
        # -----------------------------------------------------

        "repositories": repository_breakdown,
    }


def esc(value: object) -> str:
    return html.escape(str(value))


def fmt(number: int) -> str:
    return f"{number:,}"


def svg_text(
    x: int,
    y: int,
    text: str,
    size: int,
    color: str,
    weight: int = 400,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" '
        f'fill="{color}" '
        f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,'
        f'Roboto,Helvetica,Arial,sans-serif" '
        f'font-size="{size}px" '
        f'font-weight="{weight}" '
        f'text-anchor="{anchor}">'
        f'{esc(text)}</text>'
    )


def make_svg(stats: dict) -> str:
    username = stats["username"]
    year = stats["year"]

    total_contributions = stats[
        "contributions"
    ]["total"]

    restricted = stats[
        "contributions"
    ]["restricted"]

    commits_all_time = stats[
        "commits"
    ]["all_time"]

    commits_year = stats[
        "commits"
    ]["year"]

    prs = stats[
        "pull_requests"
    ]["authored"]

    merged = stats[
        "pull_requests"
    ]["merged"]

    repositories = len(
        stats["repositories"]
    )

    title = f"{username}'s GitHub Stats"

    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}" '
            f'role="img" '
            f'aria-labelledby="title desc">'
        ),

        f'<title id="title">{esc(title)}</title>',

        (
            f'<desc id="desc">'
            f'{total_contributions} contributions, '
            f'{commits_all_time} commits all-time, '
            f'{commits_year} commits in {year}, '
            f'{prs} pull requests and '
            f'{merged} merged pull requests in {year}.'
            f'</desc>'
        ),

        (
            f'<rect x="0.5" y="0.5" '
            f'width="{WIDTH - 1}" '
            f'height="{HEIGHT - 1}" '
            f'rx="10" ry="10" '
            f'fill="{BG}" '
            f'stroke="{BORDER}" />'
        ),
    ]

    # ---------------------------------------------------------
    # Header
    # ---------------------------------------------------------

    elements.append(
        svg_text(
            28,
            35,
            title,
            20,
            TEXT,
            600,
        )
    )

    elements.append(
        svg_text(
            28,
            58,
            (
                f"Activity in {year} • "
                "public + private repositories"
            ),
            12,
            MUTED,
        )
    )

    # ---------------------------------------------------------
    # Top row
    # ---------------------------------------------------------

    columns = [
        (
            85,
            fmt(total_contributions),
            "Contributions",
        ),
        (
            260,
            fmt(commits_all_time),
            "Commits",
        ),
        (
            435,
            fmt(prs),
            "PRs Authored",
        ),
    ]

    for x, value, label in columns:
        elements.append(
            svg_text(
                x,
                103,
                value,
                25,
                ACCENT,
                700,
                "middle",
            )
        )

        elements.append(
            svg_text(
                x,
                124,
                label,
                11,
                MUTED,
                400,
                "middle",
            )
        )

    # ---------------------------------------------------------
    # Informação dos commits do ano
    # ---------------------------------------------------------

    elements.append(
        svg_text(
            260,
            136,
            f"{fmt(commits_year)} in {year}",
            10,
            MUTED,
            400,
            "middle",
        )
    )

    # ---------------------------------------------------------
    # Divider
    # ---------------------------------------------------------

    elements.append(
        f'<line x1="28" y1="151" '
        f'x2="492" y2="151" '
        f'stroke="{BORDER}" />'
    )

    # ---------------------------------------------------------
    # Bottom row
    # ---------------------------------------------------------

    elements.append(
        svg_text(
            80,
            176,
            fmt(merged),
            23,
            GREEN,
            700,
            "middle",
        )
    )

    elements.append(
        svg_text(
            80,
            197,
            "PRs Merged",
            11,
            MUTED,
            400,
            "middle",
        )
    )

    elements.append(
        svg_text(
            260,
            176,
            fmt(restricted),
            23,
            ACCENT,
            700,
            "middle",
        )
    )

    elements.append(
        svg_text(
            260,
            197,
            "Restricted Contributions",
            11,
            MUTED,
            400,
            "middle",
        )
    )

    elements.append(
        svg_text(
            440,
            176,
            str(repositories),
            23,
            ACCENT,
            700,
            "middle",
        )
    )

    elements.append(
        svg_text(
            440,
            197,
            "Repositories with PRs",
            11,
            MUTED,
            400,
            "middle",
        )
    )

    # ---------------------------------------------------------
    # Footer
    # ---------------------------------------------------------

    elements.append(
        svg_text(
            28,
            230,
            "Generated directly from the GitHub API",
            10,
            MUTED,
        )
    )

    elements.append("</svg>")

    return "\n".join(elements)


def main() -> None:
    authenticated_user = current_user()

    if authenticated_user.lower() != USERNAME.lower():
        print(
            f"Warning: GITHUB_USERNAME={USERNAME}, "
            f"but gh is authenticated as "
            f"{authenticated_user}."
        )
        print(
            "Using the authenticated account."
        )
        username_used = authenticated_user
    else:
        username_used = USERNAME

    print("=" * 60)
    print(" GitHub Stats")
    print("=" * 60)
    print(f"User: {username_used}")
    print(f"Year: {YEAR}")
    print()

    stats = collect_stats(
        username_used,
        YEAR,
    )

    OUTPUT_JSON.write_text(
        json.dumps(
            stats,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    svg = make_svg(stats)

    OUTPUT_SVG.write_text(
        svg,
        encoding="utf-8",
    )

    print(
        "Contributions       : "
        f"{stats['contributions']['total']}"
    )

    print(
        "Restricted          : "
        f"{stats['contributions']['restricted']}"
    )

    print(
        "Commits all-time    : "
        f"{stats['commits']['all_time']}"
    )

    print(
        "Commits this year   : "
        f"{stats['commits']['year']}"
    )

    print(
        "PRs authored        : "
        f"{stats['pull_requests']['authored']}"
    )

    print(
        "PRs merged          : "
        f"{stats['pull_requests']['merged']}"
    )

    print(
        "PRs open            : "
        f"{stats['pull_requests']['open']}"
    )

    print(
        "PRs closed unmerged : "
        f"{stats['pull_requests']['closed_unmerged']}"
    )

    print(
        "Repositories w/ PR : "
        f"{len(stats['repositories'])}"
    )

    print()
    print(f"JSON: {OUTPUT_JSON}")
    print(f"SVG : {OUTPUT_SVG}")


if __name__ == "__main__":
    main()