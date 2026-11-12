using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace Lala.Desktop;

/// <summary>Read-only navigation form. Valid coordinates alone cannot produce an authorised route.</summary>
public sealed class NavigationWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly TextBox scene = new() { Name = "NavigationSceneId" };
    private readonly TextBox startX = new() { Name = "NavigationStartX" };
    private readonly TextBox startY = new() { Name = "NavigationStartY" };
    private readonly TextBox endX = new() { Name = "NavigationEndX" };
    private readonly TextBox endY = new() { Name = "NavigationEndY" };
    private readonly ComboBox mode = Ui.Combo(["步行", "海上", "飛行"], name: "NavigationTravelMode");
    private readonly CheckBox smooth = new() { Content = "平面走廊平滑（斜坡會拒絕）", Name = "NavigationSmooth" };
    private readonly TextBlock mapping = Ui.Text("請先完成官方資料同步。", 12, Ui.Muted);
    private readonly TextBlock status = Ui.Text("填寫起終點後可檢查輸入；尚未取得導航資料。", 12, Ui.Muted);
    private readonly TextBox output = new()
    {
        Name = "NavigationOutput", IsReadOnly = true, AcceptsReturn = true,
        TextWrapping = TextWrapping.Wrap, MinHeight = 65, Background = Ui.Panel
    };
    private bool closed;
    private long seenGeneration;
    private ushort? seenScene;
    private uint? seenRole;
    private CancellationTokenSource? planning;
    private readonly Button syncButton, startButton, stopButton;

    public NavigationWindow(DesktopSession session) : base("官方資料庫導航預覽", 640, 520)
    {
        this.session = session;
        Name = "NavigationWindow";
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto,Auto,*") };
        Ui.At(body, Ui.Text("預覽路線後可開始步行導航；起點使用目前同步或本機推算位置。"), 0);
        startX.IsReadOnly = startY.IsReadOnly = true;
        var fields = new Grid { ColumnDefinitions = new ColumnDefinitions("100,*"), RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto"), Margin = new Thickness(0, 6) };
        var entries = new (string Label, TextBox Field)[]
        {
            ("地圖 ID", scene), ("起點 X", startX), ("起點 Y", startY), ("終點 X", endX), ("終點 Y", endY)
        };
        for (int i = 0; i < entries.Length; i++)
        {
            Ui.At(fields, Ui.Text(entries[i].Label), 0, i);
            entries[i].Field.Margin = new Thickness(0, 1);
            Ui.At(fields, entries[i].Field, 1, i);
        }
        Ui.At(body, fields, 0, 1);
        mapping.Name = "NavigationMapping";
        Ui.At(body, mapping, 0, 2);
        Ui.At(body, Ui.Column(mode, smooth), 0, 3);
        var actions = Ui.Row(Ui.Button("從資料庫預覽", Preview, "NavigationPreview"),
            syncButton = Ui.Button("同步此地圖並預覽", () => _ = PlanAsync(true), "NavigationSyncPreview"),
            startButton = Ui.Button("開始導航", () => _ = PlanAsync(true, true), "NavigationStart"),
            stopButton = Ui.Button("停止", async () => { planning?.Cancel(); await session.StopNavigationAsync(); }, "NavigationStop"));
        actions.Margin = new Thickness(0, 4);
        Ui.At(body, actions, 0, 4);
        status.Name = "NavigationStatus";
        status.Margin = new Thickness(0, 0, 0, 4);
        Ui.At(body, status, 0, 5);
        Ui.At(body, output, 0, 6);
        SetBody(new ScrollViewer
        {
            Content = body,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto
        });
        FillCurrentPosition();
        RefreshActions();
        session.Changed += Changed;
        Closed += (_, _) => { closed = true; planning?.Cancel(); session.Changed -= Changed; };
    }

    private void FillCurrentPosition(DesktopPublication? publication = null)
    {
        var view = publication ?? session.ReadView();
        var world = view.Snapshot.Local.World;
        seenGeneration = view.Generation;
        seenScene = world.Player?.Scene;
        seenRole = world.Player?.RoleId;
        scene.Text = world.Player?.Scene.ToString(CultureInfo.InvariantCulture) ?? "";
        var confirmed = world.Location.Confirmed;
        if (world.Player is not null && world.Location.ConfirmedIsCurrent && confirmed?.Scene == world.Player.Scene)
        {
            startX.Text = endX.Text = confirmed.X.ToString(CultureInfo.InvariantCulture);
            startY.Text = endY.Text = confirmed.Y.ToString(CultureInfo.InvariantCulture);
        }
        else startX.Text = startY.Text = endX.Text = endY.Text = "";
        mapping.Text = world.Player is null ? "等待角色地圖與官方資料同步。"
            : view.Labels.Scene(world.Player.Scene) + "｜尚未取得同版地圖對應及導航資料。";
    }

    private void Changed() => Ui.OnUi(() =>
    {
        if (closed) return;
        RefreshActions();
        var view = session.ReadView();
        var player = view.Snapshot.Player;
        // Unrelated receive updates must not erase coordinates currently being typed.
        if (seenGeneration == view.Generation && seenScene == player?.Scene && seenRole == player?.RoleId) return;
        output.Text = "";
        status.Text = "角色或地圖資料已變更；請重新確認起終點。";
        FillCurrentPosition(view);
    });

    private void Preview() => _ = PlanAsync(false);
    private void RefreshActions()
    {
        syncButton.IsEnabled = startButton.IsEnabled = session.CanSendGameCommands && planning is null;
        stopButton.IsEnabled = planning is not null || session.NavigationStatus.Running;
    }
    private async Task PlanAsync(bool synchronize, bool execute = false)
    {
        planning?.Cancel();
        output.Text = "";
        if (!ushort.TryParse(scene.Text, NumberStyles.None, CultureInfo.InvariantCulture, out var mapId) || mapId == 0)
        {
            status.Text = "請輸入 1～65535 的地圖 ID。";
            scene.Focus();
            return;
        }
        foreach (var (label, field) in new[] { ("起點 X", startX), ("起點 Y", startY), ("終點 X", endX), ("終點 Y", endY) })
        {
            if (!double.TryParse(field.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) ||
                !double.IsFinite(value) || value < 0 || value > ushort.MaxValue)
            {
                status.Text = label + " 請輸入 0～65535 的有限數值。";
                field.Focus();
                return;
            }
        }
        using var cancellation = new CancellationTokenSource(); planning = cancellation; RefreshActions();
        try
        {
            if (!ushort.TryParse(endX.Text, out var x) || !ushort.TryParse(endY.Text, out var y)) throw new InvalidOperationException("執行目的地請輸入 0～65535 的整數。");
            var target = new Lala.Core.Gameplay.GameNavigationTarget(mapId, x, y, synchronize, mode.SelectedIndex switch { 1 => "sea", 2 => "sky", _ => "land" }, smooth.IsChecked == true);
            if (session.Snapshot.Player?.Scene is {} current && current != mapId)
            {
                var catalog = session.Catalogs ?? throw new InvalidOperationException("同版圖資尚未就緒。");
                var legs = Lala.Core.Gameplay.GameTravelPlanner.Plan(catalog, current, mapId);
                output.Text = string.Join("\n", legs.Select((leg, index) => $"{index + 1}. {session.ReadView().Labels.Scene(leg.Scene)} → 出口 {leg.Door} ({leg.X}, {leg.Y}) → {session.ReadView().Labels.Scene(leg.Destination)}"));
                status.Text = "跨圖行程已列出；各段步行路線會在抵達該地圖後核對。";
                if (execute) { await session.NavigateAsync(target, cancellation.Token); if (!closed) status.Text = session.NavigationStatus.Message; }
                return;
            }
            status.Text = synchronize ? "同步並規劃官方導航資料…" : "讀取導航快取並規劃…";
            var route = await session.PreviewNavigationAsync(target, cancellation.Token);
            if (closed || cancellation.IsCancellationRequested || !route.IsCurrent) return;
            mapping.Text = session.ReadView().Labels.Scene(mapId) + $"｜同版官方導航網格｜{route.Points.Length} 點";
            output.Text = string.Join("\n", route.Points.Select((point, index) => $"{index + 1}. ({point.X:0.##}, {point.Y:0.##})"));
            status.Text = "路線預覽完成；按開始導航才會移動角色。";
            if (execute) { status.Text = "導航執行中…"; await session.NavigateAsync(target, cancellation.Token); if (!closed) status.Text = session.NavigationStatus.Message; }
        }
        catch (OperationCanceledException) { if (!closed) status.Text = "已取消導航工作。"; }
        catch (Exception error) when (error is IOException or ArgumentException or InvalidOperationException or Lala.Core.Protocol.ProtocolException)
        { if (!closed) status.Text = error.Message; }
        finally { if (ReferenceEquals(planning, cancellation)) planning = null; if (!closed) RefreshActions(); }
    }
}
