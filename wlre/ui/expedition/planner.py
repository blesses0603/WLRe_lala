"""Expedition team prediction, with background work kept off the Tk event loop."""
import copy
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from wlre.services.expedition import choose_members
from wlre.services.expedition_teams import success_details


def plan_quests(quests, roles, threshold, npcs):
    result = {}
    for quest in quests:
        team = choose_members(quest, roles, threshold, npcs)
        result[str(quest['id'])] = (team, success_details(quest, team, npcs) if team else {})
    return result



class ExpeditionPlannerMixin:
    def _plan_quests(self, quests, roles, threshold, npcs):
        return plan_quests(quests, roles, threshold, npcs)

    def request_plans(self, quests, idle, threshold):
        key = repr(([q['id'] for q in quests], idle, threshold))
        if key == self.plan_key: return
        self.plan_key = key
        self.plans = {}
        if self.plan_future is not None: self.plan_future.cancel()
        if len(idle) <= 10:
            self.plan_future = None
            self.plans = self._plan_quests(quests, idle, threshold, self.catalog.get('npcs', {}))
            return
        if self.planner is None: self.planner = ThreadPoolExecutor(max_workers=1, thread_name_prefix='expedition-planner')
        self.plan_future = self.planner.submit(self._plan_quests, quests, copy.deepcopy(idle), threshold, self.catalog.get('npcs', {}))
        if self.plan_job is None: self.plan_job = self.after(50, self.collect_plans)

    def collect_plans(self):
        self.plan_job = None
        if self.plan_future is None: return
        if not self.plan_future.done():
            self.plan_job = self.after(50, self.collect_plans)
            return
        try: self.plans = self.plan_future.result()
        except Exception as exc:
            self.status.set('成功率計算失敗：' + str(exc))
            self.plans = {}
        self.plan_future = None
        self.signature = None
        self.render(self.app.snapshot)

