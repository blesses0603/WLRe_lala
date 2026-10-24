"""Legacy expedition UI entry point. Existing callers and patch points remain stable."""
import copy
import time
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.services.expedition import (
    preferences, validate, faith_gain, duration, recovery_stock, choose_members,
)
# Keep this old import/patch symbol for test and extension compatibility,
# but bind it to the audited active-version loader by default.
from wlre.services.expedition_data import load_active_catalog as load_catalog
from wlre.services.items.combat_resources import CAT, item_name
from wlre.storage import expedition_settings
from wlre.ui.layout import heading, scroll_table
from wlre.ui.expedition_display import task_name, time_text, rewards_text
from wlre.services.expedition_teams import success_details
from wlre.ui.expedition.planner import plan_quests
from wlre.ui.expedition.panel import ExpeditionPanel as _ExpeditionPanel


class ExpeditionPanel(_ExpeditionPanel):
    """Compatibility adapter preserving historic module-level test/extension hooks."""

    def _load_catalog(self):
        return load_catalog()

    def _plan_quests(self, quests, roles, threshold, npcs):
        return plan_quests(quests, roles, threshold, npcs)
