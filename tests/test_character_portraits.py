import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from PIL import Image
from wlre.services.world.character_portraits import PortraitProvider, select_portrait
from wlre.services.world.portrait_mapping import CHARACTERS, parse_npc_portraits


class ImmediateExecutor:
    def submit(self, f, *a):
        future = Future()
        try: future.set_result(f(*a))
        except Exception as error: future.set_exception(error)
        return future


class PortraitTests(unittest.TestCase):
    def setUp(self):
        self.catalog = SimpleNamespace(catalog_key='verified', characters=CHARACTERS,
            npcs={7000: {'icon': '7000', 'palettes': {1: 444444444}},
                  7001: {'icon': '7001_2', 'palettes': {1: 444444444}}},
            image=lambda *args: Image.new('RGBA', (80, 100), 'red'))
        self.state = {'player': {'role_id': 1, 'sex': 2, 'head': 0,
                                'palette1': 444444444, 'palette5': 444444000},
                      'knowledge': {'active_npc_id': 7000, 'companions': {
                          '1': {'ready': True, 'npc_id': 7000, 'stats': {'modeling': 0}}}}}

    def test_all_character_pairs_unique(self):
        self.assertEqual(set(CHARACTERS.values()), set(range(1, 16)))
        self.assertEqual(select_portrait(self.state, 'player', self.catalog)[1], '0001')
        self.state['player']['head'] = 99
        self.assertIsNone(select_portrait(self.state, 'player', self.catalog))

    def test_no_missing_or_ambiguous_observations(self):
        self.state['player']['palette1'] = True
        self.assertIsNone(select_portrait(self.state, 'player', self.catalog))
        self.state['knowledge']['companions']['2'] = self.state['knowledge']['companions']['1'].copy()
        self.assertIsNone(select_portrait(self.state, 'companion', self.catalog))

    def test_companion_modeling_and_missing_data(self):
        self.assertEqual(select_portrait(self.state, 'companion', self.catalog)[1], '7000')
        stats = self.state['knowledge']['companions']['1']['stats']
        stats['modeling'] = 7001
        self.assertEqual(select_portrait(self.state, 'companion', self.catalog)[1], '7001_2')
        stats['modeling'] = 9000
        self.assertIsNone(select_portrait(self.state, 'companion', self.catalog))
        del stats['modeling']
        self.assertIsNone(select_portrait(self.state, 'companion', self.catalog))

    def test_async_ready_version_switch_and_close(self):
        source = [self.catalog]
        provider = PortraitProvider(lambda: source[0], ImmediateExecutor())
        self.assertIsNone(provider.request(self.state, 'player', 40)['image'])
        ready = provider.request(self.state, 'player', 40)
        self.assertEqual(ready['image'].size, (32, 40))
        source[0] = None
        self.assertIsNone(provider.request(self.state, 'player', 40)['image'])
        provider.close(); provider.close()
        self.assertIsNone(provider.request(self.state, 'player', 40)['image'])

    def test_failures_never_fallback_to_other_portrait(self):
        self.catalog.image = lambda *a: None
        provider = PortraitProvider(lambda: self.catalog, ImmediateExecutor())
        provider.request(self.state, 'player', 40)
        result = provider.request(self.state, 'player', 40)
        self.assertIsNone(result['image'])
        self.assertEqual(result['status'], '頭像待同步')
        provider.close()

    def test_transient_failure_retries_with_backoff(self):
        now = [0]
        calls = []
        def image(*args):
            calls.append(1)
            if len(calls) == 1: raise OSError('temporary lock')
            return Image.new('RGBA',(80,100),'red')
        self.catalog.image = image
        provider = PortraitProvider(lambda:self.catalog,ImmediateExecutor(),clock=lambda:now[0])
        provider.request(self.state,'player',40)
        self.assertIsNone(provider.request(self.state,'player',40)['image'])
        for _ in range(5): provider.request(self.state,'player',40)
        self.assertEqual(len(calls),1)
        now[0] = 6
        provider.request(self.state,'player',40)
        self.assertIsNotNone(provider.request(self.state,'player',40)['image'])
        provider.close()

    def test_unreviewed_npc_data_rejected(self):
        with self.assertRaises(ValueError): parse_npc_portraits(b'unknown')

if __name__ == '__main__': unittest.main()
