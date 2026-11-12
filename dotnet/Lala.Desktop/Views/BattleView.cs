using System.Globalization;
using System.Numerics;
using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Lala.Core.Battle;

namespace Lala.Desktop;

/// <summary>The original packet-slot formation. Selecting a card never sends a command.</summary>
public sealed class BattleView : UserControl
{
    private readonly DesktopSession session;
    private readonly Dictionary<BattleSlot, Cell> cells = [];
    private readonly TextBlock note = Ui.Text("尚無戰鬥資料。\n左右各八格依封包位置排列。", 12, Ui.Muted);
    private Selection? actor;
    private Selection? target;
    private long generation;
    private BigInteger battleCount;
    private bool subscribed;

    public BattleView(DesktopSession session)
    {
        this.session = session;
        Name = "BattleView";
        var body = new Grid { RowDefinitions = new RowDefinitions("*,Auto"), Margin = new Thickness(4) };
        var formation = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,*,22,*,*"),
            RowDefinitions = new RowDefinitions("*,*,*,*"), Background = Ui.Background
        };
        var versus = Ui.Text("VS", 14, Brush.Parse("#d16d3c"), true);
        versus.HorizontalAlignment = HorizontalAlignment.Center;
        Ui.At(formation, versus, 2, rowSpan: 4);
        for (byte col = 1; col <= 4; col++)
        {
            for (byte row = 1; row <= 4; row++)
            {
                var slot = new BattleSlot(col, row);
                var cell = new Cell(slot, () => SelectSlot(slot));
                cell.Button.PointerEntered += (_, _) => ShowUnit(slot);
                cell.Button.PointerExited += (_, _) => UpdateNote();
                cells.Add(slot, cell);
                Ui.At(formation, cell.Frame, col <= 2 ? col - 1 : col, row - 1);
            }
        }
        Ui.At(body, formation, 0);
        note.Name = "BattleSelectionNote";
        note.MinHeight = 38;
        note.Margin = new Thickness(2, 4, 2, 0);
        Ui.At(body, note, 0, 1);
        Content = body;
        AttachedToVisualTree += (_, _) => Subscribe();
        DetachedFromVisualTree += (_, _) => Unsubscribe();
        Refresh();
    }

    public string? SelectedActorKey => actor?.Slot.ToString();
    public string? SelectedTargetKey => target?.Slot.ToString();

    public void SelectSlot(BattleSlot slot)
    {
        // Re-read the current publication: a click queued before an update must not select an old occupant.
        var view = session.ReadView();
        Refresh(view);
        var state = view.Snapshot;
        var unit = state.Local.Battle.UnitAt(slot);
        if (unit is null || unit.Hp == 0 || unit.Exited || !cells.ContainsKey(slot)) return;
        var selection = Selection.Of(unit);
        if (Owned(unit, state.Player?.RoleId)) actor = selection;
        else target = selection;
        UpdateFrames();
        ShowUnit(slot);
    }

    private void Subscribe()
    {
        if (subscribed) return;
        subscribed = true;
        session.Changed += Changed;
        Refresh();
    }

    private void Unsubscribe()
    {
        if (!subscribed) return;
        subscribed = false;
        session.Changed -= Changed;
    }

    private void Changed() => Ui.OnUi(() => { if (subscribed) Refresh(); });

    private void Refresh(DesktopPublication? publication = null)
    {
        var view = publication ?? session.ReadView();
        var state = view.Snapshot;
        var battle = state.Local.Battle;
        if (generation != view.Generation || battleCount != battle.BattleCount)
        {
            actor = target = null;
            generation = view.Generation;
            battleCount = battle.BattleCount;
        }
        if (!StillSelected(actor, battle, true, state.Player?.RoleId)) actor = null;
        if (!StillSelected(target, battle, false, state.Player?.RoleId)) target = null;
        foreach (var (slot, cell) in cells)
        {
            var unit = battle.UnitAt(slot);
            var command = battle.CommandAt(slot)?.Status;
            cell.Render(unit, unit is not null && Owned(unit, state.Player?.RoleId), command);
        }
        UpdateFrames();
        UpdateNote(battle);
    }

    private static bool Owned(BattleUnitState unit, uint? playerId) => playerId is > 0 &&
        (unit.Layout.Pid == playerId || unit.Layout.MasterId == playerId);

    private static bool StillSelected(Selection? selection, BattleEventSnapshot battle, bool owned, uint? playerId)
    {
        if (selection is not { } old || battle.UnitAt(old.Slot) is not { } unit) return false;
        return unit.Hp > 0 && !unit.Exited && Selection.Of(unit) == old && Owned(unit, playerId) == owned;
    }

    private void UpdateFrames()
    {
        foreach (var (slot, cell) in cells)
        {
            bool isActor = actor?.Slot == slot;
            bool isTarget = target?.Slot == slot;
            cell.Frame.BorderBrush = isTarget ? Brush.Parse("#dc8740") : isActor ? Ui.Accent : Ui.BorderBrush;
            cell.Frame.BorderThickness = new Thickness(isActor || isTarget ? 3 : 1);
        }
    }

    private void UpdateNote(BattleEventSnapshot? observation = null)
    {
        var battle = observation ?? session.ReadView().Snapshot.Local.Battle;
        note.Text = battle.Units.Length == 0 ? "尚無戰鬥資料。\n左右各八格依封包位置排列。"
            : (battle.Active == true ? "戰鬥資料" : "末次戰場") +
              "｜點選卡片標示角色或目標。\n移入格子查看名稱與 HP；選取不會送出行動。";
    }

    private void ShowUnit(BattleSlot slot)
    {
        var state = session.ReadView().Snapshot;
        if (state.Local.Battle.UnitAt(slot) is not { } unit) { UpdateNote(); return; }
        var status = unit.Hp == 0 ? "已陣亡" : unit.Exited ? "已離場" :
            Owned(unit, state.Player?.RoleId) ? "角色／夥伴" : "目標";
        note.Text = $"{DisplayName(unit)}｜{slot}｜{status}\nHP {unit.Hp}/{unit.Layout.MaxHp}";
    }

    private static string DisplayName(BattleUnitState unit) =>
        string.IsNullOrEmpty(unit.Layout.Name) ? "名稱待同步" : unit.Layout.Name;

    private readonly record struct Selection(BattleSlot Slot, uint Pid, ushort NpcIndex, uint MasterId)
    {
        public static Selection Of(BattleUnitState unit) =>
            new(unit.Slot, unit.Layout.Pid, unit.Layout.NpcIndex, unit.Layout.MasterId);
    }

    private sealed class Cell
    {
        private readonly BattleSlot slot;
        private readonly TextBlock empty;
        private readonly TextBlock element = Ui.Text("", 10, Brushes.White, true);
        private readonly Border elementMark;
        private readonly TextBlock name = Ui.Text("", 11, bold: true);
        private readonly TextBlock hp = Ui.Text("", 11);
        private readonly TextBlock status = Ui.Text("", 10, Ui.Muted);
        private readonly ProgressBar health = new() { Minimum = 0, Maximum = 100, Height = 4, Background = Ui.Background };
        private readonly Grid detail;

        public Cell(BattleSlot slot, Action select)
        {
            this.slot = slot;
            empty = Ui.Text(slot + " 空位", 11, Brush.Parse("#7292a4"));
            empty.HorizontalAlignment = HorizontalAlignment.Center;
            empty.TextWrapping = TextWrapping.NoWrap;
            var content = new Grid();
            detail = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto") };
            var heading = new Grid { ColumnDefinitions = new ColumnDefinitions("17,*") };
            element.HorizontalAlignment = HorizontalAlignment.Center;
            elementMark = new Border { Width = 16, Height = 16, CornerRadius = new CornerRadius(8), Child = element };
            Ui.At(heading, elementMark, 0);
            name.TextWrapping = TextWrapping.NoWrap;
            name.TextTrimming = TextTrimming.CharacterEllipsis;
            Ui.At(heading, name, 1);
            Ui.At(detail, heading, 0);
            hp.HorizontalAlignment = HorizontalAlignment.Center;
            hp.TextWrapping = TextWrapping.NoWrap;
            hp.TextTrimming = TextTrimming.CharacterEllipsis;
            Ui.At(detail, hp, 0, 1);
            health.Margin = new Thickness(0, 2);
            Ui.At(detail, health, 0, 2);
            status.HorizontalAlignment = HorizontalAlignment.Center;
            status.TextWrapping = TextWrapping.NoWrap;
            Ui.At(detail, status, 0, 3);
            content.Children.Add(empty);
            content.Children.Add(detail);
            Button = new Button
            {
                Name = $"BattleSlot_{slot.Col}_{slot.Row}", Content = content, Background = Brushes.Transparent,
                BorderThickness = new Thickness(0), Padding = new Thickness(3),
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                VerticalContentAlignment = VerticalAlignment.Stretch
            };
            AutomationProperties.SetName(Button, "戰場位置 " + slot);
            Button.Click += (_, _) => select();
            Frame = new Border
            {
                Child = Button, Background = Brush.Parse("#183044"), BorderBrush = Ui.BorderBrush,
                BorderThickness = new Thickness(1), Margin = new Thickness(1.5)
            };
        }

        public Button Button { get; }
        public Border Frame { get; }

        public void Render(BattleUnitState? unit, bool owned, BattleCommandStatus? command)
        {
            empty.IsVisible = unit is null;
            detail.IsVisible = unit is not null;
            Button.IsEnabled = unit is { Hp: > 0, Exited: false };
            if (unit is null)
            {
                Frame.Background = Brush.Parse("#183044");
                ToolTip.SetTip(Button, slot + " 空位");
                return;
            }
            bool unavailable = unit.Hp == 0 || unit.Exited;
            Frame.Background = Brush.Parse(unavailable ? "#737c88" : "#203f53");
            var (label, color) = unit.Layout.Element switch
            {
                0 => ("無", "#8665a9"), 1 => ("地", "#b58b40"), 2 => ("水", "#3f8fc5"),
                3 => ("火", "#d36056"), 4 => ("風", "#5d9e61"), _ => ("?", "#888888")
            };
            element.Text = label;
            elementMark.Background = Brush.Parse(color);
            name.Text = DisplayName(unit);
            hp.Text = unavailable ? unit.Hp == 0 ? "已陣亡" : "已離場"
                : string.Create(CultureInfo.InvariantCulture, $"{unit.Hp}/{unit.Layout.MaxHp}");
            double percentage = 100d * unit.Hp / Math.Max(1u, unit.Layout.MaxHp);
            health.Value = Math.Clamp(percentage, 0, 100);
            health.Foreground = Brush.Parse(percentage > 30 ? "#63a45f" : "#d56b54");
            health.IsVisible = !unavailable;
            status.Text = unavailable ? "" : !owned ? "目標" : command switch
            {
                BattleCommandStatus.Resolved => "已有結果", BattleCommandStatus.Sent => "已送出", _ => "可選取"
            };
            ToolTip.SetTip(Button, $"{DisplayName(unit)}｜{slot}\nHP {unit.Hp}/{unit.Layout.MaxHp}\n只選取，不會送出行動。");
        }
    }
}
