from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any


PALETTE = {
    "obsidian": "#090611",
    "midnight": "#170D2B",
    "royal": "#6D28D9",
    "electric": "#8B5CF6",
    "amethyst": "#A855F7",
    "lavender": "#D8B4FE",
    "silver": "#E2E0F0",
}

CARD_MARKERS = {
    "contribution-calendar.svg": "CONTRIBUTION MATRIX",
    "activity-streak.svg": "ACTIVITY PULSE",
}

ALLOWED_SVG_ELEMENTS = {"g", "rect", "style", "svg", "text"}
MAX_SVG_BYTES = 256 * 1024
URL_VALUE = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)
GRAPHQL_URL = "https://api.github.com/graphql"
REST_API_ROOT = "https://api.github.com"


@dataclass(frozen=True)
class ContributionDay:
    day: date
    count: int
    level: str


@dataclass(frozen=True)
class PrivateAggregate:
    configured: bool
    repository_count: int = 0
    language_bytes: tuple[tuple[str, int], ...] = ()


def _request_json(
    url: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, str]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if payload is not None else "GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "krazykitty-profile-statistics",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        detail = error.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed with HTTP {error.code}: {detail}") from error


def fetch_public_contributions(username: str, token: str) -> list[ContributionDay]:
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks {
              contributionDays {
                contributionCount
                contributionLevel
                date
              }
            }
          }
        }
      }
    }
    """
    payload, _ = _request_json(
        GRAPHQL_URL,
        token,
        payload={"query": query, "variables": {"login": username}},
    )
    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {payload['errors']}")

    try:
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("GitHub did not return a contribution calendar for the requested user") from error

    days: list[ContributionDay] = []
    for week in weeks:
        for item in week["contributionDays"]:
            days.append(
                ContributionDay(
                    day=date.fromisoformat(item["date"]),
                    count=max(0, int(item["contributionCount"])),
                    level=str(item["contributionLevel"]),
                )
            )
    if not days:
        raise RuntimeError("GitHub returned an empty contribution calendar")
    return sorted(days, key=lambda item: item.day)


def fetch_private_aggregates(username: str, token: str) -> PrivateAggregate:
    if not token:
        return PrivateAggregate(configured=False)

    viewer, _ = _request_json(f"{REST_API_ROOT}/user", token)
    if str(viewer.get("login", "")).casefold() != username.casefold():
        raise RuntimeError("PROFILE_STATS_TOKEN must belong to the profile owner")

    repositories: list[dict[str, Any]] = []
    for page in range(1, 21):
        query = urllib.parse.urlencode(
            {
                "visibility": "private",
                "affiliation": "owner",
                "per_page": 100,
                "page": page,
            }
        )
        batch, _ = _request_json(f"{REST_API_ROOT}/user/repos?{query}", token)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected private repository response")
        repositories.extend(
            repository
            for repository in batch
            if repository.get("private")
            and str(repository.get("owner", {}).get("login", "")).casefold() == username.casefold()
        )
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Private repository pagination exceeded the safety limit")

    language_bytes: Counter[str] = Counter()
    for repository in repositories:
        owner = urllib.parse.quote(str(repository["owner"]["login"]), safe="")
        name = urllib.parse.quote(str(repository["name"]), safe="")
        languages, _ = _request_json(f"{REST_API_ROOT}/repos/{owner}/{name}/languages", token)
        if not isinstance(languages, dict):
            raise RuntimeError("GitHub returned an unexpected language response")
        for language, byte_count in languages.items():
            language_bytes[str(language)] += max(0, int(byte_count))

    return PrivateAggregate(
        configured=True,
        repository_count=len(repositories),
        language_bytes=tuple(language_bytes.most_common()),
    )


def calculate_streaks(days: list[ContributionDay]) -> tuple[int, int]:
    longest = 0
    running = 0
    for item in days:
        if item.count > 0:
            running += 1
            longest = max(longest, running)
        else:
            running = 0

    current = 0
    reversed_days = list(reversed(days))
    if reversed_days and reversed_days[0].count == 0:
        reversed_days = reversed_days[1:]
    for item in reversed_days:
        if item.count <= 0:
            break
        current += 1
    return current, longest


def _svg_header(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
        "<style>text{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}</style>"
        f'<rect width="{width}" height="{height}" rx="12" fill="{PALETTE["obsidian"]}" '
        f'stroke="{PALETTE["royal"]}"/>'
    )


def render_contribution_calendar(days: list[ContributionDay]) -> str:
    levels = {
        "NONE": PALETTE["midnight"],
        "FIRST_QUARTILE": PALETTE["royal"],
        "SECOND_QUARTILE": PALETTE["electric"],
        "THIRD_QUARTILE": PALETTE["amethyst"],
        "FOURTH_QUARTILE": PALETTE["lavender"],
    }
    days = days[-371:]
    first_day = days[0].day
    first_sunday = first_day.fromordinal(first_day.toordinal() - ((first_day.weekday() + 1) % 7))
    total = sum(item.count for item in days)
    width, height = 887, 190
    start_x, start_y, step, cell = 74, 64, 14, 11

    parts = [_svg_header(width, height)]
    parts.append(
        f'<text x="28" y="31" fill="{PALETTE["amethyst"]}" font-size="19" font-weight="700">'
        "CONTRIBUTION MATRIX</text>"
    )
    parts.append(
        f'<text x="859" y="31" text-anchor="end" fill="{PALETTE["silver"]}" font-size="13">'
        f"{total} PUBLIC PROFILE CONTRIBUTIONS</text>"
    )

    for label, row in (("MON", 1), ("WED", 3), ("FRI", 5)):
        parts.append(
            f'<text x="28" y="{start_y + row * step + 9}" fill="{PALETTE["lavender"]}" '
            f'font-size="9">{label}</text>'
        )

    rendered_months: set[tuple[int, int]] = set()
    for item in days:
        column = (item.day - first_sunday).days // 7
        row = (item.day.weekday() + 1) % 7
        if not 0 <= column < 53:
            continue
        month_key = (item.day.year, item.day.month)
        if item.day.day <= 7 and month_key not in rendered_months:
            rendered_months.add(month_key)
            parts.append(
                f'<text x="{start_x + column * step}" y="51" fill="{PALETTE["lavender"]}" '
                f'font-size="9">{item.day.strftime("%b").upper()}</text>'
            )
        color = levels.get(item.level, PALETTE["midnight"])
        parts.append(
            f'<rect x="{start_x + column * step}" y="{start_y + row * step}" '
            f'width="{cell}" height="{cell}" rx="2" fill="{color}"/>'
        )

    parts.append(
        f'<text x="28" y="177" fill="{PALETTE["silver"]}" font-size="10">'
        "PUBLIC GRAPH // PRIVATE REPOSITORY IDENTITIES ARE NEVER RENDERED</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _private_summary(aggregate: PrivateAggregate) -> str:
    if not aggregate.configured:
        return "PRIVATE AGGREGATES // OPTIONAL SECRET NOT CONFIGURED"
    total_bytes = sum(byte_count for _, byte_count in aggregate.language_bytes)
    language_parts: list[str] = []
    if total_bytes:
        for language, byte_count in aggregate.language_bytes[:2]:
            percent = round(byte_count * 100 / total_bytes)
            language_parts.append(f"{language.upper()[:18]} {percent}%")
    details = " · ".join(language_parts) if language_parts else "NO LANGUAGE DATA"
    return f"PRIVATE AGGREGATES // {aggregate.repository_count} SELECTED REPOS · {details}"


def render_activity_streak(days: list[ContributionDay], aggregate: PrivateAggregate) -> str:
    current, longest = calculate_streaks(days)
    total = sum(item.count for item in days)
    width, height = 420, 247
    parts = [_svg_header(width, height)]
    parts.append(
        f'<text x="24" y="32" fill="{PALETTE["amethyst"]}" font-size="19" font-weight="700">'
        "ACTIVITY PULSE</text>"
    )
    metrics = (
        ("CURRENT STREAK", f"{current} DAYS"),
        ("LONGEST STREAK", f"{longest} DAYS"),
        ("YEAR TOTAL", str(total)),
    )
    for index, (label, value) in enumerate(metrics):
        y = 70 + index * 36
        parts.append(f'<rect x="24" y="{y - 18}" width="7" height="7" fill="{PALETTE["electric"]}"/>')
        parts.append(f'<text x="43" y="{y - 10}" fill="{PALETTE["lavender"]}" font-size="11">{label}</text>')
        parts.append(
            f'<text x="396" y="{y - 10}" text-anchor="end" fill="{PALETTE["silver"]}" '
            f'font-size="14" font-weight="700">{escape(value)}</text>'
        )
    parts.append(
        f'<text x="24" y="229" fill="{PALETTE["lavender"]}" font-size="9">'
        f"{escape(_private_summary(aggregate))}</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _validate_svg(svg: str, marker: str, path: Path) -> None:
    if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
        raise ValueError(f"{path} exceeds the SVG size limit")
    if marker not in svg:
        raise ValueError(f"{path} is missing the expected marker: {marker}")
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper():
        raise ValueError(f"{path} contains a forbidden document declaration")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        raise ValueError(f"{path} is not valid SVG/XML: {error}") from error
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError(f"{path} does not have an SVG root element")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in ALLOWED_SVG_ELEMENTS:
            raise ValueError(f"{path} contains a forbidden SVG element: {tag}")
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or name in {"href", "src"}:
                raise ValueError(f"{path} contains a forbidden SVG attribute: {name}")
            for raw_url in URL_VALUE.findall(value):
                if not raw_url.strip().strip("\"'").startswith("#"):
                    raise ValueError(f"{path} contains an external SVG resource reference")
        if tag == "style" and element.text:
            if "@import" in element.text.lower() or URL_VALUE.search(element.text):
                raise ValueError(f"{path} contains a forbidden CSS resource reference")


def validate_activity_assets(directory: Path) -> None:
    expected = set(CARD_MARKERS)
    actual = {path.name for path in directory.glob("*.svg")}
    if actual != expected:
        raise ValueError(f"Expected activity assets {sorted(expected)}, found {sorted(actual)}")
    allowed_colors = {color.upper() for color in PALETTE.values()}
    for filename, marker in CARD_MARKERS.items():
        path = directory / filename
        svg = path.read_text(encoding="utf-8")
        _validate_svg(svg, marker, path)
        colors = {
            token.upper()
            for token in re.findall(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b", svg)
        }
        unexpected = sorted(colors - allowed_colors)
        if unexpected:
            raise ValueError(f"{path} contains colors outside the KrazyKitty palette: {unexpected}")


def generate_assets(output_dir: Path, username: str, public_token: str, private_token: str) -> None:
    if not public_token:
        raise RuntimeError("PUBLIC_GITHUB_TOKEN is required")
    days = fetch_public_contributions(username, public_token)
    aggregate = fetch_private_aggregates(username, private_token)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "contribution-calendar.svg").write_text(
        render_contribution_calendar(days), encoding="utf-8", newline="\n"
    )
    (output_dir / "activity-streak.svg").write_text(
        render_activity_streak(days, aggregate), encoding="utf-8", newline="\n"
    )
    validate_activity_assets(output_dir)


def publish_assets(source_dir: Path, output_dir: Path) -> None:
    validate_activity_assets(source_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in CARD_MARKERS:
        temporary = (output_dir / filename).with_suffix(".svg.tmp")
        shutil.copyfile(source_dir / filename, temporary)
        temporary.replace(output_dir / filename)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render safe ultraviolet GitHub activity SVGs.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--publish", type=Path, nargs=2, metavar=("SOURCE", "OUTPUT"))
    parser.add_argument("--username", default="krazykitty2503")
    args = parser.parse_args()
    if sum((args.output is not None, args.check is not None, args.publish is not None)) != 1:
        parser.error("choose exactly one mode: --output, --check, or --publish")
    return args


def main() -> None:
    args = parse_args()
    if args.check is not None:
        validate_activity_assets(args.check)
    elif args.publish is not None:
        publish_assets(*args.publish)
    else:
        generate_assets(
            args.output,
            args.username,
            os.environ.get("PUBLIC_GITHUB_TOKEN", ""),
            os.environ.get("PROFILE_STATS_TOKEN", ""),
        )


if __name__ == "__main__":
    main()

