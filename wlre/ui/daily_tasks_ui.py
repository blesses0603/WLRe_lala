"""Read-only daily and weekly task evidence viewer.

Until the 1262 binary task catalog is verified, task names, goals and
automatic claims are unavailable. Never provide a misleading Start button.
"""
import tkinter as tk
from tkinter import ttk


class DailyTaskPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=14)
        self.app = app
        ttk.Label(self, text="每日／每週任務", style="Heading.TLabel").pack(anchor="w")
        self.status = tk.StringVar(value="尚未收到伺服器每日任務狀態")
        ttk.Label(self, textvariable=self.status, style="Muted.TLabel",
                  wraplength=890, justify="left").pack(anchor="w", pady=(8, 12), fill="x")
        columns = ("cycle", "id", "count", "received")
        self.table = ttk.Treeview(self, columns=columns, show="headings", height=16)
        for key, title, width in (
            ("cycle", "週期", 100), ("id", "任務序號", 130),
            ("count", "伺服器進度", 180), ("received", "領取標記", 140),
        ):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="center", stretch=key == "count")
        scroller = ttk.Scrollbar(self, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroller.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroller.pack(side="right", fill="y")

    def render(self, state):
        daily = state.get("daily_tasks") or {}
        self.table.delete(*self.table.get_children())
        if not daily.get("ready"):
            self.status.set("每日任務尚未同步。未登入或伺服器尚未發送 S124-1。")
            return
        group_text = (
            "每日群組 %s／每週群組 %s" % (
                daily.get("daily_group"), daily.get("weekly_group"))
            if daily.get("groups_ready") else "任務群組尚未同步"
        )
        self.status.set(
            "每日活躍 %s／每週活躍 %s；%s。\n"
            "目前提供伺服器進度檢視；1262 任務／獎勵資料表尚未核對，"
            "因此不自動領取，也不執行可能消耗資源的任務。\n%s" % (
                daily.get("daily_value"), daily.get("weekly_value"),
                group_text, daily.get("last_notice") or ""))
        for cycle, key, count_key, mark_key in (
            ("每日", "daily_progress", "daily_group", "daily_done_mark"),
            ("每週", "weekly_progress", "weekly_group", "weekly_done_mark"),
        ):
            mark = daily.get(mark_key, 0)
            for idx, count in enumerate(daily.get(key) or [], 1):
                bit = (idx - 1) % 8
                value = mark[(idx - 1) // 8] if isinstance(mark, list) else mark
                claimed = bool(value & (1 << bit))
                self.table.insert("", "end", values=(
                    cycle, idx, count, "已領取" if claimed else "未領取／未完成"))
