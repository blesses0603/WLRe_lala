using System.Globalization;
using System.Text;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Lala.Core.Expedition;

namespace Lala.Desktop;

/// <summary>Server-observation lists and an account-bound local draft; no expedition commands.</summary>
public sealed class ExpeditionWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly long draftGeneration;
    private readonly string draftIdentity;
    private readonly NumericUpDown hours = Ui.Number(0, 0, 24, .5m, 120);
    private readonly NumericUpDown faith = Ui.Number(80, 1, 100, width: 120);
    private readonly NumericUpDown success = Ui.Number(75, 0, 100, 5, 120);
    private readonly CheckBox autoClaim = new() { Content = "自動領獎", IsChecked = true, Name = "ExpeditionAutoClaim" };
    private readonly ComboBox restore = Ui.Combo(["自動從背包選擇"], name: "ExpeditionRestoreItem");
    private readonly TextTable tasks = new(["任務名稱", "所需時間", "預估成功率"], "*,90,100", "ExpeditionTasks");
    private readonly TextTable roles = new(["夥伴", "好友度", "狀態"], "*,65,65", "ExpeditionRoles");
    private readonly TextBox detail = new()
    {
        Name = "ExpeditionTaskDetail", IsReadOnly = true, AcceptsReturn = true,
        TextWrapping = TextWrapping.Wrap, Background = Ui.Panel, BorderThickness = new Thickness(0)
    };
    private readonly TextBlock status = Ui.Text("等待遠征與駐紮所資料同步。", 13, Ui.Muted);
    private readonly TextBlock teams = Ui.Text("等待遠征隊伍資料同步。", 12);
    private readonly TextBlock note = Ui.Text("設定只儲存至此桌面預覽，不會啟動派遣或領獎。", 12, Ui.Muted);
    private readonly Button save;
    private readonly Button start, stop;
    private ushort? restoreItem;
    private ushort? savedRestoreChoice;
    private bool closed;

    public ExpeditionWindow(DesktopSession session) : base("飄流Re:LaLa · 遠征", 1080, 650)
    {
        this.session = session;
        var view = session.ReadView();
        draftGeneration = view.Generation;
        draftIdentity = view.IdentityKey;
        Name = "ExpeditionWindow";
        hours.Name = "ExpeditionMinHours";
        faith.Name = "ExpeditionMinFaith";
        success.Name = "ExpeditionMinSuccess";
        status.Name = "ExpeditionStatus";
        note.Name = "ExpeditionPreferenceStatus";
        teams.Name = "ExpeditionTeams";
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,*,Auto,Auto") };
        Ui.At(body, Ui.Text("遠征", 18, bold: true), 0);
        status.Margin = new Thickness(0, 4);
        Ui.At(body, status, 0, 1);
        var controls = Ui.Row(Ui.Text("任務時間大於"), hours, Ui.Text("小時　好友度低於"), faith,
            Ui.Text("時補充"), Ui.Text("最低成功率"), success, Ui.Text("%"), autoClaim);
        controls.Margin = new Thickness(0, 3);
        Ui.At(body, controls, 0, 2);
        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto,Auto"), Margin = new Thickness(0, 3, 0, 8) };
        Ui.At(actions, Ui.Text("恢復物品"), 0);
        restore.Margin = new Thickness(6, 0);
        Ui.At(actions, restore, 1);
        start = Ui.Button("啟動自動派遣", () => _ = SetAutomaticAsync(true), "ExpeditionStart");
        start.Content = Ui.Row(Ui.Icon("automation-controls/Auto_Play.png", 18), Ui.Text("啟動自動派遣", 13));
        Ui.At(actions, start, 2);
        stop = Ui.Button("停止", () => _ = SetAutomaticAsync(false), "ExpeditionStop");
        stop.Content = Ui.Row(Ui.Icon("automation-controls/Auto_Pause.png", 18), Ui.Text("停止", 13));
        stop.Margin = new Thickness(4, 0);
        Ui.At(actions, stop, 3);
        save = Ui.Button("儲存", SaveDraft, "ExpeditionSave");
        Ui.At(actions, save, 4);
        Ui.At(body, actions, 0, 3);

        var lists = new Grid { ColumnDefinitions = new ColumnDefinitions("4*,3*,3*"), RowDefinitions = new RowDefinitions("Auto,*") };
        Ui.At(lists, Ui.Text("可用任務", 14, bold: true), 0);
        Ui.At(lists, Ui.Text("駐紮所夥伴", 14, bold: true), 1);
        Ui.At(lists, Ui.Text("任務詳情", 14, bold: true), 2);
        tasks.Margin = new Thickness(0, 5, 8, 0);
        roles.Margin = new Thickness(0, 5, 8, 0);
        detail.Margin = new Thickness(0, 5, 0, 0);
        Ui.At(lists, tasks, 0, 1);
        Ui.At(lists, roles, 1, 1);
        Ui.At(lists, detail, 2, 1);
        Ui.At(body, lists, 0, 4);
        teams.Margin = new Thickness(0, 6);
        Ui.At(body, teams, 0, 5);
        Ui.At(body, note, 0, 6);
        SetBody(body);

        LoadDraft();
        tasks.SelectionChanged += ShowTask;
        restore.SelectionChanged += (_, _) => restoreItem = restore.SelectedIndex == 1 ? savedRestoreChoice : null;
        session.Changed += Changed;
        Closed += (_, _) => { closed = true; session.Changed -= Changed; };
        Refresh();
    }

    private void LoadDraft()
    {
        try
        {
            var value = session.Preferences.ReadExpedition(draftIdentity);
            session.RequireCurrentDraft(draftGeneration);
            hours.Value = value.MinHours;
            faith.Value = value.MinFaith;
            success.Value = value.MinSuccess;
            autoClaim.IsChecked = value.AutoClaim;
            restoreItem = value.RestoreItemId;
            savedRestoreChoice = restoreItem;
            if (restoreItem is { } id)
            {
                restore.ItemsSource = new[] { "自動從背包選擇", session.ReadView().Labels.Item(id) + "（恢復效果待同步）" };
                restore.SelectedIndex = 1;
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or ArgumentException or InvalidOperationException)
        {
            save.IsEnabled = false;
            note.Text = "遠征設定無法讀取，未覆寫原檔。請修復設定後重新開啟視窗。";
        }
    }

    private void SaveDraft()
    {
        try
        {
            if (hours.Value is not { } minHours || faith.Value is not { } minFaith || success.Value is not { } minSuccess)
                throw new ArgumentException("請完整填寫任務時間、好友度與最低成功率。");
            if (decimal.Truncate(minFaith) != minFaith || decimal.Truncate(minSuccess) != minSuccess)
                throw new ArgumentException("好友度與最低成功率請輸入整數。");
            var value = new ExpeditionPreferences(minHours, checked((int)minFaith), checked((int)minSuccess),
                autoClaim.IsChecked == true, restoreItem);
            value.Validate();
            session.SaveExpedition(draftGeneration, draftIdentity, value);
            note.Text = "已儲存此桌面預覽的遠征設定；未啟動派遣，也不會自動領獎。";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or ArgumentException or InvalidOperationException or OverflowException)
        {
            note.Text = error is ArgumentException or InvalidOperationException or InvalidDataException ? error.Message
                : "遠征設定儲存失敗，請檢查設定目錄是否可寫入。";
        }
    }

    private void Changed() => Ui.OnUi(() => { if (!closed) Refresh(); });
    private async Task SetAutomaticAsync(bool enabled)
    {
        try
        {
            session.RequireCurrentDraft(draftGeneration);
            var settings = GameplayPreferences.Read(session);
            if (enabled)
            {
                if (hours.Value is not {} minHours || faith.Value is not {} minFaith || success.Value is not {} minSuccess ||
                    decimal.Truncate(minFaith) != minFaith || decimal.Truncate(minSuccess) != minSuccess) throw new InvalidOperationException("請完整填寫有效的遠征條件。");
                var draft = new ExpeditionPreferences(minHours, checked((int)minFaith), checked((int)minSuccess), autoClaim.IsChecked == true, restoreItem);
                draft.Validate(); session.SaveExpedition(draftGeneration, draftIdentity, draft);
                settings = settings with { ExpeditionMinHours = draft.MinHours, ExpeditionMinFaith = draft.MinFaith,
                    ExpeditionMinSuccess = draft.MinSuccess, ExpeditionAutoClaim = draft.AutoClaim, RestoreItem = draft.RestoreItemId };
            }
            await session.SetAutomationAsync("expedition", enabled, settings);
            if (!closed) note.Text = enabled ? "自動派遣已啟動；符合條件後才會送出，結果由伺服器確認。" : "已停止後續派遣。";
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or ArgumentException or Lala.Core.Protocol.ProtocolException)
        { if (!closed) note.Text = error.Message; }
    }

    private void Refresh()
    {
        var view = session.ReadView();
        var expedition = view.Snapshot.Expedition;
        bool currentDraft = view.Generation == draftGeneration && view.IdentityKey == draftIdentity;
        if (!currentDraft)
        {
            save.IsEnabled = false;
            note.Text = "帳號或連線已變更；此草稿不會套用，請重新開啟遠征視窗。";
        }
        bool automatic = session.Automations.GetValueOrDefault("expedition")?.Enabled == true;
        start.IsEnabled = currentDraft && session.CanSendGameCommands && !automatic;
        stop.IsEnabled = automatic;
        bool editable = currentDraft && !automatic && expedition.Pending is null;
        hours.IsEnabled = faith.IsEnabled = success.IsEnabled = autoClaim.IsEnabled = restore.IsEnabled = editable;
        status.Text = !expedition.Ready || !expedition.OutpostReady
            ? "等待遠征與駐紮所資料同步。"
            : session.Automations.GetValueOrDefault("expedition")?.Message ?? (session.IsConnected ? "已連線｜遠征與駐紮所資料已同步。" : "尚未連線，顯示最後同步資料。");
        if (expedition.Uncertain) status.Text += " 上次操作結果未確認。";
        var ids = expedition.Quests.Values.Where(id => id != 0).Distinct().Order().ToArray();
        tasks.SetRows(ids.Select(id => (id.ToString(CultureInfo.InvariantCulture),
            new[] { view.Labels.ExpeditionTask(id), "待同步", "待同步" })),
            expedition.Ready ? "目前沒有伺服器回報的可用任務。" : "等待伺服器任務同步。");
        roles.SetRows(expedition.Roles.OrderBy(pair => pair.Key).Select(pair =>
            (pair.Key.ToString(CultureInfo.InvariantCulture), new[]
            {
                view.Labels.Npc(pair.Value.NpcId), pair.Value.Faith.ToString(CultureInfo.InvariantCulture),
                pair.Value.State == 0 ? "閒置" : "遠征中"
            })), expedition.OutpostReady ? "駐紮所目前沒有夥伴。" : "等待駐紮所夥伴同步。");
        var running = expedition.Teams.OrderBy(pair => pair.Key).Where(pair => pair.Value.Quest != 0)
            .Select(pair => $"隊伍 {pair.Key}：{view.Labels.ExpeditionTask(pair.Value.Quest)}（最近回報 {pair.Value.Minutes} 分鐘）")
            .ToArray();
        teams.Text = (running.Length != 0 ? string.Join("｜", running) : expedition.Ready
            ? "目前沒有進行中的遠征。" : "等待遠征隊伍資料同步。") +
            (expedition.Ready ? $"　已領獎 {expedition.Claimed} 次" : "");
        ShowTask(view);
    }

    private void ShowTask() => ShowTask(session.ReadView());

    private void ShowTask(DesktopPublication view)
    {
        if (!ushort.TryParse(tasks.SelectedKey, NumberStyles.None, CultureInfo.InvariantCulture, out var id))
        {
            detail.Text = "選取任務可查看完整獎勵與派遣條件。\n\n任務時間與成功率等待同版任務目錄同步。";
            return;
        }
        var expedition = view.Snapshot.Expedition;
        if (!expedition.Quests.Values.Contains(id)) { detail.Text = "此任務已不在目前任務清單，請重新選取。"; return; }
        var value = new StringBuilder();
        value.AppendLine(view.Labels.ExpeditionTask(id));
        value.AppendLine($"任務 ID：{id}");
        value.AppendLine("所需時間：待同步");
        value.AppendLine("消耗好友度：待同步");
        value.AppendLine("預估成功率：待同步");
        value.AppendLine();
        value.AppendLine("任務獎勵");
        value.AppendLine("等待同版任務目錄。");
        value.AppendLine();
        value.AppendLine("推薦條件");
        value.AppendLine("等待同版任務與 NPC 資料。");
        foreach (var team in expedition.Teams.OrderBy(pair => pair.Key).Where(pair => pair.Value.Quest == id))
        {
            value.AppendLine();
            value.AppendLine($"伺服器回報隊伍 {team.Key}");
            value.AppendLine("夥伴：" + string.Join("、", team.Value.Members.Where(npc => npc != 0).Select(view.Labels.Npc)));
            value.AppendLine($"最近回報時間：{team.Value.Minutes} 分鐘");
        }
        detail.Text = value.ToString().TrimEnd();
    }
}
