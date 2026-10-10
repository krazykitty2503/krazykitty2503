from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from style_profile_stats import CARD_SPECS, PALETTE, publish_cards, style_cards, validate_cards


class StyleProfileStatsTests(unittest.TestCase):
    def _temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def _write_source_cards(self, source_dir: Path) -> None:
        for index, (source_name, (_, marker)) in enumerate(CARD_SPECS.items()):
            accent = "#ff0000" if index == 1 else "#9745f5"
            (source_dir / source_name).write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                f'<rect fill="#000000" stroke="{accent}" />'
                f'<text fill="#ffffff">{marker.removeprefix(">").removesuffix("</text>")}</text>'
                "</svg>",
                encoding="utf-8",
            )

    def test_styles_and_validates_expected_cards(self) -> None:
        with self._temporary_directory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            source_dir.mkdir()
            self._write_source_cards(source_dir)

            style_cards(source_dir, output_dir)
            validate_cards(output_dir)

            output = "".join(path.read_text(encoding="utf-8") for path in output_dir.glob("*.svg"))
            self.assertNotIn("#ff0000", output.lower())
            self.assertTrue(any(color in output for color in PALETTE))

    def test_rejects_missing_generator_output(self) -> None:
        with self._temporary_directory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            source_dir.mkdir()

            with self.assertRaises(FileNotFoundError):
                style_cards(source_dir, root / "output")

    def test_rejects_tampered_out_of_palette_asset(self) -> None:
        with self._temporary_directory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            source_dir.mkdir()
            self._write_source_cards(source_dir)
            style_cards(source_dir, output_dir)

            card = output_dir / "github-stats.svg"
            card.write_text(card.read_text(encoding="utf-8").replace("#090611", "#ff0000"), encoding="utf-8")

            with self.assertRaises(ValueError):
                validate_cards(output_dir)

    def test_rejects_active_svg_content(self) -> None:
        with self._temporary_directory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            source_dir.mkdir()
            self._write_source_cards(source_dir)
            style_cards(source_dir, output_dir)

            card = output_dir / "github-stats.svg"
            card.write_text(
                card.read_text(encoding="utf-8").replace("</svg>", "<script>alert(1)</script></svg>"),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                validate_cards(output_dir)

    def test_publishes_only_validated_fixed_assets(self) -> None:
        with self._temporary_directory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            artifact_dir = root / "artifact"
            published_dir = root / "published"
            source_dir.mkdir()
            self._write_source_cards(source_dir)
            style_cards(source_dir, artifact_dir)

            publish_cards(artifact_dir, published_dir)

            self.assertEqual(
                {output_name for output_name, _ in CARD_SPECS.values()},
                {path.name for path in published_dir.glob("*.svg")},
            )
            validate_cards(published_dir)


if __name__ == "__main__":
    unittest.main()

