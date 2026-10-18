"""1262 character point distribution: pure checks, never a live server."""
import unittest
from types import SimpleNamespace

from wlre.network.wire import Packet, ProtocolError
from wlre.network.protocol import decode
from wlre.services.battle.attribute_points import (
    baseline, allocation, defaults, begin, apply_event, expire)


class AttributePointsTests(unittest.TestCase):
    def setUp(self):
        self.stats = dict(str=20, con=30, int=40, wis=50, agi=60,
                          attribute_potential=20)
        self.initial = baseline(self.stats)

    def test_layout_matches_lua(self):
        packet, expected = allocation(self.stats, {"str": 2, "int": 3}, self.initial)
        self.assertEqual((packet.main, packet.sub), (8, 1))
        # write1(0), write1(2), INT=27 with u32(3), STR=28 with u32(2).
        self.assertEqual(packet.payload, bytes.fromhex("00 02 1b 03 00 00 00 1c 02 00 00 00"))
        self.assertEqual(expected["attribute_potential"], 15)
        self.assertEqual(expected["str"], 22)

    def test_reject_negative_unknown_and_overspending(self):
        for change in ({"str": -1}, {"str": 21}, {"foo": 1},
                       {"str": 1.0}, {}, {"str": True}):
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                allocation(self.stats, change, self.initial)

    def test_reject_outdated_baseline_and_cap(self):
        with self.assertRaises(ProtocolError):
            allocation(self.stats, {"str": 1}, {**self.initial, "str": 19})
        with self.assertRaises(ProtocolError):
            allocation({**self.stats, "str": 602}, {"str": 1},
                       {**self.initial, "str": 602})

    def test_s8_4_success_has_no_payload(self):
        event = decode(Packet(8, 4, b""))
        self.assertEqual(event["type"], "attribute_allocation_success")

    def test_confirm_requires_server_ack_and_authoritative_values(self):
        state = SimpleNamespace(attribute_allocation=defaults(),
                                knowledge={"player": {"stats": self.stats.copy()}})
        _, expected = allocation(self.stats, {"str": 2}, self.initial)
        begin(state, expected, now=1)
        apply_event(state, {"type": "attribute_allocation_success"})
        self.assertTrue(state.attribute_allocation["pending"])
        state.knowledge["player"]["stats"].update(expected)
        apply_event(state, {"type": "attribute_set"})
        self.assertFalse(state.attribute_allocation["pending"])
        self.assertFalse(state.attribute_allocation["uncertain"])

    def test_timeout_stops_repeat_spend(self):
        state = SimpleNamespace(attribute_allocation=defaults())
        begin(state, {"str": 21}, now=1)
        self.assertFalse(expire(state, now=10))
        self.assertTrue(expire(state, now=20))
        self.assertTrue(state.attribute_allocation["uncertain"])


if __name__ == "__main__":
    unittest.main()
