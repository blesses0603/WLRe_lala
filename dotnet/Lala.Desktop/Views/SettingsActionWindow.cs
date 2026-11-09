using System.Globalization;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Media;

namespace Lala.Desktop;

internal sealed record SettingsActionChoice(int Id, string Label, string? ActorIdentity = null);

internal static class SettingsActions
{
    private static readonly IReadOnlyDictionary<int, string> Names = new Dictionary<int, string>
    {
        [0] = "略過此格", [-1] = "自動搜尋特技", [-2] = "背包補 HP", [-3] = "背包補 SP",
        [10001] = "自動普攻", [60021] = "防禦", [60041] = "逃跑", [10008] = "捕捉"
    };

    internal static (string[] Labels, bool Enabled) TargetOptions(int id, int kind, string? key)
    {
        if (kind != 2 && id is 0 or 60021 or 60041) return (["不需目標", "不需目標", "不需目標"], false);
        if (key is "lowHpAction" or "lowSpAction")
        {
            var resource = key == "lowSpAction" ? "SP" : "HP";
            if (kind == 2) return ([$"最低{resource}", "座標順序", $"最高{resource}"], true);
            if (id is not (10001 or 10008 or -1))
                return ([$"友方最低{resource}／敵方最低HP", "友方座標／敵方屬性", $"友方最高{resource}／敵方最高HP"], true);
        }
        return (id is 10001 or 10008 ? ["最低HP", "最低HP（基本行動）", "最高HP"] : ["最低HP", "屬性優先", "最高HP"], true);
    }

    public static SettingsActionChoice[] Choices(DesktopPublication view, string who, bool items)
    {
        if (who is not ("player" or "partner")) throw new ArgumentOutOfRangeException(nameof(who));
        var result = (items ? new[] { 0, -2, -3 } : [0, -1, 10001, 60021, 60041, 10008])
            .Select(id => new SettingsActionChoice(id, Names[id])).ToList();
        if (items || view.Snapshot.Player is not { } player) return result.ToArray();
        var state = view.Snapshot;
        var skills = SkillPresentation.All(state, view.Labels).Where(row => row.Player == (who == "player"));
        string actor = "player:" + player.RoleId.ToString(CultureInfo.InvariantCulture);
        if (who == "partner")
        {
            var matches = state.Companions.Companions.Where(pair => pair.Value.Data.NpcId == state.Companions.ActiveNpcId).ToArray();
            // A single active companion identity must be known; do not combine all companions' skills.
            if (matches.Length != 1) return result.ToArray();
            var active = matches[0];
            skills = skills.Where(row => row.CompanionIndex == active.Key && row.NpcId == active.Value.Data.NpcId);
            actor = $"partner:{player.RoleId}:{active.Key}:{active.Value.Data.NpcId}";
        }
        foreach (var row in skills)
        {
            if (row.Id > ushort.MaxValue || result.Any(choice => choice.Id == (int)row.Id)) continue;
            result.Add(new((int)row.Id, $"{row.Name}（{row.Id}）｜{row.Actor} 已觀察 Lv.{row.Level}", actor));
        }
        return result.ToArray();
    }

    public static string Label(JsonObject row, DesktopSession session, string who)
    {
        int id = BattleSettingsDraft.Int(row["id"]), kind = BattleSettingsDraft.Int(row["kind"]);
        bool basicKind = kind == 1 && id is 0 or -1 or 10001 or 60021 or 60041 or 10008
            || kind == 2 && id is 0 or -2 or -3;
        if (basicKind && Names.TryGetValue(id, out var basic)) return basic;
        var view = session.ReadView();
        if (kind == 2) return $"{view.Labels.Item((ushort)id)}（{id}，用途待核對）";
        var observed = Choices(view, who, false).FirstOrDefault(choice => choice.Id == id);
        return observed is null ? $"特技 {id}（此單位尚未同步或未學會）" : $"{view.Labels.Skill((uint)id)}（{id}）";
    }

    public static void RequireSelectable(DesktopSession session, string who, JsonObject row)
    {
        var view = session.ReadView();
        var candidate = Choices(view, who, BattleSettingsDraft.Int(row["kind"]) == 2)
            .FirstOrDefault(choice => choice.Id == BattleSettingsDraft.Int(row["id"]));
        if (candidate is null) throw new InvalidOperationException("此行動尚未通過目前單位的資料核對。");
    }
}

/// <summary>Independent modal action edit. Saving changes its parent draft, never a live command.</summary>
internal sealed class SettingsActionWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly string who;
    private readonly string? ruleKey;
    private readonly long generation;
    private readonly string identity;
    private readonly JsonObject original;
    private readonly ComboBox kind;
    private readonly ComboBox target;
    private readonly CheckBox next;
    private readonly TextBox search = new() { Name = "ActionSearch", MaxLength = 128 };
    private readonly ListBox choices = new() { Name = "ActionChoices", Background = Ui.Panel };
    private readonly TextBlock selected = Ui.Text("略過此格");
    private readonly TextBlock note = Ui.Text("只列本機角色或目前出戰夥伴的已觀察特技；實際條件仍需核對。", 12, Ui.Muted);
    private readonly Button save;
    private readonly Dictionary<string, ComboBox> conditions = new(StringComparer.Ordinal);
    private NumericUpDown? threshold;
    private SettingsActionChoice[] allChoices = [];
    private SettingsActionChoice[] visibleChoices = [];
    private int chosen;
    private string? chosenActor;
    private bool updating;
    private bool closed;

    public SettingsActionWindow(DesktopSession session, string who, JsonObject row, string? ruleKey = null)
        : base("編輯行動與條件", 960, 640)
    {
        this.session = session;
        this.who = who; this.ruleKey = ruleKey;
        var view = session.ReadView();
        generation = view.Generation; identity = view.IdentityKey;
        original = (JsonObject)row.DeepClone();
        chosen = BattleSettingsDraft.Int(row["id"]);
        kind = Ui.Combo(["技能／基本行動", "背包道具"], BattleSettingsDraft.Int(row["kind"]) - 1, "ActionKind");
        target = Ui.Combo(["最低HP", "屬性優先", "最高HP"], BattleSettingsDraft.Int(row["target"]) - 1, "ActionTarget");
        next = new CheckBox { Content = "允許次階特技（僅技能）", IsChecked = BattleSettingsDraft.Bool(row["bUseNextSkill"]), Name = "ActionNext" };
        save = Ui.Button("儲存此行動", Save, "ActionSave");
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,*,Auto,Auto"), RowSpacing = 8 };
        Ui.At(body, Ui.Column(Ui.Text("編輯行動", 22, bold: true),
            Ui.Text("先選擇行動，再核對目標與條件；儲存後返回規則草稿。", color: Ui.Muted)), 0);
        Ui.At(body, Ui.Field("行動類型", kind), 0, 1);
        Ui.At(body, Ui.Field("搜尋名稱／ID", search), 0, 2);
        var area = new Grid { ColumnDefinitions = new ColumnDefinitions("*,280"), ColumnSpacing = 12 };
        Ui.At(area, choices, 0);
        var options = Ui.Column(selected, Ui.Field("目標排序", target, "88,*"), next);
        foreach (var field in new[] { "notice", "compareKind" })
        {
            if (!row.ContainsKey(field)) continue;
            var combo = Ui.Combo(field == "notice" ? ["同方任一單位", "本機角色", "出戰夥伴"] : ["大於", "小於"], BattleSettingsDraft.Int(row[field]) - 1);
            conditions[field] = combo;
            options.Children.Add(Ui.Field(field == "notice" ? "觀察對象" : "敵 HP 比較", combo, "88,*"));
        }
        if (row.ContainsKey("value"))
        {
            threshold = Ui.Number(BattleSettingsDraft.Number(row["value"]), 0, decimal.MaxValue, width: 150);
            threshold.FormatString = "0.##";
            options.Children.Add(Ui.Field(ruleKey == "lowHpAction" ? "HP <" : ruleKey == "lowSpAction" ? "SP <" : "HP 門檻", threshold, "88,*"));
        }
        options.Children.Add(Ui.Text("SP 不足仍可編輯本機規則。\n友方技能不代表恢復 SP，效果未驗證。\n0 為略過，不會送出指令。", 12, Ui.Muted));
        Ui.At(area, new ScrollViewer { Content = options, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }, 1);
        Ui.At(body, area, 0, 3);
        Ui.At(body, note, 0, 4);
        Ui.At(body, Ui.Row(Ui.Button("取消", () => Close(null), "ActionCancel"), save), 0, 5);
        SetBody(body);

        kind.SelectionChanged += (_, _) =>
        {
            if (updating) return;
            chosen = 0; chosenActor = null; next.IsChecked = false;
            Populate();
        };
        search.TextChanged += (_, _) => { if (!updating) Populate(); };
        choices.SelectionChanged += (_, _) =>
        {
            if (updating || choices.SelectedIndex < 0 || choices.SelectedIndex >= visibleChoices.Length) return;
            var choice = visibleChoices[choices.SelectedIndex];
            chosen = choice.Id; chosenActor = choice.ActorIdentity;
            UpdateSelection();
        };
        session.Changed += SessionChanged;
        Closed += (_, _) => { closed = true; session.Changed -= SessionChanged; };
        Populate();
        chosenActor = allChoices.FirstOrDefault(choice => choice.Id == chosen)?.ActorIdentity;
        UpdateSelection();
    }

    private bool IsCurrent
    {
        get
        {
            var view = session.ReadView();
            return !closed && view.Generation == generation && view.IdentityKey == identity;
        }
    }

    private void SessionChanged() => Ui.OnUi(() => { if (!closed) Populate(); });

    private void Populate()
    {
        if (closed) return;
        var view = session.ReadView();
        if (view.Generation != generation || view.IdentityKey != identity)
        {
            save.IsEnabled = false;
            note.Text = "帳號或連線已變更，此行動未儲存；請關閉後重新開啟設定。";
            return;
        }
        updating = true;
        try
        {
            bool item = kind.SelectedIndex == 1;
            allChoices = SettingsActions.Choices(view, who, item);
            string query = (search.Text ?? "").Trim();
            visibleChoices = allChoices.Where(choice => query.Length == 0 || choice.Label.Contains(query, StringComparison.OrdinalIgnoreCase)
                || choice.Id.ToString(CultureInfo.InvariantCulture).Contains(query, StringComparison.OrdinalIgnoreCase)).ToArray();
            choices.ItemsSource = visibleChoices.Select(choice => choice.Label).ToArray();
            choices.SelectedIndex = Array.FindIndex(visibleChoices, choice => choice.Id == chosen);
            next.IsEnabled = !item;
            if (item) next.IsChecked = false;
            note.Text = item ? "物品效果與用途尚未核對；目前僅保留基本補給指令，不新增任意道具。"
                : "只列本機角色或目前出戰夥伴的已觀察特技；實際條件仍需核對。";
            UpdateSelection();
        }
        finally { updating = false; }
    }

    private void UpdateSelection()
    {
        var policy = Math.Clamp(target.SelectedIndex, 0, 2);
        var options = SettingsActions.TargetOptions(chosen, kind.SelectedIndex + 1, ruleKey);
        target.ItemsSource = options.Labels; target.SelectedIndex = policy; target.IsEnabled = options.Enabled;
        var choice = allChoices.FirstOrDefault(choice => choice.Id == chosen);
        bool actorMatches = choice is not null && (choice.ActorIdentity is null || choice.ActorIdentity == chosenActor);
        selected.Text = choice?.Label ?? $"原設定 ID {chosen} 尚未核對，請重新選擇或略過此格。";
        if (choice is not null && !actorMatches) selected.Text += "\n目前單位已變更，請重新選擇此行動。";
        save.IsEnabled = IsCurrent && actorMatches;
    }

    private void Save()
    {
        if (!IsCurrent) return;
        try
        {
            var view = session.ReadView();
            var choice = SettingsActions.Choices(view, who, kind.SelectedIndex == 1).FirstOrDefault(choice => choice.Id == chosen);
            if (choice is null || choice.ActorIdentity is not null && choice.ActorIdentity != chosenActor)
                throw new InvalidOperationException("行動或單位已變更。");
            var result = (JsonObject)original.DeepClone();
            result["id"] = chosen; result["kind"] = kind.SelectedIndex + 1; result["target"] = target.SelectedIndex + 1;
            result["bUseNextSkill"] = kind.SelectedIndex == 0 && next.IsChecked == true;
            foreach (var pair in conditions) result[pair.Key] = pair.Value.SelectedIndex + 1;
            if (threshold is not null)
                result["value"] = threshold.Value ?? throw new InvalidOperationException("門檻不可為空。");
            Close(result);
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error))
        {
            note.Text = "行動或條件無效，或目前單位／特技已變更；請重新選擇。草稿未變更。";
            note.Foreground = Ui.Gold;
            save.IsEnabled = false;
        }
    }
}
