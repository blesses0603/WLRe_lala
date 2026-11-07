import unittest
from datetime import datetime, timezone
from wlre.ui.display_time import clock_text, DISPLAY_TIMEZONE
from wlre.ui.background_version_controller import _observation_time


class DisplayTimeTests(unittest.TestCase):
    def test_epoch_uses_fixed_utc8(self):
        self.assertEqual(clock_text(0), '08:00:00')
        self.assertEqual(DISPLAY_TIMEZONE.utcoffset(None).total_seconds(), 28800)

    def test_observation_rolls_into_next_day_without_changing_source(self):
        source = '2026-11-07T19:30:00Z'
        self.assertEqual(_observation_time(source), '11-08 03:30:00 UTC+8')
        self.assertEqual(source, '2026-11-07T19:30:00Z')

    def test_offset_inputs_and_invalid_timestamps(self):
        self.assertEqual(_observation_time('2026-11-07T19:30:00+08:00'), '11-07 19:30:00 UTC+8')
        for source in ('bad', None, '2026-11-07T19:30:00'):
            self.assertEqual(_observation_time(source), '尚無')
