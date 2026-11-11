using System.Text.Json.Nodes;
using Avalonia.Controls;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private Control PartyGuardControls()
    {
        var note = Ui.Text("儲存後更新執行中的戰鬥 AI；未啟動時只保存設定。", 12, Ui.Muted);
        var enabled = Check("名單未到齊時，遇戰自動逃跑"); enabled.Name = "PartyGuardEnabled";
        var entries = Enumerable.Range(0, 4).Select(i => { var entry = Edit("角色 ID 或已同步名稱"); entry.Name = "PartyGuardMember" + i; return entry; }).ToArray();
        var panel = Ui.Column(enabled);
        try
        {
            var party = session.Preferences.ReadBattle(session.IdentityKey).Value["party_guard"]!;
            enabled.IsChecked = BattleSettingsDraft.Bool(party["enabled"]);
            int i = 0; foreach (var member in (JsonArray)party["members"]!) entries[i++].Text = BattleSettingsDraft.Number(member!["role_id"]).ToString();
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error)) { note.Text = "必要隊員設定無法讀取，尚未覆寫。"; }
        foreach (var entry in entries) panel.Children.Add(entry);
        panel.Children.Add(Ui.Button("帶入目前隊伍", () =>
        {
            var state = session.Snapshot;
            var members = state.Party.OwnTeam(state.Player?.RoleId)?.Members.Where(id => id != state.Player?.RoleId).Take(4).ToArray() ?? [];
            for (int i = 0; i < entries.Length; i++) entries[i].Text = i < members.Length ? members[i].ToString() : "";
        }, "PartyGuardUseTeam"));
        panel.Children.Add(Ui.Button("儲存並套用", async () =>
        {
            var expectedGeneration = generation; string identity = session.IdentityKey;
            try
            {
                session.RequireCurrentDraft(expectedGeneration);
                var state = session.Snapshot; var members = new JsonArray();
                foreach (var entry in entries)
                {
                    string text = entry.Text?.Trim() ?? ""; if (text.Length == 0) continue;
                    if (!uint.TryParse(text, out uint id))
                    {
                        var found = state.Party.Nearby.Values.Where(p => p.Name == text).Select(p => p.RoleId).Distinct().ToArray();
                        if (found.Length != 1) throw new InvalidOperationException("名稱必須唯一且已同步；也可直接填入角色 ID。");
                        id = found[0];
                    }
                    if (id == 0 || id == state.Player?.RoleId) throw new InvalidOperationException("必要隊員請填其他玩家的有效角色 ID。");
                    members.Add(new JsonObject { ["role_id"] = id, ["name"] = state.Party.PlayerName(id) });
                }
                var draft = session.Preferences.ReadBattle(identity);
                draft.Value["party_guard"] = new JsonObject { ["enabled"] = enabled.IsChecked == true, ["members"] = members };
                session.SaveBattle(expectedGeneration, identity, draft);
                await session.ReapplyActiveSettingsAsync(expectedGeneration, identity, "battle");
                if (!closed && generation == expectedGeneration) note.Text = "必要隊員名單已儲存，執行中的戰鬥 AI 已更新；沒有啟動新的 AI。";
            }
            catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException)
            { if (!closed) note.Text = error.Message; }
        }, "PartyGuardApply"));
        panel.Children.Add(Ui.Button("清空草稿", () => { foreach (var entry in entries) entry.Text = ""; enabled.IsChecked = false; }));
        panel.Children.Add(note);
        return panel;
    }

    private TextBlock? assistantNote;
    private readonly Dictionary<string, CheckBox> assistantChecks = [];
    private Button? assistantStart, assistantStop;
    private bool assistantBusy;
    private Control AssistantControls()
    {
        assistantChecks.Clear(); assistantBusy = false;
        AssistantPreferences value;
        try { value = session.Preferences.ReadAssistant(session.IdentityKey); }
        catch (Exception error) when (SettingsFiles.IsExpected(error)) { value = new(); actionNote.Text = "助手設定無法讀取，尚未覆寫。"; }
        var toggles = new WrapPanel();
        foreach (var (id, name, selected) in new[] { ("cube", "魔方開啟", value.Cube), ("rewards", "任務／寶箱領獎", value.Rewards),
            ("sign", "組織簽到", value.GuildSign), ("donate", "組織捐獻", value.GuildDonate), ("dispatch", "方舟派遣", value.ArkDispatch),
            ("questions", "方舟問答", value.ArkQuestions), ("fights", "方舟戰鬥（需戰鬥 AI）", value.ArkFights) })
        {
            var check = Check(name); check.Name = "Assistant_" + id; check.IsChecked = selected; assistantChecks[id] = check; toggles.Children.Add(check);
        }
        var gold = Ui.Number(value.GoldBudget, 0, int.MaxValue); gold.Name = "AssistantGoldBudget";
        var target = Ui.Number(value.DonationTarget, 1, 5); var stars = Ui.Number(value.StarBudget, 0, int.MaxValue); var hours = Ui.Number(value.ArkHours, 1, 6);
        var plan = Ui.Combo(["初級捐獻", "中級捐獻", "高級捐獻"], value.DonationPlan - 8);
        AssistantPreferences Draft() => new(assistantChecks["cube"].IsChecked == true, assistantChecks["rewards"].IsChecked == true,
            assistantChecks["sign"].IsChecked == true, assistantChecks["donate"].IsChecked == true, assistantChecks["dispatch"].IsChecked == true,
            assistantChecks["questions"].IsChecked == true, assistantChecks["fights"].IsChecked == true,
            plan.SelectedIndex + 8, checked((int)(target.Value ?? 0)), checked((int)(gold.Value ?? -1)), checked((int)(hours.Value ?? 0)), checked((int)(stars.Value ?? -1)));
        assistantNote = Ui.Text("勾選是設定草稿，儲存不會自動啟動。", 12, Ui.Muted);
        void Save()
        {
            var draft = Draft(); draft.Validate(); session.SaveAssistant(generation, session.IdentityKey, draft);
            assistantNote.Text = "助手設定已儲存，尚未啟動。";
        }
        assistantStart = Ui.Button("儲存並啟動助手", async () =>
        {
            if (assistantBusy) return; long expectedGeneration = generation;
            try
            {
                assistantBusy = true; RefreshAssistantControls(); Save(); var settings = GameplayPreferences.Read(session);
                session.RequireCurrentDraft(expectedGeneration);
                await session.SetAutomationAsync("daily", settings.DailyCube || settings.DailyRewards, settings with { GuildSign = false, GuildDonate = false });
                session.RequireCurrentDraft(expectedGeneration);
                await session.SetAutomationAsync("guild", settings.GuildSign || settings.GuildDonate, settings with { DailyCube = false, DailyRewards = false });
                session.RequireCurrentDraft(expectedGeneration);
                await session.SetAutomationAsync("ark", settings.ArkDispatch || settings.ArkQuestions || settings.ArkFights, settings);
                if (!closed && generation == expectedGeneration) assistantNote.Text = "已套用已勾選的助手功能；實際操作由核心核對並等待伺服器確認。";
            }
            catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException or OverflowException)
            { if (!closed) assistantNote.Text = error.Message; }
            finally { assistantBusy = false; if (!closed) RefreshAssistantControls(); }
        }, "AssistantStart");
        assistantStop = Ui.Button("暫停助手接續", async () =>
        {
            if (assistantBusy) return; long expectedGeneration = generation;
            try
            {
                assistantBusy = true; RefreshAssistantControls();
                foreach (string kind in new[] { "daily", "guild", "ark" }) { session.RequireCurrentDraft(expectedGeneration); await session.SetAutomationAsync(kind, false); }
                if (!closed) assistantNote.Text = "已暫停助手接續；已送出的操作仍以伺服器結果為準。";
            }
            catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException) { if (!closed) assistantNote.Text = error.Message; }
            finally { assistantBusy = false; if (!closed) RefreshAssistantControls(); }
        }, "AssistantStop");
        var save = Ui.Button("儲存設定", () => { try { Save(); } catch (Exception error) when (SettingsFiles.IsExpected(error) || error is OverflowException) { assistantNote.Text = error.Message; } }, "AssistantSave");
        return Page("每日助手", toggles, Columns("*,*", Ui.Column(Field("金幣上限（本輪）", gold), Field("每日捐獻總目標", target)),
            Ui.Column(Field("星力上限（本次登入）", stars), Field("派遣小時", hours))), Field("捐獻方案", plan),
            Ui.Row(save, assistantStart, assistantStop), assistantNote, Table("AssistantTasks", ["功能", "狀態", "來源", "說明"], 160));
    }
    private void RefreshAssistantControls()
    {
        if (assistantStart is null) return;
        assistantStart.IsEnabled = !assistantBusy && session.CanSendGameCommands;
        assistantStop!.IsEnabled = !assistantBusy && session.IsConnected;
        if (tables.TryGetValue("AssistantTasks", out var table)) table.SetRows(new[] { ("daily", "魔方／任務"), ("guild", "組織"), ("ark", "方舟") }.Select(row =>
        {
            var status = session.Automations.GetValueOrDefault(row.Item1);
            return (row.Item1, new[] { row.Item2, status?.Enabled == true ? "執行中" : "未啟動", "公用核心", status?.Message ?? "等待手動啟動" });
        }));
    }
}
