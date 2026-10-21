"""Synthetic S124 fixtures grounded in official 1262 Lua layouts."""
import unittest

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.daily_tasks import claimable_task_indices


def full_payload():
    # 2 active values, 8 daily, 12 weekly, 4+2+3 marks, 2 booleans.
    return (bytes((75, 120)) + bytes((1, 2, 3, 4, 5, 6, 7, 8))
            + bytes(range(12)) + bytes((1, 2, 3, 4, 0, 1, 5, 6, 7, 1, 0)))


class DailyTaskProtocol(unittest.TestCase):
    def test_snapshot_decode_and_apply(self):
        event = decode(Packet(124, 1, full_payload()))
        self.assertEqual(event["type"], "daily_task_snapshot")
        self.assertEqual(len(event["daily_progress"]), 8)
        self.assertEqual(len(event["weekly_progress"]), 12)
        self.assertEqual(event["weekly_done_mark"], [0, 1])
        state = State()
        state.apply(event)
        self.assertTrue(state.daily_tasks["ready"])
        self.assertEqual(state.daily_tasks["daily_value"], 75)

    def test_groups_and_progress_delta(self):
        state = State()
        state.apply(decode(Packet(124, 2, b"\x05\x09")))
        self.assertEqual(state.daily_tasks["daily_group"], 5)
        self.assertTrue(state.daily_tasks["groups_ready"])
        state.apply(decode(Packet(124, 3, b"\x02\x0b\x03\x01")))
        self.assertEqual(state.daily_tasks["daily_progress"], [])
        state.apply(decode(Packet(124, 1, full_payload())))
        state.apply(decode(Packet(124, 3, b"\x02\x0b\x03\x01")))
        self.assertEqual(state.daily_tasks["daily_progress"][2], 11)

    def test_marks_replacement_and_server_error(self):
        state = State()
        state.apply(decode(Packet(124, 1, full_payload())))
        state.apply(decode(Packet(124, 3, b"\x01" + bytes((100, 150, 1, 2, 3, 4, 0, 2, 5, 6, 7)))))
        self.assertEqual(state.daily_tasks["daily_value"], 100)
        self.assertEqual(state.daily_tasks["weekly_done_mark"], [0, 2])
        state.apply(decode(Packet(124, 5, b"\x0f")))
        self.assertIn("空間不足", state.daily_tasks["last_notice"])

    def test_reject_truncated_and_oversized_snapshot(self):
        for payload in (full_payload()[:-1], full_payload() + b"\x00"):
            with self.subTest(size=len(payload)), self.assertRaises(ProtocolError):
                decode(Packet(124, 1, payload))
        with self.assertRaises(ProtocolError):
            decode(Packet(124, 2, b"\x01"))

    def test_unknown_subtype_does_not_guess_action(self):
        self.assertNotEqual(decode(Packet(124, 10, b"\x01"))["type"], "daily_task_snapshot")

    def test_claim_planner_requires_verified_catalog(self):
        state = State()
        state.apply(decode(Packet(124, 1, full_payload())))
        state.apply(decode(Packet(124, 2, b"\x05\x09")))
        entry = {"index": 91, "id": 3, "group": 5, "cycle": 1, "goal": 3}
        self.assertEqual(claimable_task_indices(state.snapshot(), [entry]), ())
        self.assertEqual(claimable_task_indices(state.snapshot(), [entry], verified=True), (91,))
        self.assertEqual(claimable_task_indices(state.snapshot(), [{**entry, "goal": 4}], verified=True), ())
        self.assertEqual(claimable_task_indices(state.snapshot(), [{**entry, "group": 8}], verified=True), ())
        self.assertEqual(claimable_task_indices(state.snapshot(), [{**entry, "index": 0}], verified=True), ())

    def test_already_claimed_bit_is_not_resubmitted(self):
        state = State()
        state.apply(decode(Packet(124, 1, full_payload())))
        state.apply(decode(Packet(124, 2, b"\x05\x09")))
        entry = {"index": 91, "id": 1, "group": 5, "cycle": 1, "goal": 1}
        self.assertEqual(claimable_task_indices(state.snapshot(), [entry], verified=True), ())


if __name__ == "__main__":
    unittest.main()
