"""Fail-closed serial catch-up tests, with no provider writes or credentials."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_public_link_runtime import runtime


def item(part, route="film"):
    return {
        "route": route, "page": "Film Mağarası",
        "id": "drive-" + str(part), "name": "Film_Part_" + str(part) + ".mp4",
        "platforms": ["instagram"], "captions": {"instagram": "Part " + str(part)},
    }


def entry(plan, status="intent", post_id=None):
    result = {
        "route": plan["route"], "platform": "instagram",
        "file": plan["name"], "status": status, "run_id": "555",
        "caption_hash": runtime.caption_key(plan["captions"]["instagram"]),
        "publish_caption": plan["captions"]["instagram"],
    }
    if post_id:
        result["post_id"] = post_id
    return result


class OrderedBatchGuard(unittest.TestCase):
    def test_first_part_must_be_confirmed_before_next_post(self):
        first, second = item(1), item(2)
        state = {"entries": {
            "film:instagram:drive-1": entry(first, status="uncertain"),
            "film:instagram:drive-2": entry(second),
        }}
        self.assertFalse(runtime.ordered_predecessors_confirmed(
            [first, second], 1, second, state))
        state["entries"]["film:instagram:drive-1"].update(
            status="done", post_id="real-confirmed-id")
        self.assertTrue(runtime.ordered_predecessors_confirmed(
            [first, second], 1, second, state))
        state["entries"]["film:instagram:drive-1"].pop("post_id")
        self.assertFalse(runtime.ordered_predecessors_confirmed(
            [first, second], 1, second, state))
        self.assertTrue(runtime.ordered_predecessors_confirmed(
            [first, item(2, "tarladaki")], 1, item(2, "tarladaki"), state))

    def test_unattempted_successor_released_only_with_exact_intent(self):
        next_item = item(2)
        key = "film:instagram:drive-2"
        original = entry(next_item)
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "555"}):
            state = {"entries": {key: dict(original)}}
            runtime.hold_unattempted_ordered_successor(next_item, state)
            self.assertEqual(state["entries"][key]["status"], "ready")
            self.assertFalse(state["entries"][key]["failure"]["external_post_attempted"])
            for changed in (dict(original, status="uncertain"),
                            dict(original, run_id="older-run"),
                            dict(original, caption_hash="different"),
                            dict(original, file="other.mp4")):
                state = {"entries": {key: changed}}
                runtime.hold_unattempted_ordered_successor(next_item, state)
                self.assertEqual(state["entries"][key], changed)

    def test_failed_resumed_part_does_not_upload_later_part(self):
        first, second = item(1), item(2)
        first["resume_container_id"] = "old-unfinished-container"
        state = {"entries": {
            "film:instagram:drive-1": entry(first),
            "film:instagram:drive-2": entry(second),
        }}
        with tempfile.TemporaryDirectory() as tmp:
            state_path, plan_path = Path(tmp) / "state.json", Path(tmp) / "plan.json"
            state_path.write_text(json.dumps(state))
            plan_path.write_text(json.dumps([first, second]))
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "555"}), \
                 patch.object(runtime, "STATE", state_path), \
                 patch.object(runtime, "PLAN", plan_path), \
                 patch.object(runtime, "load_meta_auth", return_value={
                     "pages": [{"page_name": "Film Mağarası"}]}), \
                 patch.object(runtime, "publish_existing_ig_intent", return_value=False), \
                 patch.object(runtime, "download", side_effect=AssertionError("unexpected download")) as download:
                with self.assertRaises(SystemExit) as raised:
                    runtime.publish()
            self.assertEqual(raised.exception.code, 1)
            download.assert_not_called()
            updated = json.loads(state_path.read_text())
            self.assertEqual(updated["entries"]["film:instagram:drive-1"]["status"], "intent")
            self.assertEqual(updated["entries"]["film:instagram:drive-2"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
