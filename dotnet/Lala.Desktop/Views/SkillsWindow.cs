using System.Collections.Immutable;
using System.Globalization;
using Avalonia.Controls;
using Lala.Core.State;

namespace Lala.Desktop;

/// <summary>Independent skill view; it owns its controls, search, and selection.</summary>
public sealed class SkillsWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly TextBox search = new() { Name = "SkillsSearch", Width = 260, MaxLength = 128 };
    private readonly TextBlock status = Ui.Text("等待角色與夥伴特技同步", 12, Ui.Muted);
    private readonly TextBlock detail = Ui.Text("請選取特技查看資料。", color: Ui.Muted);
    private readonly TextTable table = new(
        ["角色／夥伴", "ID", "特技", "等級", "分類", "消耗SP", "基礎條件／不可用原因", "資料來源"],
        "150,65,160,55,60,65,*,140", "SkillsTable");
    private SkillPresentationRow[] rows = [];
    private long generation;
    private bool closed;
    private bool refreshing;
    private readonly ComboBox target = Ui.Combo([], -1, "SkillsTarget");
    private readonly Button cast;

    public SkillsWindow(DesktopSession session) : base("角色／夥伴特技", 1040, 700)
    {
        ArgumentNullException.ThrowIfNull(session);
        this.session = session;
        generation = session.ReadView().Generation;
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,*,Auto,Auto"), RowSpacing = 8 };
        Ui.At(body, Ui.Column(Ui.Text("特技", 22, bold: true),
            Ui.Text("搜尋角色與夥伴已確認的特技；技能清單與背包分開顯示。", color: Ui.Muted)), 0);
        Ui.At(body, Ui.Row(Ui.Text("搜尋名稱／ID"), search,
            Ui.Button("更新顯示", Refresh, "SkillsRefresh")), 0, 1);
        Ui.At(body, status, 0, 2);
        Ui.At(body, table, 0, 3);
        detail.Name = "SkillsDetails";
        Ui.At(body, Ui.Card("特技資訊", detail), 0, 4);
        cast = Ui.Button("施放選取特技（戰鬥內）", () => _ = CastAsync(), "SkillsCast");
        target.MinWidth = 210;
        Ui.At(body, Ui.Column(Ui.Row(Ui.Text("戰場目標"), target, cast),
            Ui.Text("送出前會核對施放者、回合、已學會技能、SP 與目標；每單位每回合只下令一次。", 12, Ui.Muted)), 0, 5);
        SetBody(body);
        search.TextChanged += (_, _) => { if (!refreshing && !closed) Refresh(); };
        table.SelectionChanged += UpdateDetails;
        session.Changed += SessionChanged;
        Closed += (_, _) => { closed = true; session.Changed -= SessionChanged; };
        Refresh();
    }

    public string SearchText { get => search.Text ?? ""; set => search.Text = value; }
    public int SkillRowCount => table.RowCount;
    public string? SelectedSkillKey => table.SelectedKey;
    public string DetailsText => detail.Text ?? "";
    public void SelectSkillRow(int index) => table.SelectIndex(index);

    private void SessionChanged() => Ui.OnUi(() => { if (!closed) Refresh(); });

    private void Refresh()
    {
        if (refreshing || closed) return;
        refreshing = true;
        try
        {
            var view = session.ReadView();
            if (generation != view.Generation)
            {
                generation = view.Generation;
                search.Text = "";
                table.SetRows([]);
            }
            var snapshot = view.Snapshot;
            var previousTarget = target.SelectedItem as string;
            target.ItemsSource = snapshot.Local.Battle.Units.Where(u => !u.Exited).Select(u => $"{u.Slot}｜{u.Layout.Name} HP {u.Hp}").ToArray();
            if (previousTarget is not null) target.SelectedItem = previousTarget;
            cast.IsEnabled = session.CanSendGameCommands && snapshot.Local.Battle.Active == true && session.ActionStatus?.Pending != true;
            var query = (search.Text ?? "").Trim();
            rows = SkillPresentation.All(snapshot, view.Labels).Where(row => query.Length == 0
                || row.Actor.Contains(query, StringComparison.OrdinalIgnoreCase)
                || row.Name.Contains(query, StringComparison.OrdinalIgnoreCase)
                || row.Id.ToString(CultureInfo.InvariantCulture).Contains(query, StringComparison.OrdinalIgnoreCase)).ToArray();
            table.SetRows(rows.Select(row => (row.Key, row.Cells)),
                query.Length == 0 ? "等待角色與夥伴特技同步。" : "沒有符合搜尋條件的已確認特技。");
            status.Text = $"角色技能：{(snapshot.PlayerKnowledge.Ready ? "已同步" : "等待同步")}；" +
                $"夥伴資料：{snapshot.Companions.Companions.Count} 隻｜目前列出 {rows.Length} 筆特技。";
            UpdateDetails();
        }
        finally { refreshing = false; }
    }

    private void UpdateDetails()
    {
        var row = rows.FirstOrDefault(row => row.Key == table.SelectedKey);
        detail.Text = row is null ? "請選取特技查看資料。"
            : $"{row.Actor}｜{row.Name}（{row.Id}）｜等級 {row.Level}\n資料來源：{row.Source}。\n{row.MetadataText}；實際施放條件尚待核對。";
    }
    private async Task CastAsync()
    {
        try
        {
            var skill = rows.FirstOrDefault(row => row.Key == table.SelectedKey) ?? throw new InvalidOperationException("請先選取特技。");
            var state = session.Snapshot; var player = state.Player ?? throw new InvalidOperationException("請先登入。");
            var units = state.Local.Battle.Units.Where(u => !u.Exited && u.Hp > 0 && (skill.Player ? u.Layout.Pid == player.RoleId
                : u.Layout.MasterId == player.RoleId && u.Layout.NpcIndex == skill.CompanionIndex && u.Layout.Pid == skill.NpcId)).ToArray();
            if (units.Length != 1 || state.Local.Battle.Round is not {} round) throw new InvalidOperationException("所選技能的施放者不在目前可下令的戰場。");
            if (target.SelectedItem is not string selected) throw new InvalidOperationException("請先選擇戰場目標。");
            var unit = units[0];
            await session.ExecuteGameActionAsync(new("battle", "skill", unit.Layout.Pid, round, checked((int)skill.Id),
                unit.Layout.Col, unit.Layout.Row, player.Scene, Key: selected.Split('｜')[0]));
            if (!closed) detail.Text = "特技已送出，結果以伺服器回報為準。";
        }
        catch (Exception error) when (error is InvalidOperationException or Lala.Core.Protocol.ProtocolException)
        { if (!closed) detail.Text = error.Message; }
    }
}

internal sealed record SkillPresentationRow(string Key, string Actor, uint Id, string Name, long Level,
    string Source, bool Player, ushort? CompanionIndex = null, uint? NpcId = null, DesktopSkillDetails? Details = null)
{
    public string RecoveryText => Details?.RecoveryText ?? "恢復效果未驗證";
    public string MetadataText => Details is null ? "分類、消耗 SP、目標與恢復效果未驗證" :
        $"{Details.Category}｜消耗 SP {Details.SpCost}｜目標 {Details.Target}｜{RecoveryText}";
    public string[] Cells => [Actor, Id.ToString(CultureInfo.InvariantCulture), Name,
        Level.ToString(CultureInfo.InvariantCulture), Details?.Category ?? "待核對", Details?.SpCost.ToString(CultureInfo.InvariantCulture) ?? "待核對", RecoveryText + "；施放條件待核對", Source];
}

/// <summary>Read-only evidence projection shared by windows, never shared controls or action authority.</summary>
internal static class SkillPresentation
{
    public static IEnumerable<SkillPresentationRow> All(ServiceStateSnapshot state, DesktopLabels labels)
    {
        var playerName = state.Player is { } player ? $"角色 {player.Name}" : "角色（身分待同步）";
        foreach (var pair in state.PlayerKnowledge.Skills.OrderBy(pair => pair.Key))
        {
            if (pair.Key == 0 || pair.Value.Level <= 0 || Removed(state.PlayerKnowledge.RemovedSkillIds, pair.Key)) continue;
            yield return new($"player:{pair.Key}", playerName, pair.Key, labels.Skill(pair.Key),
                pair.Value.Level, Source(pair.Value.Source), true, Details: labels.SkillDetails.GetValueOrDefault(pair.Key));
        }
        foreach (var companion in state.Companions.Companions.OrderBy(pair => pair.Key))
        {
            var data = companion.Value.Data;
            var name = !string.IsNullOrWhiteSpace(data.Name) ? data.Name
                : data.NpcId <= ushort.MaxValue ? labels.Npc((ushort)data.NpcId)
                : $"夥伴 {data.NpcId}（名稱待同步）";
            foreach (var pair in companion.Value.Skills.OrderBy(pair => pair.Key))
            {
                if (pair.Key == 0 || pair.Value.Level <= 0 || Removed(companion.Value.RemovedSkillIds, pair.Key)) continue;
                yield return new($"companion:{companion.Key}:{data.NpcId}:{pair.Key}", $"夥伴#{companion.Key} {name}",
                    pair.Key, labels.Skill(pair.Key), pair.Value.Level, Source(pair.Value.Source), false, companion.Key, data.NpcId, labels.SkillDetails.GetValueOrDefault(pair.Key));
            }
        }
    }

    private static bool Removed(ImmutableArray<uint>? removed, uint id) =>
        removed is { IsDefaultOrEmpty: false } values && values.Contains(id);
    private static string Source(string? value) => string.IsNullOrWhiteSpace(value) ? "來源待同步" : value;
}
