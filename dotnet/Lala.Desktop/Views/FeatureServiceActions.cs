using Avalonia.Controls;
using Lala.Core.Automation;
using Lala.Core.Gameplay;
using Lala.Core.State;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private readonly Dictionary<bool, TextBox> roomPasswords = [];
    private readonly Dictionary<bool, NumericUpDown> roomMembers = [];
    private readonly Dictionary<string, CheckBox> dailyToggles = [];
    private Control InstanceControls(bool coop)
    {
        roomPasswords[coop] = new() { PasswordChar = '*', Width = 110, MaxLength = coop ? 9 : 5, PlaceholderText = "留白為公開" };
        roomMembers[coop] = Ui.Number(4, 1, 8, width: 65);
        return Ui.Column(Ui.Row(Ui.Text("房間密碼"), roomPasswords[coop], Ui.Text("人數"), roomMembers[coop]),
            InstanceActions(coop, "更新房間清單", "建立公開／私人房間", "加入選取房間", "離開房間", coop ? "準備／開始配對" : "開始挑戰"));
    }
    private Control InstanceActions(bool coop, params string[] labels)
    {
        var panel = new WrapPanel();
        foreach (var label in labels) panel.Children.Add(GameButton(label, () =>
        {
            string mode = coop ? "coop" : "main";
            string op = label switch { "更新房間清單" => "refresh", "建立公開／私人房間" => "create", "加入選取房間" => "join", "離開房間" => "leave", "準備／開始配對" => "standby", "開始挑戰" => "start", _ => "enter" };
            uint target = op == "create" ? checked((uint)Selected(coop ? "CoopCatalog" : "InstanceCatalog")) : op == "join" ? checked((uint)Selected(coop ? "CoopRooms" : "InstanceRooms")) : 0;
            int password = 0;
            if (!string.IsNullOrWhiteSpace(roomPasswords.GetValueOrDefault(coop)?.Text) && !int.TryParse(roomPasswords[coop].Text, out password)) throw new InvalidOperationException("房間密碼請填入有效數字。");
            var values = System.Collections.Immutable.ImmutableDictionary<string, int>.Empty.Add("password", password);
            return new("instance", op, target, Count: (int)(roomMembers.GetValueOrDefault(coop)?.Value ?? 4), Values: values, Key: mode);
        }));
        return panel;
    }
    private Control InstanceRewardControls() => Ui.Row(GameButton("領取免費協力獎勵", () => new("instance", "claim", Key: "coop")),
        GameButton("放棄目前寶箱", () => new("instance", "cancel", Key: "coop")));
    private CheckBox DailyToggle(string label, string kind)
    {
        var check = Check(label); dailyToggles[kind] = check;
        check.IsCheckedChanged += async (_, _) =>
        {
            try
            {
                var settings = GameplayPreferences.Read(session) with
                {
                    DailyCube = dailyToggles.GetValueOrDefault("cube")?.IsChecked == true,
                    DailyRewards = dailyToggles.GetValueOrDefault("daily")?.IsChecked == true || dailyToggles.GetValueOrDefault("weekly")?.IsChecked == true,
                    GuildSign = false, GuildDonate = false
                };
                await session.SetAutomationAsync("daily", settings.DailyCube || settings.DailyRewards, settings);
            }
            catch (Exception error) when (error is IOException or InvalidOperationException or Lala.Core.Protocol.ProtocolException) { actionNote.Text = error.Message; }
        };
        return check;
    }
    private void RefreshServiceTables()
    {
        var s = session.Snapshot; var catalog = session.Catalogs;
        foreach (var check in dailyToggles.Values) check.IsEnabled = session.CanSendGameCommands || session.Automations.GetValueOrDefault("daily")?.Enabled == true;
        foreach (bool coop in new[] { false, true })
        {
            if (tables.TryGetValue(coop ? "CoopCatalog" : "InstanceCatalog", out var definitions)) definitions.SetRows(
                catalog?.OptionalInstances?.Entries.Where(e => (e.Data.Kind != 1) == coop).Select(e => (e.Data.Id.ToString(), new[]
                { e.Data.Id.ToString(), e.Name, e.MinLevel.ToString(), $"{e.MinMembers}～{e.MaxMembers}", e.TimeMinutes + " 分" })) ?? []);
            var state = coop ? s.Instances.Coop : s.Instances.Main;
            if (tables.TryGetValue(coop ? "CoopRooms" : "InstanceRooms", out var rooms)) rooms.SetRows(state["rooms"].SequenceValue.Select(row =>
                (ManualNumber(row, "room_id").ToString(), new[] { ManualNumber(row, "room_id").ToString(), ManualNumber(row, "members").ToString(),
                    row.MapValue.TryGetValue("public", out var privacy) && privacy.ScalarValue is true ? "公開" : "私人" })));
        }
        if (catalog?.OptionalDailyCatalog is {} daily)
        {
            var rows = DailyTaskService.TaskRows(s.DailyTasks, daily.ToPlanningDefinitions());
            foreach (byte cycle in new byte[] { 1, 2 }) if (tables.TryGetValue(cycle == 1 ? "DailyTasks" : "WeeklyTasks", out var table)) table.SetRows(rows.Where(r => r.Definition.Cycle == cycle)
                .Select(r => (r.Definition.Index.ToString(), new[] { daily.Tasks.First(t => t.Data.Index == r.Definition.Index).Name,
                    r.Progress?.ToString() ?? "待同步", r.Definition.Goal?.ToString() ?? "未知", r.Received ? "已領取" : r.Eligible ? "可領取" : "未達標" })));
        }
    }
    private static long ManualNumber(StateValue map, string key) => map.MapValue.TryGetValue(key, out var v) && v.Kind == StateValueKind.Scalar && long.TryParse(v.ScalarValue?.ToString(), out var n) ? n : 0;
}
