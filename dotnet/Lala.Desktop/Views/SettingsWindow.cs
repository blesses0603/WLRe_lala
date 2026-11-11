using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;

namespace Lala.Desktop;

/// <summary>Detached reproduction of Python's five-tab AI editor. Applying saves UI preferences only.</summary>
public sealed class SettingsWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly long generation;
    private readonly string identity;
    private readonly CancellationTokenSource lifetime = new();
    private readonly TextBlock note = Ui.Text("變更先留在草稿；套用會儲存本機預覽設定，不會自動啟動 AI。", color: Ui.Muted);
    private readonly TabControl tabs = new() { Name = "SettingsTabs" };
    private readonly Button apply;
    private readonly Button load;
    private readonly Button export;
    private readonly Dictionary<string, ContentControl> ruleHosts = new(StringComparer.Ordinal);
    private readonly Dictionary<string, ListBox> ruleMenus = new(StringComparer.Ordinal);
    private readonly Dictionary<string, TextBlock> balances = new(StringComparer.Ordinal);
    private readonly Dictionary<string, TextBlock> percentages = new(StringComparer.Ordinal);
    private readonly Dictionary<string, NumericUpDown> numbers = new(StringComparer.Ordinal);
    private readonly List<(JsonArray Values, int Index, Button Button, string? Resource)> slots = [];
    private BattleSettingsDraft draft;
    private bool closed;
    private bool busy;
    private bool actionOpen;
    private static readonly string[] RuleKeys = ["orderAction", "repeatAction", "roundAction", "misc"];
    private static readonly string[] Notices = ["同方任一單位", "本機角色", "出戰夥伴"];

    public SettingsWindow(DesktopSession session, int initialTab = 0)
        : base("自動戰鬥設定", 1080, 720)
    {
        ArgumentNullException.ThrowIfNull(session);
        this.session = session;
        var view = session.ReadView();
        generation = view.Generation;
        identity = view.IdentityKey;
        try { draft = session.Preferences.ReadBattle(identity); }
        catch (Exception error) when (SettingsFiles.IsExpected(error))
        {
            draft = new BattleSettingsDraft();
            note.Text = "既有設定無法讀取，暫顯示預設草稿；尚未覆寫原設定。請載入有效 JSON，或確認草稿後再套用。";
            note.Foreground = Ui.Gold;
        }

        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto"), RowSpacing = 8 };
        Ui.At(body, Ui.Column(Ui.Text("自動戰鬥設定", 22, bold: true),
            Ui.Text("角色與夥伴規則、補給及停止條件；修改會先保留在草稿。", color: Ui.Muted)), 0);
        Ui.At(body, tabs, 0, 1);
        note.Name = "SettingsStatus";
        Ui.At(body, note, 0, 2);
        var buttons = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto,Auto"), ColumnSpacing = 6 };
        load = Ui.Button("載入 JSON", () => _ = LoadAsync(), "SettingsLoad");
        export = Ui.Button("匯出目前設定", () => _ = ExportAsync(), "SettingsExport");
        apply = Ui.Button("套用全部設定", async () => { if (await ApplyDraftAsync()) Close(); }, "SettingsApply");
        Ui.At(buttons, load, 0); Ui.At(buttons, export, 1);
        Ui.At(buttons, Ui.Button("取消", Close, "SettingsCancel"), 3); Ui.At(buttons, apply, 4);
        Ui.At(body, buttons, 0, 3);
        SetBody(body);
        BuildPages();
        SelectTab(initialTab);
        session.Changed += SessionChanged;
        Closed += (_, _) =>
        {
            closed = true;
            session.Changed -= SessionChanged;
            lifetime.Cancel();
            lifetime.Dispose();
        };
        UpdateObservedLabels();
    }

    public BattleSettingsDraft DraftSnapshot => draft.Copy();
    public string StatusText => note.Text ?? "";
    public int SelectedTab => tabs.SelectedIndex;
    public void SelectTab(int index)
    {
        if (index is < 0 or > 4) throw new ArgumentOutOfRangeException(nameof(index));
        tabs.SelectedIndex = index;
    }

    public void SelectRuleGroup(string who, string key)
    {
        EnsureCurrent();
        if (!ruleMenus.TryGetValue(who, out var menu)) throw new ArgumentOutOfRangeException(nameof(who));
        var index = Array.IndexOf(RuleKeys, key);
        if (index < 0) throw new ArgumentOutOfRangeException(nameof(key));
        menu.SelectedIndex = index;
    }

    public void SetRuleEnabled(string who, string key, bool enabled)
    {
        EnsureCurrent();
        var group = Group(key);
        Profile(who)[group.Flag] = enabled;
        RenderRule(who);
    }

    public void SetAction(string who, string key, int index, JsonObject value)
    {
        EnsureCurrent();
        var candidate = draft.Copy();
        SetRow(BattleSettingsDraft.Profile(candidate.Value, who), key, index, (JsonObject)value.DeepClone());
        _ = candidate.ToJson();
        var profile = BattleSettingsDraft.Profile(candidate.Value, who);
        var normalized = (JsonObject)(Group(key).Count == 1 ? profile[key]! : profile[key]![index]!);
        SettingsActions.RequireSelectable(session, who, normalized);
        SetRow(Profile(who), key, index, (JsonObject)normalized.DeepClone());
        RenderRule(who);
    }

    public void ClearAction(string who, string key, int index)
    {
        EnsureCurrent();
        var row = (JsonObject)ActionRow(who, key, index).DeepClone();
        row["id"] = 0; row["kind"] = 1; row["bUseNextSkill"] = false;
        SetRow(Profile(who), key, index, row);
        RenderRule(who);
    }

    public bool MoveAction(string who, string key, int index, int direction)
    {
        EnsureCurrent();
        if (direction is not (-1 or 1)) throw new ArgumentOutOfRangeException(nameof(direction));
        var profile = Profile(who);
        if (profile[key] is not JsonArray array || index < 0 || index >= array.Count || index + direction < 0 || index + direction >= array.Count) return false;
        var first = array[index]!.DeepClone();
        var second = array[index + direction]!.DeepClone();
        array[index] = second; array[index + direction] = first;
        RenderRule(who);
        return true;
    }

    public void ImportJson(string text)
    {
        EnsureCurrent();
        var replacement = BattleSettingsDraft.Parse(text);
        draft = replacement;
        BuildPages();
        UpdateObservedLabels();
        SetNote("已載入草稿，可繼續修改；尚未儲存或啟動 AI。");
    }

    public string ExportDraftJson() { EnsureCurrent(); ValidateEditors(); return draft.ToJson(); }

    public bool ApplyDraft()
    {
        try
        {
            EnsureCurrent();
            ValidateEditors();
            session.SaveBattle(generation, identity, draft.Copy());
            SetNote("已儲存本機預覽設定；沒有啟動 AI、徘徊或任何遊戲操作。");
            return true;
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error))
        {
            SetNote(IsCurrent ? "設定未能儲存；請檢查欄位內容與檔案寫入權限。原草稿仍保留。"
                : "帳號或連線已變更，草稿未套用；請重新開啟設定。", true);
            return false;
        }
    }
    public async Task<bool> ApplyDraftAsync()
    {
        if (busy) return false;
        if (!ApplyDraft()) return false;
        busy = true; apply.IsEnabled = false;
        try
        {
            await session.ReapplyActiveSettingsAsync(generation, identity, "battle", "roaming");
            SetNote("設定已儲存；執行中的 AI／徘徊及補給設定已更新，未啟動的功能維持關閉。");
            return true;
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException)
        { SetNote("設定已儲存，但執行中的 AI 未能更新，請確認連線後重新套用。", true); return false; }
        finally { busy = false; if (!closed) apply.IsEnabled = IsCurrent; }
    }

    public void ClearRecoverySlot(string resource, int index)
    {
        EnsureCurrent();
        if (resource is not ("hp" or "sp")) throw new ArgumentOutOfRangeException(nameof(resource));
        ClearSlot((JsonArray)draft.Value["recovery"]![resource]!["items"]!, index);
    }

    public void ClearMaintenanceSlot(string kind, int index)
    {
        EnsureCurrent();
        if (kind is not ("repair" or "cleanup")) throw new ArgumentOutOfRangeException(nameof(kind));
        ClearSlot((JsonArray)draft.Value["maintenance"]![kind + "_items"]!, index);
    }

    private bool IsCurrent
    {
        get
        {
            var view = session.ReadView();
            return !closed && view.Generation == generation && view.IdentityKey == identity;
        }
    }
    private void EnsureCurrent()
    {
        if (!IsCurrent) throw new InvalidOperationException("帳號或連線已變更，請重新開啟設定。");
        session.RequireCurrentDraft(generation);
    }

    private JsonObject Profile(string who)
    {
        if (who is not ("player" or "partner")) throw new ArgumentOutOfRangeException(nameof(who));
        return BattleSettingsDraft.Profile(draft.Value, who);
    }

    private static (string Key, string Flag, string Title, int Count) Group(string key) =>
        BattleSettingsDraft.Groups.FirstOrDefault(group => group.Key == key) is var result && result.Key is not null
            ? result : throw new ArgumentOutOfRangeException(nameof(key));

    private JsonObject ActionRow(string who, string key, int index)
    {
        var group = Group(key);
        if (index < 0 || index >= group.Count) throw new ArgumentOutOfRangeException(nameof(index));
        return group.Count == 1 ? (JsonObject)Profile(who)[key]! : (JsonObject)Profile(who)[key]![index]!;
    }

    private static void SetRow(JsonObject profile, string key, int index, JsonObject value)
    {
        var group = Group(key);
        if (index < 0 || index >= group.Count) throw new ArgumentOutOfRangeException(nameof(index));
        if (group.Count == 1) profile[key] = value; else profile[key]![index] = value;
    }

    private void BuildPages()
    {
        var selected = Math.Max(0, tabs.SelectedIndex);
        ruleHosts.Clear(); ruleMenus.Clear(); balances.Clear(); percentages.Clear(); slots.Clear(); numbers.Clear();
        tabs.ItemsSource = new[]
        {
            new TabItem { Header = "角色規則", Content = RulesPage("player") },
            new TabItem { Header = "夥伴規則", Content = RulesPage("partner") },
            new TabItem { Header = "補給設定", Content = RecoveryPage() },
            new TabItem { Header = "修理／整理", Content = MaintenancePage() },
            new TabItem { Header = "停止條件", Content = Ui.Column(
                Flag(draft.Value, "bPlayerDieCloseAI", "角色陣亡時停止 AI 與徘徊", "SettingsPlayerDeath"),
                Flag(draft.Value, "bNPCDieCloseAI", "夥伴陣亡時停止 AI 與徘徊", "SettingsPartnerDeath")) }
        };
        tabs.SelectedIndex = selected;
    }

    private Control RulesPage(string who)
    {
        var page = new Grid { ColumnDefinitions = new ColumnDefinitions("132,*"), ColumnSpacing = 10 };
        var menu = new ListBox
        {
            Name = "SettingsRules_" + who, ItemsSource = new[] { "順序行動", "循環行動", "指定回合", "雜項設定" },
            SelectedIndex = 0, Background = Ui.Panel, Padding = new Thickness(3)
        };
        var host = new ContentControl();
        ruleHosts[who] = host; ruleMenus[who] = menu;
        menu.SelectionChanged += (_, _) => { if (IsCurrent) RenderRule(who); };
        Ui.At(page, menu, 0);
        var area = new Grid { RowDefinitions = new RowDefinitions("Auto,*"), RowSpacing = 8 };
        Ui.At(area, Ui.Text("點選行動名稱編輯。優先序：陣亡 → 敵 HP → 低 HP → 低 SP → 回合 → 循環 → 順序 → 普攻。", 12, Ui.Muted), 0);
        Ui.At(area, new ScrollViewer { Content = host, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }, 0, 1);
        Ui.At(page, area, 1);
        RenderRule(who);
        return page;
    }

    private void RenderRule(string who)
    {
        if (!ruleHosts.TryGetValue(who, out var host)) return;
        foreach (var binding in numbers.Keys.Where(binding => binding.StartsWith(who + ":", StringComparison.Ordinal)).ToArray())
            numbers.Remove(binding);
        var index = ruleMenus[who].SelectedIndex;
        var key = RuleKeys[Math.Clamp(index, 0, 3)];
        var content = new StackPanel { Spacing = 7 };
        foreach (var rule in key == "misc" ? new[] { "lowHpAction", "lowSpAction", "enemyHpAction", "deadAction" } : [key])
            content.Children.Add(RuleCard(who, rule, key == "misc"));
        host.Content = content;
    }

    private Control RuleCard(string who, string key, bool compact)
    {
        var group = Group(key);
        var profile = Profile(who);
        var heading = key switch
        {
            "orderAction" => "使用特定指令（預設普攻）", "repeatAction" => "循環使用指令", "roundAction" => "特定回合指令",
            "lowHpAction" => "HP 低於設定數值時", "lowSpAction" => "SP 低於設定數值時", "enemyHpAction" => "敵方 HP 條件", _ => "我方陣亡時"
        };
        var card = new StackPanel { Spacing = compact ? 4 : 7 };
        var top = Ui.Row(Flag(profile, group.Flag, heading, $"Settings_{who}_{group.Flag}"));
        if (group.Count == 1)
        {
            var row = ActionRow(who, key, 0);
            if (row.ContainsKey("notice")) top.Children.Add(Choice(row, "notice", Notices));
            if (row.ContainsKey("compareKind")) top.Children.Add(Choice(row, "compareKind", ["大於", "小於"]));
            if (row.ContainsKey("value")) top.Children.Add(Number(row, "value", 0, decimal.MaxValue, bindingKey: who + ":" + key));
        }
        card.Children.Add(top);
        if (key is "lowHpAction" or "lowSpAction")
            card.Children.Add(Ui.Text((key == "lowHpAction" ? "HP" : "SP") + " < 門檻 → 使用此列技能／指令；兩列獨立保存。", 12, Ui.Muted));
        for (var i = 0; i < group.Count; i++)
        {
            var index = i;
            var row = ActionRow(who, key, index);
            var actions = new Grid { ColumnDefinitions = new ColumnDefinitions(compact ? "*,Auto,Auto,Auto" : "80,*,Auto,Auto,Auto"), ColumnSpacing = 6 };
            var actionColumn = compact ? 0 : 1;
            if (!compact) Ui.At(actions, Ui.Text(key == "orderAction" ? $"第 {index + 1} 順位" : key == "roundAction" ? $"第 {index + 1} 回合" : $"順序 {index + 1}"), 0);
            var edit = Ui.Button(SettingsActions.Label(row, session, who), () => _ = EditActionAsync(who, key, index), $"SettingsEdit_{who}_{key}_{index}");
            edit.HorizontalAlignment = HorizontalAlignment.Stretch;
            edit.Content = Ellipsis(SettingsActions.Label(row, session, who));
            ToolTip.SetTip(edit, SettingsActions.Label(row, session, who));
            Ui.At(actions, edit, actionColumn);
            var up = Ui.Button("↑", () => EditDraft(() => MoveAction(who, key, index, -1)), enabled: index > 0);
            var down = Ui.Button("↓", () => EditDraft(() => MoveAction(who, key, index, 1)), enabled: index + 1 < group.Count);
            if (group.Count > 1)
            {
                Ui.At(actions, up, actionColumn + 1); Ui.At(actions, down, actionColumn + 2);
            }
            Ui.At(actions, Ui.Button("清除", () => EditDraft(() => ClearAction(who, key, index)), $"SettingsClear_{who}_{key}_{index}"), actionColumn + 3);
            card.Children.Add(actions);
            var next = Flag(row, "bUseNextSkill", compact ? "次階特技" : "允許下一階特技", $"SettingsNext_{who}_{key}_{index}");
            next.IsEnabled = BattleSettingsDraft.Int(row["kind"]) == 1;
            var options = SettingsActions.TargetOptions(BattleSettingsDraft.Int(row["id"]), BattleSettingsDraft.Int(row["kind"]), key);
            var targetChoice = Choice(row, "target", options.Labels);
            targetChoice.IsEnabled = options.Enabled;
            card.Children.Add(Ui.Row(Ui.Text("優先目標"), targetChoice, next));
        }
        if (key == "orderAction") card.Children.Add(Ui.Text("第一順位不可用才試第二順位；不是同回合連續施放兩次。", 12, Ui.Muted));
        if (key == "repeatAction") card.Children.Add(Ui.Text("每回合輪用一格，只計入非空指令。", 12, Ui.Muted));
        return new Border { Background = Ui.Panel, CornerRadius = new CornerRadius(6), Padding = new Thickness(8, 6), Child = card };
    }

    private Control RecoveryPage()
    {
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,*"), ColumnDefinitions = new ColumnDefinitions("*,*"), ColumnSpacing = 10, RowSpacing = 7 };
        Ui.At(page, Flag(draft.Value, "field_heal", "啟用戰後補給（HP／SP 共用開關）", "SettingsFieldHeal"), 0, 0, 2);
        Ui.At(page, RecoveryColumn("hp"), 0, 1);
        Ui.At(page, RecoveryColumn("sp"), 1, 1);
        return page;
    }

    private Control RecoveryColumn(string resource)
    {
        var config = (JsonObject)draft.Value["recovery"]![resource]!;
        var caption = resource.ToUpperInvariant();
        var column = new StackPanel { Spacing = 5 };
        var balance = Ui.Text("藥水儲存槽：尚未同步", 12, Ui.Muted); balances[resource] = balance;
        column.Children.Add(Ui.Row(Ui.Text(caption + " 補給", 16, bold: true), balance));
        var first = new CheckBox { Content = "優先使用藥水儲存槽回復 " + caption, IsChecked = config["storage"]!.GetValue<string>() == "first" };
        var after = new CheckBox { Content = "指定補品用完後，使用藥水儲存槽", IsChecked = config["storage"]!.GetValue<string>() == "after" };
        first.IsCheckedChanged += (_, _) =>
        {
            if (!IsCurrent) return;
            if (first.IsChecked == true) { config["storage"] = "first"; after.IsChecked = false; }
            else if (config["storage"]!.GetValue<string>() == "first") config["storage"] = "off";
        };
        after.IsCheckedChanged += (_, _) =>
        {
            if (!IsCurrent) return;
            if (after.IsChecked == true) { config["storage"] = "after"; first.IsChecked = false; }
            else if (config["storage"]!.GetValue<string>() == "after") config["storage"] = "off";
        };
        column.Children.Add(first);
        column.Children.Add(Flag(config, "enabled", "自動使用指定 " + caption + " 補品（由左至右、上至下）", "SettingsRecovery_" + resource));
        column.Children.Add(SlotGrid((JsonArray)config["items"]!, 3, caption + " 補品", "SettingsSupply_" + resource, resource));
        column.Children.Add(Ui.Text("點格選擇已核對效果的背包補品；右鍵清除。低於門檻時回復，儲存設定不會啟動 AI。", 12, Ui.Muted));
        column.Children.Add(after);
        column.Children.Add(Flag(config, "other_items", "指定補品用完後，使用背包內其他 " + caption + " 補品", "SettingsOtherSupply_" + resource));
        foreach (var who in new[] { "player", "partner" })
        {
            var key = who + "_percent";
            var amount = Ui.Text("", 12, Ui.Muted); percentages[resource + ":" + who] = amount;
            var slider = new Slider { Minimum = 0, Maximum = 100, TickFrequency = 1, IsSnapToTickEnabled = true,
                Value = BattleSettingsDraft.Int(config[key]), Name = "SettingsThreshold_" + resource + "_" + who };
            slider.ValueChanged += (_, _) =>
            {
                if (!IsCurrent) return;
                config[key] = (int)Math.Round(slider.Value);
                if (who == "player") draft.Value["field_" + resource + "_percent"] = (int)Math.Round(slider.Value);
                UpdateObservedLabels();
            };
            column.Children.Add(Ui.Row(Ui.Text((who == "player" ? "玩家" : "夥伴") + caption + " 使用門檻"), amount));
            var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), ColumnSpacing = 6 };
            Ui.At(line, Ui.Button("－", () => slider.Value = Math.Max(0, slider.Value - 1)), 0);
            Ui.At(line, slider, 1);
            Ui.At(line, Ui.Button("＋", () => slider.Value = Math.Min(100, slider.Value + 1)), 2);
            column.Children.Add(line);
        }
        return new ScrollViewer { Content = column, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
    }

    private Control MaintenancePage()
    {
        var config = (JsonObject)draft.Value["maintenance"]!;
        var content = new StackPanel { Spacing = 8 };
        content.Children.Add(Ui.Text("啟用 AI 後，在戰鬥與戰後事件結束時執行；目前僅編輯本機設定，尚未接通執行。", 12, Ui.Muted));
        content.Children.Add(Ui.Row(Flag(config, "repair_enabled", "戰後修復角色／出戰夥伴剩餘耐久低於或等於門檻的普通裝備", "SettingsRepairEnabled"),
            Number(config, "repair_below", 0, 249, integer: true)));
        content.Children.Add(Ui.Text("剩餘耐久使用 250 點制，預設 50；特殊、限時及已損壞裝備不自動修理。", 12, Ui.Muted));
        content.Children.Add(Ui.Text("修理道具順序（由左至右；只從背包選擇）"));
        var repair = SlotGrid((JsonArray)config["repair_items"]!, 2, "修理道具", "SettingsRepairItem");
        repair.Width = 500; repair.HorizontalAlignment = HorizontalAlignment.Left;
        content.Children.Add(repair);
        content.Children.Add(new Separator());
        content.Children.Add(Flag(config, "cleanup_enabled", "戰鬥結束後，自動販售／丟棄指定物品", "SettingsCleanupEnabled"));
        content.Children.Add(Ui.Text("依官方限制決定販售或丟棄；目前尚無可供選取的已核對物品用途與限制。", 12, Ui.Muted));
        content.Children.Add(SlotGrid((JsonArray)config["cleanup_items"]!, 5, "整理物品", "SettingsCleanupItem"));
        content.Children.Add(Ui.Text("已匯入的物品 ID 保留並標示待核對；點格檢視，右鍵可清除。設定不會自動執行。", 12, Ui.Muted));
        return new ScrollViewer { Content = content, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
    }

    private Grid SlotGrid(JsonArray values, int columns, string title, string name, string? resource = null)
    {
        var grid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions(string.Join(',', Enumerable.Repeat("*", columns))),
            RowDefinitions = new RowDefinitions(string.Join(',', Enumerable.Repeat("Auto", (values.Count + columns - 1) / columns))),
            ColumnSpacing = 7, RowSpacing = 5
        };
        for (var i = 0; i < values.Count; i++)
        {
            var index = i;
            var button = Ui.Button("＋", () => _ = OpenSlotAsync(values, index, title, resource), name + "_" + index);
            button.HorizontalAlignment = HorizontalAlignment.Stretch;
            var clear = new MenuItem { Header = "清除此格" };
            clear.Click += (_, _) => { if (IsCurrent) ClearSlot(values, index); };
            button.ContextMenu = new ContextMenu { ItemsSource = new[] { clear } };
            slots.Add((values, index, button, resource));
            Ui.At(grid, button, index % columns, index / columns);
        }
        return grid;
    }

    private async Task OpenSlotAsync(JsonArray values, int index, string title, string? resource)
    {
        if (!IsCurrent || actionOpen) return;
        actionOpen = true;
        try
        {
            var id = BattleSettingsDraft.Int(values[index]);
            if (resource is not null)
            {
                var choices = session.Catalogs is { } catalogs ? Lala.Core.Gameplay.FieldRecoveryPlanning.AvailableItems(session.Snapshot, catalogs, resource) : [];
                var supply = new SettingsSupplySlotWindow(title, choices, session.ReadView().Labels);
                ushort? selected = await supply.ShowDialog<ushort?>(this);
                if (selected is { } item && IsCurrent)
                {
                    if (item == 0) ClearSlot(values, index);
                    else { SetRecoverySlot(resource, index, item); }
                }
                return;
            }
            var picker = new SettingsItemSlotWindow(title, id == 0 ? "此格尚未指定物品。" : session.ReadView().Labels.Item((ushort)id) + $"（{id}，待核對）");
            bool clear = await picker.ShowDialog<bool>(this);
            if (clear && IsCurrent) ClearSlot(values, index);
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error)) { if (!closed) SetNote("選擇視窗無法開啟，草稿未變更。", true); }
        finally { actionOpen = false; }
    }

    public void SetRecoverySlot(string resource, int index, ushort itemId)
    {
        EnsureCurrent();
        if (resource is not ("hp" or "sp") || index is < 0 or >= 10) throw new ArgumentOutOfRangeException(nameof(resource));
        if (session.Catalogs is not { } catalogs || !Lala.Core.Gameplay.FieldRecoveryPlanning.AvailableItems(session.Snapshot, catalogs, resource).Any(i => i.ItemId == itemId))
            throw new InvalidOperationException("物品已離開背包或回復效果尚未核對。");
        draft.Value["recovery"]![resource]!["items"]![index] = itemId;
        UpdateObservedLabels();
    }

    private void ClearSlot(JsonArray values, int index)
    {
        if (index < 0 || index >= values.Count) throw new ArgumentOutOfRangeException(nameof(index));
        values[index] = 0;
        UpdateObservedLabels();
    }

    private async Task EditActionAsync(string who, string key, int index)
    {
        if (!IsCurrent || actionOpen) return;
        actionOpen = true;
        try
        {
            var editor = new SettingsActionWindow(session, who, ActionRow(who, key, index), key);
            var result = await editor.ShowDialog<JsonObject?>(this);
            if (result is not null && IsCurrent) SetAction(who, key, index, result);
        }
        catch (Exception error) when (SettingsFiles.IsExpected(error)) { if (!closed) SetNote("行動未能寫入草稿；角色或技能資料可能已變更，請重新選擇。", true); }
        finally { actionOpen = false; }
    }

    private CheckBox Flag(JsonObject value, string key, string title, string name)
    {
        var check = new CheckBox { Content = title, IsChecked = BattleSettingsDraft.Bool(value[key]), Name = name };
        check.IsCheckedChanged += (_, _) => { if (IsCurrent) value[key] = check.IsChecked == true; };
        return check;
    }

    private ComboBox Choice(JsonObject value, string key, string[] options)
    {
        var choice = Ui.Combo(options, BattleSettingsDraft.Int(value[key]) - 1);
        choice.MinWidth = 100;
        choice.SelectionChanged += (_, _) => { if (IsCurrent && choice.SelectedIndex >= 0) value[key] = choice.SelectedIndex + 1; };
        return choice;
    }

    private NumericUpDown Number(JsonObject value, string key, decimal minimum, decimal maximum, bool integer = false, string? bindingKey = null)
    {
        var number = Ui.Number(BattleSettingsDraft.Number(value[key]), minimum, maximum, width: 100);
        numbers[bindingKey ?? key] = number;
        number.FormatString = integer ? "0" : "0.##";
        number.ValueChanged += (_, _) =>
        {
            if (!IsCurrent || number.Value is not { } current) return;
            if (integer) value[key] = (int)Math.Round(current); else value[key] = current;
        };
        return number;
    }

    private void ValidateEditors()
    {
        if (numbers.Values.Any(editor => editor.Value is null))
            throw new InvalidDataException("設定數值不可留白。");
    }

    private static TextBlock Ellipsis(string text) => new()
    {
        Text = text, Foreground = Ui.Ink, FontSize = 13,
        TextWrapping = TextWrapping.NoWrap, TextTrimming = TextTrimming.CharacterEllipsis
    };

    private void SessionChanged() => Ui.OnUi(() =>
    {
        if (closed) return;
        if (!IsCurrent)
        {
            tabs.IsEnabled = false;
            apply.IsEnabled = false; load.IsEnabled = false; export.IsEnabled = false;
            SetNote("帳號或連線已變更，草稿未套用；請關閉並重新開啟設定。", true);
            foreach (var window in OwnedWindows.ToArray()) window.Close();
            return;
        }
        UpdateObservedLabels();
    });

    private void UpdateObservedLabels()
    {
        if (closed) return;
        var view = session.ReadView();
        var state = view.Snapshot;
        foreach (var (values, index, button, resource) in slots)
        {
            int id = BattleSettingsDraft.Int(values[index]);
            var text = id == 0 ? $"{index + 1}　＋" : $"{index + 1} {view.Labels.Item((ushort)id)}（待核對）";
            if (id != 0 && resource is not null && session.Catalogs is { } catalogs)
            {
                var item = Lala.Core.Gameplay.FieldRecoveryPlanning.AvailableItems(state, catalogs, resource).FirstOrDefault(i => i.ItemId == id);
                if (item is not null) text = $"{index + 1} {view.Labels.Item((ushort)id)} · {resource.ToUpperInvariant()} +{(resource == "hp" ? item.Hp : item.Sp)} · ×{item.Count}";
            }
            button.Content = Ellipsis(text); ToolTip.SetTip(button, text);
        }
        foreach (var resource in new[] { "hp", "sp" })
        {
            if (balances.TryGetValue(resource, out var balance))
            {
                var value = state.Recovery.Resources.GetValueOrDefault(resource)?.Value;
                balance.Text = "藥水儲存槽：" + (value?.ToString(CultureInfo.InvariantCulture) ?? "尚未同步");
            }
            foreach (var who in new[] { "player", "partner" })
            {
                if (!percentages.TryGetValue(resource + ":" + who, out var label)) continue;
                var percent = BattleSettingsDraft.Int(draft.Value["recovery"]![resource]![who + "_percent"]);
                long? current = null, maximum = null;
                if (who == "player")
                {
                    if (state.PlayerKnowledge.Stats.TryGetValue(resource, out var hp)) current = hp;
                    if (state.PlayerKnowledge.Stats.TryGetValue("max_" + resource, out var max)) maximum = max;
                }
                else if (state.Companions.Companions.Values.FirstOrDefault(profile => profile.Data.NpcId == state.Companions.ActiveNpcId) is { } partner)
                {
                    if (partner.StatOverrides.TryGetValue(resource, out var hp)) current = hp;
                    else current = resource == "hp" ? partner.Data.Hp : partner.Data.Sp;
                    if (partner.StatOverrides.TryGetValue("max_" + resource, out var max)) maximum = max;
                }
                label.Text = current is not null && maximum is > 0 ? $"{percent}%（{current}/{maximum}）" : $"{percent}%（尚未同步）";
            }
        }
    }

    private void SetNote(string text, bool error = false)
    {
        note.Text = text; note.Foreground = error ? Ui.Gold : Ui.Muted;
    }

    private void EditDraft(Action edit)
    {
        try { edit(); }
        catch (Exception error) when (SettingsFiles.IsExpected(error))
        {
            SetNote("草稿無法變更；請確認欄位，或在帳號變更後重新開啟設定。", true);
        }
    }

    private void SetBusy(bool value)
    {
        busy = value;
        if (closed) return;
        load.IsEnabled = export.IsEnabled = apply.IsEnabled = !value && IsCurrent;
    }

    private async Task LoadAsync()
    {
        if (busy || !IsCurrent) return;
        SetBusy(true);
        try
        {
            if (!StorageProvider.CanOpen) { SetNote("此環境沒有可用的檔案選擇器，設定未載入。", true); return; }
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = "載入 AI 設定 JSON", AllowMultiple = false,
                FileTypeFilter = [new FilePickerFileType("AI 設定") { Patterns = ["*.json"] }]
            });
            if (files.Count == 0 || closed) return;
            EnsureCurrent();
            using var file = files[0];
            await using var stream = await file.OpenReadAsync();
            var text = await SettingsFiles.ReadBoundedAsync(stream, lifetime.Token);
            if (closed) return;
            ImportJson(text);
        }
        catch (OperationCanceledException) { }
        catch (Exception error) when (SettingsFiles.IsExpected(error))
        {
            if (!closed) SetNote(IsCurrent ? "JSON 無法讀取或格式不符（上限 128 KiB）；目前草稿保留，未套用。"
                : "帳號或連線已變更，設定未載入；請重新開啟設定。", true);
        }
        finally { SetBusy(false); }
    }

    private async Task ExportAsync()
    {
        if (busy || !IsCurrent) return;
        SetBusy(true);
        try
        {
            var bytes = Encoding.UTF8.GetBytes(ExportDraftJson());
            if (bytes.Length > DesktopPreferencesStore.MaximumBytes) throw new InvalidDataException("設定檔超過限制。");
            if (!StorageProvider.CanSave) { SetNote("此環境沒有可用的儲存對話框，設定未匯出。", true); return; }
            using var file = await StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "匯出目前 AI 設定", SuggestedFileName = "lala-ai-settings.json", DefaultExtension = "json", ShowOverwritePrompt = true,
                FileTypeChoices = [new FilePickerFileType("AI 設定") { Patterns = ["*.json"] }]
            });
            if (file is null || closed) return;
            EnsureCurrent();
            await using var stream = await file.OpenWriteAsync();
            if (stream.CanSeek) stream.SetLength(0);
            await stream.WriteAsync(bytes, lifetime.Token);
            await stream.FlushAsync(lifetime.Token);
            if (!closed) SetNote("已匯出目前草稿；未套用或啟動 AI。");
        }
        catch (OperationCanceledException) { }
        catch (Exception error) when (SettingsFiles.IsExpected(error))
        {
            if (!closed) SetNote("設定未能完整匯出；請檢查檔案位置與寫入權限。草稿仍保留。", true);
        }
        finally { SetBusy(false); }
    }
}

internal static class SettingsFiles
{
    public static bool IsExpected(Exception error) => error is IOException or InvalidDataException or UnauthorizedAccessException
        or JsonException or ArgumentException or InvalidOperationException or NotSupportedException;

    public static async Task<string> ReadBoundedAsync(Stream stream, CancellationToken cancellation)
    {
        using var bytes = new MemoryStream();
        var buffer = new byte[4096];
        int count;
        while ((count = await stream.ReadAsync(buffer, cancellation)) != 0)
        {
            if (bytes.Length + count > DesktopPreferencesStore.MaximumBytes) throw new InvalidDataException("設定檔超過限制。");
            bytes.Write(buffer, 0, count);
        }
        return new UTF8Encoding(false, true).GetString(bytes.ToArray()).TrimStart('\ufeff');
    }
}

internal sealed class SettingsItemSlotWindow : DesktopWindow
{
    public SettingsItemSlotWindow(string title, string current) : base("選擇" + title, 720, 520)
    {
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,*,Auto,Auto"), RowSpacing = 10 };
        Ui.At(body, Ui.Text("選擇" + title, 22, bold: true), 0);
        Ui.At(body, Ui.Text("目前指定：" + current), 0, 1);
        var table = new TextTable(["物品名稱", "可用數量", "已核對效果／用途"], "*,100,190");
        table.SetRows([], "物品效果與用途尚未核對，目前沒有可選物品。");
        Ui.At(body, table, 0, 2);
        Ui.At(body, Ui.Text("已匯入的物品 ID 可保留或清除；目前不會選取、使用、販售或丟棄物品。", 12, Ui.Muted), 0, 3);
        Ui.At(body, Ui.Row(Ui.Button("清除此格", () => Close(true)), Ui.Button("取消", () => Close(false))), 0, 4);
        SetBody(body);
    }
}
