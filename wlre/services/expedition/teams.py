"""Exact teams of 1–4, using 1262 GetCondValue and displayed success rates."""
from functools import lru_cache


def _model(role, npcs):
    s = role['stats']; degree = s.get('degree', 0)
    meta = npcs.get(str(role['npc_id']), {})
    return (role['index'], role['npc_id'], role['faith'], s.get('level', 0) + (300 if degree == 2 else degree * 100),
            s.get('potential', 0), s.get('str', 0), s.get('con', 0), s.get('int', 0),
            s.get('wis', 0), s.get('agi', 0), degree,
            meta.get('element'), meta.get('kind'), meta.get('original'))


def _compile(condition, models):
    kind, first, second = condition
    stat = {5: 3, 6: 4, 7: 6, 8: 5, 9: 7, 10: 8, 11: 9, 12: 10}
    weights, unknown = [], []
    for model in models:
        if kind == 0: value = 0
        elif kind == 1: value = 1
        elif kind in stat: value = model[stat[kind]]
        elif kind in (2, 3): value = None if model[11] is None else int(model[11] == first)
        elif kind == 4: value = None if model[13] is None else int(model[13] == first)
        elif kind in (13, 14): value = None if model[12] is None else int(model[12] == (0 if kind == 13 else 1))
        else: value = None
        weights.append(0 if value is None else value)
        unknown.append(int(value is None))
    target = 0 if kind in (0, 3) else second if kind == 2 else 1 if kind == 4 else first
    return kind, target, tuple(weights), tuple(unknown)


def _met(kind, target, value, unknown):
    if kind == 0: return True
    if kind == 3: return False if value else None if unknown else True
    return True if value >= target else None if unknown else False


def condition_met(condition, roles, npcs=None):
    compiled = _compile(condition, [_model(r, npcs or {}) for r in roles])
    kind, target, weights, unknown = compiled
    return _met(kind, target, sum(weights), sum(unknown))


def success_details(quest, roles, npcs=None):
    points = quest.get('success_rate', 0)
    details = []
    for rec in quest.get('recommendations', []):
        if rec['condition'][0] == 0: continue
        met = condition_met(rec['condition'], roles, npcs)
        bonus = rec['bonus'] if met is True else 0
        points += bonus
        details.append({**rec, 'met': met, 'awarded': bonus})
    return {'points': min(1000, points), 'percent': min(1000, points) / 10,
            'complete': points >= 1000 or all(r['met'] is not None for r in details), 'recommendations': details}


def choose_members(quest, roles, threshold, npcs=None):
    eligible = [r for r in roles if r['faith'] >= quest['faith_cost'] or r['faith'] < threshold]
    models = tuple(sorted((_model(r, npcs or {}) for r in eligible), key=lambda m: m[0]))
    recs = tuple((tuple(r['condition']), r['bonus']) for r in quest.get('recommendations', []) if r['condition'][0] and r['bonus'])
    indices = _choose_cached(tuple(quest['condition']), recs, quest.get('success_rate', 0),
                             max(threshold, quest['faith_cost']), models)
    by_index = {r['index']: r for r in eligible}
    return [by_index[index] for index in indices]


@lru_cache(maxsize=256)
def _choose_cached(join, recs, base, threshold, models):
    if not models: return ()
    # Low-cost first, with admissible bounds: no pool truncation or heuristic result.
    models = tuple(sorted(models, key=lambda m: (max(0, threshold - m[2]), sum(m[3:10]), m[0])))
    n = len(models)
    conditions = [_compile(c, models) for c in (join,) + tuple(c for c, _ in recs)]
    gains = [0] + [gain for _, gain in recs]
    # For each suffix, the maximum attainable contribution using <=4 slots.
    upper = []
    for _, _, weights, _ in conditions:
        bounds = []
        for start in range(n + 1):
            top = sorted(weights[start:], reverse=True)[:4]
            bounds.append(tuple(sum(top[:k]) for k in range(5)))
        upper.append(bounds)
    best_key = None
    best_team = ()

    def evaluate(team, totals, unknowns, deficit, cost):
        nonlocal best_key, best_team
        if not team or _met(conditions[0][0], conditions[0][1], totals[0], unknowns[0]) is not True: return
        points = base
        for j, (kind, target, _, _) in enumerate(conditions[1:], 1):
            if _met(kind, target, totals[j], unknowns[j]) is True: points += gains[j]
        indices = tuple(sorted(models[i][0] for i in team))
        key = (min(1000, points), -deficit, -cost, -len(team), tuple(-i for i in indices))
        if best_key is None or key > best_key:
            best_key, best_team = key, indices

    def visit(start, team, totals, unknowns, deficit, cost):
        evaluate(team, totals, unknowns, deficit, cost)
        slots = 4 - len(team)
        if not slots or start == n: return
        kind, target, _, _ = conditions[0]
        if kind == 3:
            if totals[0] or unknowns[0]: return
        elif kind and totals[0] + upper[0][start][slots] < target:
            return
        maximum = base
        for j, (kind, target, _, _) in enumerate(conditions[1:], 1):
            possible = not totals[j] and not unknowns[j] if kind == 3 else totals[j] + upper[j][start][slots] >= target
            if possible: maximum += gains[j]
        if best_key is not None:
            score_bound = min(1000, maximum)
            if score_bound < best_key[0]: return
            if score_bound == best_key[0]:
                if deficit > -best_key[1]: return
                if deficit == -best_key[1] and (cost > -best_key[2] or (cost == -best_key[2] and len(team) >= -best_key[3])): return
        for i in range(start, n):
            model = models[i]
            visit(i + 1, team + (i,), tuple(totals[j] + c[2][i] for j, c in enumerate(conditions)),
                  tuple(unknowns[j] + c[3][i] for j, c in enumerate(conditions)),
                  deficit + max(0, threshold - model[2]), cost + sum(model[3:10]))

    zero = (0,) * len(conditions)
    visit(0, (), zero, zero, 0, 0)
    return best_team
