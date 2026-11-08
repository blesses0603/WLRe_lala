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
        Ui.At(body, Ui.Column(Ui.Unavailable("施放選取特技（戰鬥內）", "SkillsCast"),
            Ui.Text("裝備附帶特技、分類、SP 與使用條件待資料核對；目前不會發送戰鬥指令。", 12, Ui.Muted)), 0, 5);
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
            : $"{row.Actor}｜{row.Name}（{row.Id}）｜等級 {row.Level}\n資料來源：{row.Source}。分類、消耗 SP、目標與施放條件尚待核對。";
    }
}

internal sealed record SkillPresentationRow(string Key, string Actor, uint Id, string Name, long Level,
    string Source, bool Player, ushort? CompanionIndex = null, uint? NpcId = null)
{
    public string[] Cells => [Actor, Id.ToString(CultureInfo.InvariantCulture), Name,
        Level.ToString(CultureInfo.InvariantCulture), "待核對", "待核對", "等待連線、回合與技能規則核對", Source];
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
                pair.Value.Level, Source(pair.Value.Source), true);
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
                    pair.Key, labels.Skill(pair.Key), pair.Value.Level, Source(pair.Value.Source), false, companion.Key, data.NpcId);
            }
        }
    }

    private static bool Removed(ImmutableArray<uint>? removed, uint id) =>
        removed is { IsDefaultOrEmpty: false } values && values.Contains(id);
    private static string Source(string? value) => string.IsNullOrWhiteSpace(value) ? "來源待同步" : value;
}
