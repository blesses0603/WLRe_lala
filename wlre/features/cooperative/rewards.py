"""Display-only cooperative reward status and safe button availability.

No server command or payment is issued here. Network services retain authority.
"""


class CooperativeRewardViewMixin:
    def render_cooperative_rewards(self, data, other, live, activity_blocked, inventory):
            inventory = inventory or {}
            reward = data.get('reward') or {}
            bag_capacity = inventory.get('capacity')
            bag_items = inventory.get('items')
            safe_bag = (
                inventory.get('ready') is True and inventory.get('reliable') is True
                and type(bag_capacity) is int and 1 <= bag_capacity <= 255
                and isinstance(bag_items, dict)
                and bag_capacity - len(bag_items) >= 4
                and not any(inventory.get(k) for k in (
                    'holds', 'alchemy_slots', 'expedition_slots', 'maintenance_slots'))
                and not any((inventory.get('reserved') or {}).values())
                and not (inventory.get('field_supply') or {}).get('pending')
            )
            reward_busy = any(data.get(k) for k in (
                'claim_pending', 'cancel_pending', 'reward_uncertain'))
            reward_operation_busy = any(
                part.get(k) is not None for part in (data, other)
                for k in ('create_pending', 'join_pending', 'leave_pending',
                          'standby_pending', 'start_pending', 'enter_pending'))
            reward_operation_busy = reward_operation_busy or any(
                part.get(k) for part in (data, other)
                for k in ('create_uncertain', 'join_uncertain', 'leave_uncertain',
                          'standby_uncertain', 'start_uncertain', 'enter_uncertain'))
            can_reward = (self.cooperative and bool(live) and not activity_blocked
                          and not reward_busy and not reward_operation_busy
                          and not other.get('room'))
            reward_fp = (reward.get('reward_count'), reward.get('win_stage'),
                         reward.get('open_reward'), reward.get('reward_mark'),
                         reward.get('npc_id')) if reward else None
            self._auto_enabled = bool(data.get('auto_claim_enabled'))
            self._auto_toggle_ready = (
                self.cooperative and bool(live) and not data.get('reward_uncertain'))
            self._claim_ready = (
                can_reward and safe_bag and reward.get('open_reward') == 1
                and type(reward.get('reward_mark')) is int
                and reward['reward_mark'] & 1 != 0
                and data.get('reward_handled_fingerprint') != reward_fp)
            self._cancel_ready = (
                can_reward and reward.get('open_reward') in (1, 2)
                and data.get('reward_handled_fingerprint') != reward_fp)
            if self.cooperative:
                self.auto_reward_button.configure(
                    text='關閉免費獎勵自動領取' if self._auto_enabled
                    else '開啟免費獎勵自動領取')
                if reward.get('open_reward') == 2:
                    reward_text = '付費寶箱待處理；不會自動購買或扣點'
                elif reward.get('open_reward') == 1:
                    reward_text = '免費寶箱待領' if safe_bag else '免費寶箱待領；包包空位未確認'
                elif reward:
                    reward_text = '獎勵已同步，目前沒有開啟的寶箱'
                else:
                    reward_text = '尚未收到 S186-11 協力獎勵狀態'
                    if data.get('phase') == 'matched' and data.get('room') is not None:
                        reward_text += '；戰後房間仍待伺服器確認，不能推定可領獎'
                if data.get('claim_pending') or data.get('cancel_pending'):
                    reward_text = '獎勵操作待伺服器確認，不可重送'
                elif data.get('reward_uncertain'):
                    reward_text = '獎勵操作結果不明，請重新登入確認'
                self.reward_note.set('獎勵：%s；自動領取%s' %
                                     (reward_text, '開' if self._auto_enabled else '關'))
