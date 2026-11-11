using System.Collections.Immutable;
using Avalonia.Controls;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private NumericUpDown? donationTarget, goldBudget, arkHours, starBudget;
    private ComboBox? donationPlan;
    private CheckBox? guildSignAuto, guildDonateAuto, arkDispatchAuto, arkQuestionsAuto;
    private TextBlock? arkQuestion;
    private Control GuildControls()
    {
        guildStatus = Ui.Text("等待組織資料同步。");
        guildSignAuto = Check("自動簽到"); guildDonateAuto = Check("自動捐獻");
        donationPlan = Ui.Combo(["初級捐獻", "中級捐獻", "高級捐獻"], 0);
        donationTarget = Ui.Number(3, 1, 5); goldBudget = Ui.Number(450, 0, int.MaxValue);
        GameAction Donation() => new("guild", "donate", Index: donationPlan.SelectedIndex + 8, Count: (int)(donationTarget.Value ?? 3), Values: ImmutableDictionary<string, int>.Empty.Add("budget", (int)(goldBudget.Value ?? 0)));
        return Page("組織", guildStatus, Ui.Row(guildSignAuto, guildDonateAuto),
            Ui.Row(Ui.Text("捐獻方案"), donationPlan, Ui.Text("每日總目標"), donationTarget), Ui.Row(Ui.Text("本輪金幣上限"), goldBudget),
            Ui.Row(Ui.Button("套用設定", async () => await SocialAutomationAsync("guild", true)), Ui.Button("暫停組織自動操作", async () => await SocialAutomationAsync("guild", false)),
                GameButton("立即簽到", () => new("guild", "sign")), GameButton("捐獻一次", Donation)),
            Ui.Text("送出前會核對同版價格、可靠金幣、消費次數與剩餘資格。", color: Ui.Muted));
    }
    private Control ArkControls()
    {
        arkStatus = Ui.Text("等待方舟資料同步。"); arkQuestion = Ui.Text("等待伺服器題目。");
        arkDispatchAuto = Check("派遣情報員"); arkQuestionsAuto = Check("問答自動接續");
        arkHours = Ui.Number(1, 1, 6); starBudget = Ui.Number(120, 0, int.MaxValue);
        var events = Table("ArkEvents", ["事件", "星球", "類型", "狀態"], 160);
        GameAction SelectedEvent()
        {
            var row = session.Snapshot.Ark.Events.GetValueOrDefault(checked((byte)Selected("ArkEvents"))) ?? throw new InvalidOperationException("事件清單已改變。");
            return new("ark", row.Kind == 3 ? "question" : "fight", row.Id, row.Index);
        }
        GameAction Dispatch()
        {
            var agent = session.Snapshot.Ark.Agents.Values.Where(a => a.Planet == 0).OrderBy(a => a.Index).FirstOrDefault() ?? throw new InvalidOperationException("沒有空閒情報員。");
            return new("ark", "dispatch", Index: agent.Index, Count: (int)(arkHours.Value ?? 1), Values: ImmutableDictionary<string, int>.Empty.Add("budget", (int)(starBudget.Value ?? 0)));
        }
        return Page("星之方舟", arkStatus, Ui.Row(arkDispatchAuto, arkQuestionsAuto), Ui.Row(Ui.Text("採集小時"), arkHours, Ui.Text("登入星力上限"), starBudget),
            Ui.Row(Ui.Button("套用設定", async () => await SocialAutomationAsync("ark", true)), Ui.Button("暫停", async () => await SocialAutomationAsync("ark", false)),
                GameButton("派遣一次", Dispatch), GameButton("執行選取事件", SelectedEvent)), events, arkQuestion,
            Ui.Row(Enumerable.Range(1, 4).Select(index => (Control)GameButton($"回答選項 {index}", () => new("ark", "answer", Index: index))).ToArray()));
    }
    private async Task SocialAutomationAsync(string kind, bool enabled)
    {
        try
        {
            await session.SetAutomationAsync(kind, enabled, GameplayPreferences.Read(session) with
            {
                DailyCube = false, DailyRewards = false, GuildSign = guildSignAuto?.IsChecked == true, GuildDonate = guildDonateAuto?.IsChecked == true,
                DonationSellId = (donationPlan?.SelectedIndex ?? 0) + 8, DonationTarget = (int)(donationTarget?.Value ?? 3), GoldBudget = (int)(goldBudget?.Value ?? 0),
                ArkDispatch = arkDispatchAuto?.IsChecked == true, ArkQuestions = arkQuestionsAuto?.IsChecked == true, ArkHours = (int)(arkHours?.Value ?? 1), StarBudget = (int)(starBudget?.Value ?? 0)
            });
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException) { actionNote.Text = error.Message; }
    }
    private void RefreshSocialControls()
    {
        var s = session.Snapshot;
        if (tables.TryGetValue("ArkEvents", out var events)) events.SetRows(s.Ark.Events.Values.OrderBy(e => e.Index).Select(e =>
            (e.Index.ToString(), new[] { e.Id.ToString(), e.Planet.ToString(), e.Kind == 3 ? "問答" : e.Kind == 1 ? "戰鬥" : e.Kind.ToString(), e.Id == 0 ? "已完成" : "可選取" })));
        if (arkQuestion is not null) arkQuestion.Text = s.Ark.Question is {} q ? q.Text + "\n" + string.Join("\n", q.Labels.Select((label, i) => $"{i + 1}. {label}")) : "等待伺服器題目。";
        if (guildStatus is not null) guildStatus.Text = $"組織：{s.Guild.Name ?? "尚未同步"}｜簽到：{s.GuildActions.SignState switch { 1 => "可簽到", 2 => "已簽到", 3 => "新加入，今日不可簽到", _ => "等待同步" }}｜剩餘捐獻：{s.GuildActions.Remaining?.ToString() ?? "待同步"}\n{session.Automations.GetValueOrDefault("guild")?.Message ?? s.GuildActions.Status}";
    }
}
