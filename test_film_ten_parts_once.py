"""No-network, fail-closed release tests for ten En Buyuk Saban parts."""
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import publisher_one_shot_gate as gate
from film_series_transition import EXPECTED_PARTS, SERIES_PREFIX, switch_film_source


class FilmTenPartsReleaseTests(unittest.TestCase):
    def test_only_new_marker_on_first_main_push_same_day(self):
        expected=("push","refs/heads/main",gate.FILM_TEN_SUBJECT,
                  [gate.FILM_TEN_MARKER])
        self.assertTrue(gate.is_film_ten_once(*expected,
                          today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_ten_once(*expected,
                           today="2026-11-11",run_attempt="1"))
        self.assertFalse(gate.is_film_ten_once(*expected,
                           today="2026-11-10",run_attempt="2"))
        self.assertFalse(gate.is_film_ten_once("pull_request",
                         *expected[1:],today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_ten_once("push","refs/heads/prod",
                         *expected[2:],today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_ten_once("push","refs/heads/main",
                         gate.FILM_TEN_SUBJECT,(),today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_ten_once("push","refs/heads/main",
                         "release anything",expected[3],today="2026-11-10",run_attempt="1"))

    def test_ci_only_repair_marker_does_not_rearm_first_failed_commit(self):
        original=("push", "refs/heads/main", gate.FILM_TEN_SUBJECT,
                  [gate.FILM_TEN_MARKER])
        repair=("push", "refs/heads/main", gate.FILM_TEN_REPAIR_SUBJECT,
                [gate.FILM_TEN_REPAIR_MARKER])
        self.assertTrue(gate.is_any_film_ten_once(*repair,
                        today="2026-11-10", run_attempt="1"))
        self.assertFalse(gate.is_any_film_ten_once(*repair,
                         today="2026-11-11", run_attempt="1"))
        self.assertFalse(gate.is_any_film_ten_once(*repair,
                         today="2026-11-10", run_attempt="2"))
        self.assertFalse(gate.is_any_film_ten_once(*repair[:3], (),
                         today="2026-11-10", run_attempt="1"))
        self.assertFalse(gate.is_any_film_ten_once("push", "refs/heads/main",
                         gate.FILM_TEN_SUBJECT, [gate.FILM_TEN_REPAIR_MARKER],
                         today="2026-11-10", run_attempt="1"))
        self.assertTrue(gate.is_any_film_ten_once(*original,
                        today="2026-11-10", run_attempt="1"))

    def test_source_release_stays_exactly_first_ten_canonical_parts(self):
        videos=[{"id":f"source-{n}","name":f"{SERIES_PREFIX}_Part_{n}.mp4"}
                for n in range(1,EXPECTED_PARTS+1)]
        catalog={row["name"]:row for row in videos}
        catalog.update({f"{SERIES_PREFIX}_Part_{n}.txt":{"id":f"txt-{n}"}
                        for n in range(1,EXPECTED_PARTS+1)})
        complete=switch_film_source("film",videos,catalog)
        allowed={f"{SERIES_PREFIX}_Part_{n}.mp4" for n in range(1,11)}
        selected=[video for video in complete if video["name"] in allowed]
        self.assertEqual(len(selected),10)
        self.assertEqual([Path(x["name"]).stem for x in selected],
                         [f"{SERIES_PREFIX}_Part_{n}" for n in range(1,11)])
        self.assertEqual(len(complete),EXPECTED_PARTS)
        self.assertEqual(switch_film_source("toonzone",videos,catalog),videos)


if __name__ == "__main__":
    unittest.main()
