"""Offline receipt matching and daily epoch isolation regressions."""
import unittest
from copy import deepcopy
from wlre.network.wire import Packet
from wlre.services import daily_tasks as daily, star_ark as ark
import test_daily_task_runtime as daily_fixture
import test_star_ark as ark_fixture


class DailyReceiptSafetyTests(unittest.TestCase):
    setUp = daily_fixture.DailyRuntimeTests.setUp
    feed = daily_fixture.DailyRuntimeTests.feed

    def claim_items(self, awards=None):
        self.data['tasks'][0]['awards'] = awards or [dict(kind=10, id=100, value=2)]
        self.assertEqual(len(daily.tick(self.state, True, 1)), 1)
        self.feed(daily_fixture.notice())
        self.feed(daily_fixture.marks(day=1))

    def bag(self, *items):
        self.state.apply(dict(type='bag_snapshot', capacity=10, items=[
            dict(index=i+1, item_id=sid, count=count) for i, (sid, count) in enumerate(items)]))

    def test_unrelated_bag_update_never_confirms_and_timeout_never_resends(self):
        self.claim_items()
        self.bag((999, 2))
        daily.tick(self.state, True, 2)
        self.assertIsNotNone(self.state.daily_tasks['pending'])
        self.assertEqual(daily.tick(self.state, True, 21), [])
        self.assertTrue(self.state.daily_tasks['uncertain'])
        self.bag((100, 2))
        self.assertEqual(daily.tick(self.state, True, 22), [])

    def test_partial_and_duplicate_snapshots_need_full_positive_delta(self):
        self.bag((100, 5))
        self.claim_items([dict(kind=10, id=100, value=2), dict(kind=11, id=100, value=1),
                          dict(kind=10, id=200, value=1)])
        for items in (((100, 5),), ((100, 7), (200, 1)), ((100, 7), (200, 1)),
                      ((100, 8),), ((100, 3), (100, 5))):
            self.bag(*items)
            self.assertEqual(daily.tick(self.state, True, 2), [])
            self.assertIsNotNone(self.state.daily_tasks['pending'])
        self.bag((100, 3), (100, 5), (200, 1))
        daily.tick(self.state, True, 3)
        self.assertIsNone(self.state.daily_tasks['pending'])
        self.assertFalse(self.state.daily_tasks['uncertain'])

    def test_unreliable_matching_bag_cannot_confirm(self):
        self.claim_items()
        self.bag((100, 2))
        self.state.inventory['reliable'] = False
        daily.tick(self.state, True, 2)
        self.assertIsNotNone(self.state.daily_tasks['pending'])

    def test_matching_items_still_require_exact_mark_and_notice_kind(self):
        self.data['tasks'][0]['awards'] = [dict(kind=10, id=100, value=2)]
        daily.tick(self.state, True, 1)
        self.bag((100, 2))
        self.feed(daily_fixture.marks(day=2))
        self.feed(daily_fixture.notice(2))
        daily.tick(self.state, True, 2)
        self.assertIsNotNone(self.state.daily_tasks['pending'])
        self.feed(daily_fixture.marks(day=3))
        daily.tick(self.state, True, 3)
        self.assertIsNotNone(self.state.daily_tasks['pending'])
        self.feed(daily_fixture.notice())
        daily.tick(self.state, True, 4)
        self.assertIsNone(self.state.daily_tasks['pending'])

    def test_chest_batch_aggregates_duplicate_item_awards_across_chests(self):
        for row in self.data['rewards']:
            row['awards'] = [dict(kind=10, id=100, value=1)]
        self.feed(daily_fixture.marks(day=1, week=(0, 1)))
        self.assertEqual(daily.tick(self.state, True, 1), [Packet(124, 2, b'\x01')])
        self.feed(daily_fixture.notice(2))
        self.feed(daily_fixture.marks(day=1, week=(0, 1), chest=1, event=2))
        self.bag((100, 1))
        daily.tick(self.state, True, 2)
        self.assertIsNotNone(self.state.daily_tasks['pending'])
        self.bag((100, 2))
        daily.tick(self.state, True, 3)
        self.assertIsNone(self.state.daily_tasks['pending'])

    def test_old_epoch_receipt_cannot_authorize_new_claim(self):
        self.claim_items()
        self.feed(Packet(124, 3, b'\x02\x00\x01\x01'))
        self.feed(daily_fixture.snapshot())
        self.feed(Packet(124, 2, b'\x01\x02'))
        self.bag((100, 2))
        self.feed(daily_fixture.notice())
        self.feed(daily_fixture.marks(day=1))
        for now in (2, 25, 100):
            self.assertEqual(daily.tick(self.state, True, now), [])
        self.assertTrue(self.state.daily_tasks['uncertain'])
        self.assertIsNone(self.state.daily_tasks['pending'])


class DailyEpochSafetyTests(unittest.TestCase):
    setUp = ark_fixture.StarArkTests.setUp
    feed = ark_fixture.StarArkTests.feed
    coin = ark_fixture.StarArkTests.coin
    open_question = ark_fixture.StarArkTests.open_question

    def test_progress_reset_invalidates_old_correct_answer_before_tick(self):
        self.open_question()
        ark.command(self.state, dict(action='answer', index=2), True, 2)
        self.state.daily_tasks['daily_progress'] = [1]*8
        before = self.question_db.read_bytes()
        self.feed(Packet(124, 3, b'\x02\x00\x01\x01'))
        self.feed(Packet(191, 12, b'\x01\x02'))
        self.assertEqual(self.question_db.read_bytes(), before)
        self.assertTrue(self.state.star_ark['uncertain'])

    def test_reset_or_unknown_update_blocks_both_result_types_after_resync(self):
        for event in (dict(type='daily_task_progress', cycle=1, task_id=1, count=0),
                      dict(type='daily_task_progress', cycle=2, task_id=12, count=0),
                      dict(type='daily_task_unknown_update', kind=99)):
            for correct in (False, True):
                with self.subTest(event=event, correct=correct):
                    self.setUp()
                    self.open_question()
                    ark.command(self.state, dict(action='answer', index=2), True, 2)
                    d = self.state.daily_tasks
                    d.update(daily_progress=[1]*8, weekly_progress=[1]*12, groups_ahead=True, awaiting_groups=True,
                             handled=['old'])
                    generation = d['generation']
                    before = self.question_db.read_bytes()
                    question = deepcopy(self.state.star_ark['question'])
                    self.state.apply(event)
                    self.assertEqual(d['generation'], generation+1)
                    self.assertEqual(d['handled'], [])
                    self.assertFalse(d['groups_ahead'])
                    self.assertFalse(d['awaiting_groups'])
                    self.feed(daily_fixture.snapshot())
                    self.assertFalse(d['groups_ready'])
                    self.feed(Packet(124, 2, b'\x01\x02'))
                    self.assertTrue(d['groups_ready'])
                    self.feed(Packet(191, 12, bytes([correct, 2])))
                    self.assertEqual(self.question_db.read_bytes(), before)
                    self.assertEqual(self.state.star_ark['question'], question)
                    self.assertTrue(self.state.star_ark['uncertain'])
                    self.assertIsNone(self.state.star_ark['pending'])
                    self.assertEqual(ark.tick(self.state, True, 50), [])
