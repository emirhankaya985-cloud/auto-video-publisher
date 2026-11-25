"""Never post in tests: prove exact one-shot gap identity and boundaries."""
import unittest
from film_series_transition import EXPECTED_PARTS, SERIES_PREFIX, switch_film_source
import publisher_one_shot_gate as gate


class OwnerGapTests(unittest.TestCase):
    def test_single_new_main_push_only_on_10_nov(self):
        args=("push", "refs/heads/main", gate.FILM_GAP_SUBJECT,
              [gate.FILM_GAP_MARKER])
        self.assertTrue(gate.is_film_gap_once(*args, today="2026-11-10",
                                               run_attempt="1"))
        self.assertFalse(gate.is_film_gap_once(*args, today="2026-11-11",
                                                run_attempt="1"))
        self.assertFalse(gate.is_film_gap_once(*args, today="2026-11-10",
                                                run_attempt="2"))
        self.assertFalse(gate.is_film_gap_once("pull_request", *args[1:],
                                                today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_gap_once("push", "refs/heads/main",
                                               gate.FILM_GAP_SUBJECT, [],
                                               today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_gap_once("push", "refs/heads/main",
                                               "unrelated commit", args[3],
                                               today="2026-11-10",run_attempt="1"))

    def test_only_part6_through_part10_are_eligible(self):
        videos=[{"id":str(n), "name":f"{SERIES_PREFIX}_Part_{n}.mp4"}
                for n in range(1,EXPECTED_PARTS+1)]
        catalog={x["name"]:x for x in videos}
        catalog.update({f"{SERIES_PREFIX}_Part_{n}.txt":{"id":f"txt-{n}"}
                        for n in range(1,EXPECTED_PARTS+1)})
        all_parts=switch_film_source("film",videos,catalog)
        allowed={f"{SERIES_PREFIX}_Part_{n}.mp4" for n in range(6,11)}
        result=[v for v in all_parts if v["name"] in allowed]
        self.assertEqual([v["name"] for v in result],
                         [f"{SERIES_PREFIX}_Part_{n}.mp4" for n in range(6,11)])
        self.assertEqual(len(result),5)
        self.assertEqual(switch_film_source("toonzone",videos,catalog),videos)

if __name__=="__main__":
    unittest.main()
