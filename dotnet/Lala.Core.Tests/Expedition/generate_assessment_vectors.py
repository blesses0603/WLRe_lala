"""Generate fresh vectors using the actual Python expedition manager helpers.

Only synthetic in-memory catalogs and bag dictionaries are used. No service method,
resource activation, live account, packet send, download or inventory write is invoked.
Run from any directory. The output is deterministic and includes the oracle source hash.
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from wlre.services.expedition import manager


class Rules:
    def __init__(self, values):
        self.values = values

    def snapshot(self):
        return self.values


def generate():
    rng = random.Random(731031)
    cases = []
    previous_catalog, previous_rules = manager.CAT, manager.STACKABLE
    try:
        for _ in range(240):
            items = {
                str(item_id): {
                    'special': rng.choice([0, 0, 1]),
                    'attributes': [dict(kind=rng.choice([64, 64, 27]), effect=rng.randrange(3),
                                        value=rng.choice([0, 99, 100, 101, 130, 300]))
                                   for _ in range(rng.randrange(6))]
                } for item_id in range(1, 7)
            }
            rules = {item_id: rng.choice([True, False]) for item_id in items}
            manager.CAT = {'items': items}
            manager.STACKABLE = Rules(rules)

            def reward():
                return dict(kind=rng.choice([0, 1, 2, 6, 10, 10, 11, 12, 21, 22, 23, 24,
                                             25, 26, 27, 28, 29, 30, 31, 99]),
                            id=rng.randrange(1, 8), value=rng.choice([0, 1, 199, 200, 201, 4294967295]))

            quest = dict(minutes=rng.choice([1, 5, 33, 65535]),
                         rewards=[reward() for _ in range(3)], special_reward=reward())
            level = dict(reduction=rng.choice([0, 1, 100, 333, 500, 999, 1000]))
            inventory = dict(ready=True, reliable=True, capacity=20, items={}, reserved={},
                             alchemy_slots=[], expedition_slots=[], maintenance_slots=[])
            for index in range(1, 16):
                key = str(index)
                inventory['items'][key] = dict(item_id=rng.randrange(1, 7), count=rng.randrange(1, 201),
                    locked=rng.random() < .12, limited_time=rng.choice([0, 0, 1]),
                    available_time=rng.choice([0, 0, 1]))
                inventory['reserved'][key] = rng.randrange(0, 100)
                if rng.random() < .2:
                    inventory[rng.choice(['alchemy_slots', 'expedition_slots', 'maintenance_slots'])].append(key)
            cases.append(dict(items=items, rules=rules, quest=quest, level=level, inventory=inventory,
                duration=manager.duration(quest, level), need=manager.claim_space(quest),
                gains={item_id: manager.faith_gain(item_id) for item_id in items},
                stock=manager.recovery_stock(inventory)))
    finally:
        manager.CAT, manager.STACKABLE = previous_catalog, previous_rules
    return cases


if __name__ == '__main__':
    payload = json.dumps(generate(), separators=(',', ':'))
    source_hash = hashlib.sha256((ROOT / 'wlre/services/expedition/manager.py').read_bytes()).hexdigest()
    Path(__file__).with_name('PythonExpeditionAssessmentVectors.cs').write_text(
        '// Actual Python helper outputs; synthetic catalog and bag doubles, not resource admission.\n'
        'namespace Lala.Core.Tests.Expedition;\ninternal static class PythonExpeditionAssessmentVectors {\n'
        f'internal const string SourceSha256 = "{source_hash}";\n'
        'internal const string Json = """\n' + payload + '\n""";\n}\n', encoding='utf-8')
