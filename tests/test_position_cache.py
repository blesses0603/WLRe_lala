"""Remote history must not accumulate across long runs or map changes."""
import gc
import tracemalloc
import unittest
from wlre.core.state import State, POSITION_CACHE_LIMIT


class PositionCache(unittest.TestCase):
    def state(self):
        state=State();state.player=dict(role_id=1,scene=60000,x=10,y=20)
        state.remember_position(1,10,20);return state
    def test_departures_and_map_changes_release_old_remote_positions(self):
        state=self.state();state.apply(dict(type='walk',role_id=2,x=30,y=40))
        state.apply(dict(type='nearby_leave',role_id=2));self.assertNotIn('2',state.positions)
        state.apply(dict(type='walk',role_id=3,x=50,y=60))
        state.apply(dict(type='position_snapshot',role_id=1,scene=12009,x=100,y=200,source='fixture'))
        self.assertEqual(state.positions,{'1':[100,200]})
        self.assertEqual(state.location['confirmed']['x'],100)
    def test_one_hundred_thousand_remote_updates_are_bounded_and_keep_self(self):
        state=self.state()
        for rid in range(2,100002):state.apply(dict(type='walk',role_id=rid,x=rid%65535,y=1))
        self.assertEqual(len(state.positions),POSITION_CACHE_LIMIT)
        self.assertEqual(state.positions['1'],[10,20]);self.assertIn('100001',state.positions)
        self.assertNotIn('2',state.positions)
    def test_traced_cache_memory_reaches_a_plateau(self):
        state=self.state();tracemalloc.start();self.addCleanup(tracemalloc.stop)
        for rid in range(2,10002):state.remember_position(rid,1,2)
        gc.collect();baseline=tracemalloc.get_traced_memory()[0]
        for rid in range(10002,110002):state.remember_position(rid,1,2)
        gc.collect();current=tracemalloc.get_traced_memory()[0]
        self.assertLess(current-baseline,1024*1024)
        self.assertEqual(len(state.positions),POSITION_CACHE_LIMIT)
