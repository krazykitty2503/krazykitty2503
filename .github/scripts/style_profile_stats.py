from __future__ import annotations

import argparse
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


PALETTE = (
    "#090611",
    "#170D2B",
    "#6D28D9",
    "#8B5CF6",
    "#A855F7",
    "#D8B4FE",
    "#E2E0F0",
)

BASE_REPLACEMENTS = {
    "#000000": "#090611",
    "#9745F5": "#A855F7",
    "#9F4BFF": "#8B5CF6",
    "#FFFFFF": "#E2E0F0",
}

LANGUAGE_COLORS = ("#6D28D9", "#8B5CF6", "#A855F7", "#D8B4FE", "#E2E0F0")

CARD_SPECS = {
    "0-profile-details.svg": ("activity-overview.svg", "contributions in the last year"),
    "1-repos-per-language.svg": ("languages-by-repository.svg", "Top Languages by Repo"),
    "2-most-commit-language.svg": ("languages-by-commit.svg", "Top Languages by Commit"),
    "3-stats.svg": ("github-stats.svg", ">Stats</text>"),
}

ACTIVITY_CARD_SPECS = {
    "contribution-calendar.svg": "CONTRIBUTION MATRIX",
    "activity-streak.svg": "ACTIVITY PULSE",
}

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b")
URL_VALUE = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)
ALLOWED_SVG_ELEMENTS = {"clipPath", "g", "line", "path", "rect", "style", "svg", "text"}
MAX_SVG_BYTES = 512 * 1024


def _validate_svg(svg: str, marker: str, path: Path) -> None:
    if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
        raise ValueError(f"{path} exceeds the {MAX_SVG_BYTES}-byte SVG size limit")
    if marker not in svg:
        raise ValueError(f"{path} does not contain the expected card marker: {marker!r}")
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper():
        raise ValueError(f"{path} contains a forbidden document type or entity declaration")
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
            attribute_name = attribute.rsplit("}", 1)[-1].lower()
            if attribute_name.startswith("on") or attribute_name in {"href", "src"}:
                raise ValueError(f"{path} contains a forbidden SVG attribute: {attribute_name}")
            for raw_url in URL_VALUE.findall(value):
                if not raw_url.strip().strip("\"'").startswith("#"):
                    raise ValueError(f"{path} contains an external SVG resource reference")
        if tag == "style" and element.text:
            for raw_url in URL_VALUE.findall(element.text):
                if not raw_url.strip().strip("\"'").startswith("#"):
                    raise ValueError(f"{path} contains an external CSS resource reference")
            if "@import" in element.text.lower():
                raise ValueError(f"{path} contains a forbidden CSS import")


def _recolor(svg: str, language_color_map: dict[str, str]) -> str:
    allowed = {color.upper(): color for color in PALETTE}

    def replace(match: re.Match[str]) -> str:
        original = match.group(0).upper()
        if original in BASE_REPLACEMENTS:
            return BASE_REPLACEMENTS[original]
        if original in allowed:
            return allowed[original]
        if original not in language_color_map:
            language_color_map[original] = LANGUAGE_COLORS[len(language_color_map) % len(LANGUAGE_COLORS)]
        return language_color_map[original]

    return HEX_COLOR.sub(replace, svg)


def _validate_known_cards(directory: Path, specs: dict[str, str]) -> None:
    allowed = {color.upper() for color in PALETTE}
    for output_name, marker in specs.items():
        output_path = directory / output_name
        if not output_path.is_file():
            raise FileNotFoundError(f"Expected styled card is missing: {output_path}")
        svg = output_path.read_text(encoding="utf-8")
        _validate_svg(svg, marker, output_path)
        unexpected = sorted({color.upper() for color in HEX_COLOR.findall(svg)} - allowed)
        if unexpected:
            raise ValueError(
                f"{output_path} contains colors outside the KrazyKitty palette: "
                + ", ".join(unexpected)
            )


def style_cards(source_dir: Path, output_dir: Path) -> None:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    language_color_map: dict[str, str] = {}
    cards: list[tuple[Path, str, str]] = []
    for source_name, (output_name, marker) in CARD_SPECS.items():
        source_path = source_dir / source_name
        if not source_path.is_file():
            raise FileNotFoundError(f"Expected generated card is missing: {source_path}")
        svg = source_path.read_text(encoding="utf-8")
        _validate_svg(svg, marker, source_path)
        cards.append((output_dir / output_name, marker, svg))
    output_dir.mkdir(parents=True, exist_ok=True)
    for output_path, marker, svg in cards:
        styled = _recolor(svg, language_color_map)
        _validate_svg(styled, marker, output_path)
        output_path.write_text(styled, encoding="utf-8", newline="\n")
    validate_cards(output_dir)


def validate_cards(output_dir: Path) -> None:
    summary_specs = {output_name: marker for output_name, marker in CARD_SPECS.values()}
    _validate_known_cards(output_dir, summary_specs)
    actual = {path.name for path in output_dir.glob("*.svg")}
    expected = set(summary_specs)
    if actual != expected:
        raise ValueError(f"Expected summary assets {sorted(expected)}, found {sorted(actual)}")


def validate_profile_assets(output_dir: Path) -> None:
    summary_specs = {output_name: marker for output_name, marker in CARD_SPECS.values()}
    all_specs = {**summary_specs, **ACTIVITY_CARD_SPECS}
    _validate_known_cards(output_dir, all_specs)
    actual = {path.name for path in output_dir.glob("*.svg")}
    expected = set(all_specs)
    if actual != expected:
        raise ValueError(f"Expected profile assets {sorted(expected)}, found {sorted(actual)}")


def publish_cards(source_dir: Path, output_dir: Path) -> None:
    validate_cards(source_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for output_name, _ in CARD_SPECS.values():
        source_path = source_dir / output_name
        output_path = output_dir / output_name
        temporary_path = output_path.with_suffix(".svg.tmp")
        shutil.copyfile(source_path, temporary_path)
        temporary_path.replace(output_path)
    _validate_known_cards(
        output_dir,
        {output_name: marker for output_name, marker in CARD_SPECS.values()},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply and verify the KrazyKitty ultraviolet palette.")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--check-profile", type=Path)
    parser.add_argument("--publish", type=Path, nargs=2, metavar=("SOURCE", "OUTPUT"))
    args = parser.parse_args()
    style_mode = args.source is not None or args.output is not None
    if style_mode and (args.source is None or args.output is None):
        parser.error("--source and --output must be provided together")
    if sum((style_mode, args.check is not None, args.check_profile is not None, args.publish is not None)) != 1:
        parser.error("choose exactly one mode")
    return args


def main() -> None:
    args = parse_args()
    if args.check is not None:
        validate_cards(args.check)
    elif args.check_profile is not None:
        validate_profile_assets(args.check_profile)
    elif args.publish is not None:
        publish_cards(*args.publish)
    else:
        style_cards(args.source, args.output)


if __name__ == "__main__":
    main()

