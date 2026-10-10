from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from render_profile_activity import (
    ContributionDay,
    PrivateAggregate,
    calculate_streaks,
    publish_assets,
    render_activity_streak,
    render_contribution_calendar,
    validate_activity_assets,
)


class RenderProfileActivityTests(unittest.TestCase):
    def _days(self) -> list[ContributionDay]:
        start = date(2025, 10, 5)
        counts = [1, 2, 0, 3, 4, 5, 0, 2]
        levels = ["FIRST_QUARTILE", "SECOND_QUARTILE", "NONE", "THIRD_QUARTILE"]
        return [
            ContributionDay(start + timedelta(days=index), count, levels[index % len(levels)])
            for index, count in enumerate(counts)
        ]

    def _write_assets(self, directory: Path) -> None:
        days = self._days()
        aggregate = PrivateAggregate(True, 3, (("Python", 80), ("TypeScript", 20)))
        directory.mkdir()
        (directory / "contribution-calendar.svg").write_text(
            render_contribution_calendar(days), encoding="utf-8"
        )
        (directory / "activity-streak.svg").write_text(
            render_activity_streak(days, aggregate), encoding="utf-8"
        )

    def test_calculates_current_and_longest_streak(self) -> None:
        self.assertEqual((1, 3), calculate_streaks(self._days()))

    def test_renders_and_validates_both_assets(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            directory = Path(temporary) / "assets"
            self._write_assets(directory)
            validate_activity_assets(directory)
            output = "".join(path.read_text(encoding="utf-8") for path in directory.glob("*.svg"))
            self.assertIn("PRIVATE AGGREGATES // 3 SELECTED REPOS", output)
            self.assertNotIn("repository-name", output)

    def test_calendar_renders_each_month_label_once(self) -> None:
        start = date(2025, 10, 1)
        days = [
            ContributionDay(start + timedelta(days=index), 1, "FIRST_QUARTILE")
            for index in range(70)
        ]
        svg = render_contribution_calendar(days)
        self.assertEqual(1, svg.count(">OCT</text>"))
        self.assertEqual(1, svg.count(">NOV</text>"))
        self.assertEqual(1, svg.count(">DEC</text>"))

    def test_private_aggregate_has_no_repository_identity_field(self) -> None:
        aggregate = PrivateAggregate(True, 1, (("Python", 100),))
        self.assertFalse(hasattr(aggregate, "repository_names"))
        self.assertIn("PYTHON 100%", render_activity_streak(self._days(), aggregate))

    def test_rejects_active_svg_content(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            directory = Path(temporary) / "assets"
            self._write_assets(directory)
            path = directory / "activity-streak.svg"
            path.write_text(path.read_text(encoding="utf-8").replace("</svg>", "<script/></svg>"), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_activity_assets(directory)

    def test_publishes_validated_fixed_assets(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            self._write_assets(source)
            publish_assets(source, output)
            validate_activity_assets(output)


if __name__ == "__main__":
    unittest.main()

