using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace Lala.Desktop;

/// <summary>Compact original map layout. A missing map image never becomes a fabricated map.</summary>
public sealed class MapView : UserControl
{
    private readonly DesktopSession session;
    private readonly TextBlock title = Ui.Text("小地圖｜等待角色地圖", 14, bold: true);
    private readonly TextBlock position = Ui.Text("等待角色地圖同步…", 12, Ui.Muted);
    private readonly TextBlock mapMessage = Ui.Text("尚未同步小地圖", 14, Ui.Muted);
    private readonly TextBlock navigationStatus = Ui.Text("導航：等待目前地圖。", 11, Ui.Muted);
    private bool subscribed;

    public MapView(DesktopSession session, Action openNavigation)
    {
        this.session = session;
        Name = "MapView";
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto"), Margin = new Thickness(6, 4) };
        title.Name = "MapTitle";
        title.TextWrapping = TextWrapping.NoWrap;
        title.TextTrimming = TextTrimming.CharacterEllipsis;
        title.Margin = new Thickness(0, 0, 0, 4);
        Ui.At(body, title, 0);

        var content = new Grid { ColumnDefinitions = new ColumnDefinitions("125,*") };
        var sidebar = new Grid { RowDefinitions = new RowDefinitions("*,Auto,Auto"), Margin = new Thickness(0, 0, 6, 0) };
        var portals = Ui.Text("等待傳點資料。", 11, Ui.Muted);
        portals.Margin = new Thickness(4);
        var monsters = Ui.Text("等待怪物資料。", 11, Ui.Muted);
        monsters.Margin = new Thickness(4);
        var npc = new Grid { RowDefinitions = new RowDefinitions("*,Auto,Auto") };
        Ui.At(npc, Ui.Text("等待 NPC 資料。", 11, Ui.Muted), 0);
        var npcButtons = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*") };
        var interact = Ui.Unavailable("互動", "MapNpcInteract");
        var next = Ui.Unavailable("接續", "MapNpcContinue");
        foreach (var button in new[] { interact, next })
        {
            button.Padding = new Thickness(3, 2);
            button.FontSize = 11;
            button.HorizontalAlignment = HorizontalAlignment.Stretch;
        }
        Ui.At(npcButtons, interact, 0);
        Ui.At(npcButtons, next, 1);
        Ui.At(npc, npcButtons, 0, 1);
        var more = Ui.Unavailable("更多操作", "MapNpcMore");
        more.FontSize = 11;
        more.Padding = new Thickness(3, 2);
        more.HorizontalAlignment = HorizontalAlignment.Stretch;
        Ui.At(npc, more, 0, 2);
        var lists = Ui.Tabs(("傳點", portals), ("NPC", npc), ("怪物", monsters));
        lists.Name = "MapLists";
        // These three labels fit the legacy 125px sidebar without a horizontal tab scroller.
        foreach (var item in ((IEnumerable<TabItem>)lists.ItemsSource!))
        {
            item.Padding = new Thickness(4, 4);
            item.FontSize = 11;
        }
        Ui.At(sidebar, lists, 0);
        var audit = Ui.Button("逐圖核對", () =>
            navigationStatus.Text = "逐圖核對：尚未同步同版小地圖與入口資料。", "MapAudit");
        audit.FontSize = 11;
        audit.Padding = new Thickness(3, 2);
        audit.HorizontalAlignment = HorizontalAlignment.Stretch;
        Ui.At(sidebar, audit, 0, 1);
        var change = Ui.Unavailable("直接嘗試換圖", "MapPortalGo");
        change.FontSize = 11;
        change.Padding = new Thickness(3, 2);
        change.HorizontalAlignment = HorizontalAlignment.Stretch;
        Ui.At(sidebar, change, 0, 2);
        Ui.At(content, sidebar, 0);

        mapMessage.Name = "MapEmptyState";
        mapMessage.TextAlignment = TextAlignment.Center;
        position.Name = "MapPosition";
        position.TextAlignment = TextAlignment.Center;
        var missing = Ui.Column(mapMessage, position);
        missing.HorizontalAlignment = HorizontalAlignment.Stretch;
        missing.VerticalAlignment = VerticalAlignment.Center;
        var map = new Border
        {
            Name = "MapSurface", Background = Brush.Parse("#18232c"), Padding = new Thickness(8),
            BorderBrush = Ui.BorderBrush, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(4), Child = missing
        };
        ToolTip.SetTip(map, "取得同版小地圖與座標轉換資料後，才可在圖上顯示位置與選取目的地。");
        Ui.At(content, map, 1);
        Ui.At(body, content, 0, 1);

        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*,*"), Margin = new Thickness(0, 4, 0, 0) };
        var preview = Ui.Button("導航預覽", openNavigation, "MapOpenNavigation");
        var sync = Ui.Unavailable("同步導航", "MapSyncNavigation");
        var cancel = Ui.Unavailable("取消同步", "MapCancelSync", "目前沒有執行中的導航同步。");
        var buttons = new[] { preview, sync, cancel };
        for (int i = 0; i < buttons.Length; i++)
        {
            buttons[i].FontSize = 12;
            buttons[i].Padding = new Thickness(3, 2);
            buttons[i].HorizontalAlignment = HorizontalAlignment.Stretch;
            Ui.At(actions, buttons[i], i);
        }
        Ui.At(body, actions, 0, 2);
        navigationStatus.Name = "MapNavigationStatus";
        navigationStatus.Margin = new Thickness(0, 3, 0, 0);
        Ui.At(body, navigationStatus, 0, 3);
        Content = new Border
        {
            Name = "MapFrame", Background = Ui.Panel, BorderBrush = Ui.BorderBrush,
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(7), Child = body
        };
        AttachedToVisualTree += (_, _) => Subscribe();
        DetachedFromVisualTree += (_, _) => Unsubscribe();
        Refresh();
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

    private void Refresh()
    {
        var view = session.ReadView();
        var world = view.Snapshot.Local.World;
        var player = world.Player;
        title.Text = player is null ? "小地圖｜等待角色地圖" : "小地圖｜" + view.Labels.Scene(player.Scene);
        ToolTip.SetTip(title, title.Text);
        mapMessage.Text = player is null ? "尚未同步小地圖" : "此地圖的同版圖片\n尚未同步";
        var confirmed = world.Location.Confirmed;
        position.Text = player is not null && world.Location.ConfirmedIsCurrent && confirmed?.Scene == player.Scene
            ? $"已確認座標\n{confirmed.X}, {confirmed.Y}" : "等待角色位置同步…";
        navigationStatus.Text = player is null ? "導航：等待目前地圖。" : "導航：等待同版地圖與導航資料。";
    }
}
