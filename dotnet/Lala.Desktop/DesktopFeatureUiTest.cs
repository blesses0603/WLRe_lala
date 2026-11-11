using System.Collections.Immutable;
using Avalonia.Controls;
using Lala.Core.Gameplay;
using Lala.Core.Battle;
using Lala.Core.State;

namespace Lala.Desktop;

internal static partial class DesktopUiSmokeTest
{
    private sealed partial class Run
    {
        private async Task FeatureSettingsAsync(DesktopWindows manager)
        {
            var identity = session.IdentityKey; long generation = session.Generation;
            var party = manager.OpenPythonFeature("party"); await Settle(party);
            var enabled = Find<CheckBox>(party, "PartyGuardEnabled");
            for (int i = 0; i < 4; i++) Find<TextBox>(party, "PartyGuardMember" + i).Text = "";
            string original = session.Preferences.ReadBattle(identity).ToJson();
            enabled.IsChecked = true;
            Find<TextBox>(party, "PartyGuardMember0").Text = "42"; Find<TextBox>(party, "PartyGuardMember1").Text = "42";
            Click(party, "PartyGuardApply"); await Settle(party);
            Check(session.Preferences.ReadBattle(identity).ToJson() == original, "duplicate party guard IDs do not replace saved settings");
            Find<TextBox>(party, "PartyGuardMember1").Text = "43"; Click(party, "PartyGuardApply"); await Settle(party);
            Check(GameplayPreferences.Read(session).RequiredParty.SequenceEqual(new uint[] { 42, 43 }), "party editor applies validated IDs to core settings without starting AI");
            party.Hide();

            session.SaveCraftPlan(generation, identity, new() { Entries = [new(101, 2), new(102, 4)] });
            var plan = manager.OpenPythonFeature("crafting-plan"); await Settle(plan); Click(plan, "CraftPlanLoad");
            var table = Find<TextTable>(plan, "CraftPlan"); Check(table.RowCount == 2, "saved craft plan loads as ordered rows");
            table.SelectIndex(0); Click(plan, "CraftPlanDown");
            Find<NumericUpDown>(plan, "CraftPlanBatches").Value = 7; Click(plan, "CraftPlanUpdate"); Click(plan, "CraftPlanSave");
            var saved = session.Preferences.ReadCraftPlan(identity).Entries;
            Check(saved[0] == new CraftPlanEntry(102, 4) && saved[1] == new CraftPlanEntry(101, 7), "moving plan rows preserves selection and updates the intended batch count");
            Click(plan, "CraftPlanClear"); Check(table.RowCount == 0, "craft plan clear edits only the local draft");
            Click(plan, "CraftPlanLoad"); Check(table.RowCount == 2, "loading restores saved craft plan after draft edits");
            Check(!Find<Button>(plan, "CraftPlanStart").IsEnabled, "offline craft plan cannot consume materials"); plan.Hide();

            var benefits = manager.OpenPythonFeature("benefits");
            Descendants<TabControl>(benefits).First().SelectedIndex = 3; await Settle(benefits);
            foreach (string id in new[] { "cube", "rewards", "donate", "dispatch", "questions", "fights" }) Find<CheckBox>(benefits, "Assistant_" + id).IsChecked = false;
            Find<CheckBox>(benefits, "Assistant_sign").IsChecked = true;
            Find<NumericUpDown>(benefits, "AssistantGoldBudget").Value = 123;
            Click(benefits, "AssistantSave");
            Check(session.Preferences.ReadAssistant(identity).GuildSign && session.Preferences.ReadAssistant(identity).GoldBudget == 123, "assistant saves switches and spending budget");
            Check(session.Automations.Count == 0 && !Find<Button>(benefits, "AssistantStart").IsEnabled, "saving assistant settings while offline never starts automation");

            var calls = new List<(string Kind, bool Enabled, GameAutomationSettings? Settings)>(); int writes = 0;
            session.AttachGameSender(generation, _ => { writes++; return Task.CompletedTask; });
            session.AttachAutomationSender(generation, (kind, on, settings) =>
            {
                calls.Add((kind, on, settings));
                session.SetGameplayState(generation, true, null, [], session.Automations.SetItem(kind, new(kind, on, "介面測試")), new(false, "介面測試"));
                return Task.CompletedTask;
            });
            session.SetConnected(generation, true);
            session.SetGameplayState(generation, true, null, [], ImmutableDictionary<string, GameAutomationStatus>.Empty, new(false, "介面測試"));
            await Settle(benefits); Click(benefits, "AssistantStart"); await Settle(benefits);
            Check(calls.Count == 3 && calls.Single(c => c.Kind == "guild").Enabled && calls.Where(c => c.Kind != "guild").All(c => !c.Enabled), "assistant enables only the checked feature families through the core entry");
            Check(calls.Single(c => c.Kind == "guild").Settings is { DailyCube: false, DailyRewards: false, GuildSign: true, GoldBudget: 123 }, "guild assistant receives exact saved constraints and excludes daily rewards");
            Click(benefits, "AssistantStop"); await Settle(benefits);
            Check(session.Automations.Values.All(a => !a.Enabled), "assistant stop cancels its three owned feature families"); benefits.Hide();

            plan = manager.OpenPythonFeature("crafting-plan"); await Settle(plan); Click(plan, "CraftPlanStart"); await Settle(plan);
            var start = calls.Last(c => c.Kind == "craft");
            Check(start.Enabled && start.Settings?.CraftPlan.SequenceEqual(new GameCraftPlanEntry[] { new(102, 4), new(101, 7) }) == true && start.Settings.RestartCraftPlan == false,
                "craft plan start passes exact recipe order and batches to the account core");
            Check(!Find<Button>(plan, "CraftPlanClear").IsEnabled, "running plan cannot be edited underneath the active core copy");
            Click(plan, "CraftPlanStop"); await Settle(plan); Click(plan, "CraftPlanRestart"); await Settle(plan);
            Check(calls.Last(c => c.Kind == "craft").Settings?.RestartCraftPlan == true, "explicit craft restart is distinct from resume");
            Click(plan, "CraftPlanStop"); await Settle(plan);
            Check(writes == 0, "UI behavior tests use captured callbacks without sending game packets");
            await Capture(plan, "33-craft-plan-connected-fixture"); plan.Hide();
            session.Reset(identity); Publish(fixture.State, fixture.Labels);
            await EfficiencyAndNpcAsync(manager);
            Progress("必要隊員、每日助手與製作清單的保存、執行入口及帳號隔離");
        }

        private async Task EfficiencyAndNpcAsync(DesktopWindows manager)
        {
            uint role = fixture.State.Player?.RoleId ?? 17; long total = 0;
            EfficiencyKnowledgeSnapshot Knowledge() => new(role, new(total, 1, 0), playerName: "介面測試角色");
            var samples = EfficiencySnapshot.Empty;
            for (int i = 0; i < 2; i++)
            {
                samples = EfficiencyReducer.Apply(samples, Knowledge(), new EfficiencyBattleStart([new(role)]) { ObservedAt = i * 20 });
                total = 10 + i * 2;
                samples = EfficiencyReducer.Apply(samples, Knowledge(), new EfficiencyAttributeSet(EfficiencySubject.Player, 36, total) { ObservedAt = i * 20 + 5 });
                samples = EfficiencyReducer.Apply(samples, Knowledge(), new EfficiencyEventEnd { ObservedAt = i * 20 + 10 });
            }
            var state = new ServiceStateSnapshot(local: fixture.State.Local, companions: fixture.State.Companions, playerKnowledge: fixture.State.PlayerKnowledge, efficiency: samples);
            Publish(state, fixture.Labels);
            var efficiency = manager.OpenPythonFeature("efficiency"); await Settle(efficiency);
            Check(Find<ComboBox>(efficiency, "EfficiencySubject").ItemCount == 1 && Find<TextTable>(efficiency, "Efficiency").RowCount == 3, "efficiency exposes only confirmed subjects and all/10/30 sample windows");
            Check(Descendants<TextBlock>(efficiency).Any(t => t.Text == "6.0／分"), "efficiency displays rate calculated by the core reducer");
            Find<ComboBox>(efficiency, "EfficiencyUnit").SelectedIndex = 1; await Settle(efficiency);
            Check(Descendants<TextBlock>(efficiency).Any(t => t.Text == "360.0／時"), "efficiency unit changes scale without changing sample evidence");
            Check(!Find<Button>(efficiency, "EfficiencyReset").IsEnabled, "offline statistics reset cannot target an unbound core");
            long generation = session.Generation; int resets = 0;
            session.AttachEfficiencyResetter(generation, () =>
            {
                resets++;
                Publish(new(local: fixture.State.Local, efficiency: EfficiencyReducer.Apply(EfficiencySnapshot.Empty, Knowledge(), new EfficiencyRefresh { ObservedAt = 40 })), fixture.Labels);
                return Task.CompletedTask;
            });
            session.SetConnected(generation, true); await Settle(efficiency); Click(efficiency, "EfficiencyReset"); await Settle(efficiency);
            Check(resets == 1 && session.Snapshot.Efficiency.Rows.Values.All(r => r.Count == 0), "reset uses the account-owned reset callback and clears samples");
            Check(Descendants<TextBlock>(efficiency).Any(t => t.Text == "等待效率樣本"), "reset shows unknown rate rather than a fabricated zero");
            await Capture(efficiency, "34-efficiency-reset-fixture"); efficiency.Hide();

            var mapTabs = Find<TabControl>(dashboard, "MapLists"); int previous = mapTabs.SelectedIndex; mapTabs.SelectedIndex = 1; await Settle(dashboard);
            Click(dashboard, "MapNpcMore");
            var npc = dashboard.OwnedWindows.OfType<NpcInteractionWindow>().Single(); await Settle(npc);
            Check(!Find<Button>(npc, "NpcContinue").IsEnabled && !Find<Button>(npc, "NpcCloseMenu").IsEnabled, "NPC dialogue viewer cannot invent a choice or continue without a server prompt");
            await Capture(npc, "35-npc-dialogue-empty");
            session.Reset();
            Check(!session.CanResetEfficiency, "account replacement revokes statistics reset capability");
            Reject<InvalidOperationException>(() => session.ResetEfficiencyAsync(generation).GetAwaiter().GetResult(), "old statistics view cannot reset a replacement account");
            npc.Close(); mapTabs.SelectedIndex = previous;
            Publish(fixture.State, fixture.Labels);
        }
    }
}
