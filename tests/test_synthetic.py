import json
import unittest

from lifemate.synthetic import render_visible


class SyntheticRenderingTests(unittest.TestCase):
    def visible(self):
        return {"request": "Dời việc đó sang mai", "context": {"timezone": "Asia/Saigon"},
                "history": [
                    {"role": "user", "audio_text": "Tạo lời nhắc"},
                    {"role": "assistant", "text": "", "tool_calls": [{
                        "call_id": "prepared/history/1/0", "name": "reminders.create",
                        "arguments": {"content": "việc", "time": "2027-01-01T08:00:00+07:00"}}],
                     "tool_results": [{"call_id": "prepared/history/1/0",
                        "result_id": "prepared/history/1/0/result",
                        "payload": {"ok": True, "id": "rem_02"}}]}]}

    def test_history_payload_and_ids_survive_rendering(self):
        visible = self.visible()
        original = json.dumps(visible)
        messages, mapping = render_visible(visible, "real-run/case")
        call = next(m for m in messages if m.get("tool_calls"))["tool_calls"][0]
        result = next(m for m in messages if m["role"] == "tool")
        self.assertEqual(call["id"], result["tool_call_id"])
        self.assertEqual(mapping["prepared/history/1/0"], call["id"])
        self.assertEqual(json.loads(result["content"]), {"ok": True, "id": "rem_02"})
        self.assertNotIn("call_id", call["function"])
        self.assertEqual(json.dumps(visible), original)
        self.assertEqual(messages[-1]["content"], visible["request"])

    def test_unpaired_history_is_not_fabricated(self):
        visible = self.visible()
        visible["history"][1]["tool_results"][0]["call_id"] = "wrong"
        with self.assertRaises(ValueError):
            render_visible(visible, "run")

    def test_missing_profile_stays_missing(self):
        messages, _ = render_visible(self.visible(), "run")
        self.assertNotIn("user_profile", messages[0]["content"])
        self.assertNotIn("location", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
