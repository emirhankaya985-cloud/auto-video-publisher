"""Only red/green semantics; this test never contacts Meta or Drive."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import toonzone_cover_health_gate as gate


class ToonZoneCoverHealthTests(unittest.TestCase):
    def test_missing_original_cover_is_not_false_green(self):
        self.assertEqual(gate.status('HELD: exact ToonZone cover missing; required_png="S01E13_Part1.png"; fallback disabled.'), "blocked_missing_original_cover")

    def test_valid_due_route_remains_healthy(self):
        self.assertEqual(gate.status('NEXT: S01E13_Part1.mp4; platforms=facebook,instagram'), "not_cover_blocked")

    def test_no_due_is_not_misreported_as_cover_failure(self):
        self.assertEqual(gate.status("NOT DUE: publication hours have not started"), "not_cover_blocked")

    def test_missing_report_is_failure_not_green(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(gate, "Path", return_value=Path(d) / "missing-report.md"):
                self.assertEqual(gate.main(), 1)


if __name__ == "__main__":
    unittest.main()
