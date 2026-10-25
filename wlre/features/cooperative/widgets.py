"""Cooperative-only Tk controls, retaining their original packing order."""
import tkinter as tk
from tkinter import ttk


def build_cooperative_widgets(page, controls):
    """Attach existing standby and reward widgets to the cooperative page."""
    page.standby_button = ttk.Button(
        controls, text='準備／開始配對',
        command=page.request_standby, state='disabled')
    page.standby_button.pack(side='left', padx=(8, 0))
    page.companion_note = tk.StringVar(
        value='出戰夥伴：沿用一般戰鬥設定（尚未同步）')
    ttk.Label(page, textvariable=page.companion_note,
              style='Muted.TLabel').pack(
                  anchor='w', before=page.body)
    page.standby_note = tk.StringVar(value='協力準備：等待房間同步')
    ttk.Label(page, textvariable=page.standby_note,
              style='Muted.TLabel').pack(
                  anchor='w', before=page.body)
    reward_controls = ttk.Frame(page)
    reward_controls.pack(
        fill='x', before=page.body, pady=(3, 2))
    page.claim_button = ttk.Button(
        reward_controls, text='領取免費協力獎勵',
        command=page.request_reward_claim, state='disabled')
    page.claim_button.pack(side='left')
    page.cancel_reward_button = ttk.Button(
        reward_controls, text='放棄目前寶箱',
        command=page.request_reward_cancel, state='disabled')
    page.cancel_reward_button.pack(side='left', padx=(8, 0))
    page.auto_reward_button = ttk.Button(
        reward_controls, text='開啟免費獎勵自動領取',
        command=page.request_auto_reward, state='disabled')
    page.auto_reward_button.pack(side='left', padx=(8, 0))
    page.reward_note = tk.StringVar(value='獎勵：等待 S186-11 同步；不會自動購買付費寶箱')
    ttk.Label(page, textvariable=page.reward_note, style='Muted.TLabel',
              anchor='w').pack(fill='x', before=page.body)
