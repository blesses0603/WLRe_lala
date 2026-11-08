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

    public NavigationWindow(DesktopSession session) : base("官方資料庫導航預覽", 640, 520)
    {
        this.session = session;
        Name = "NavigationWindow";
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto,Auto,*") };
        Ui.At(body, Ui.Text("讀取官方導航資料庫；預覽不會移動角色。"), 0);
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
            Ui.Unavailable("同步此地圖並預覽", "NavigationSyncPreview", "官方導航下載與資料庫尚未接入。"));
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
        session.Changed += Changed;
        Closed += (_, _) => { closed = true; session.Changed -= Changed; };
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
        var view = session.ReadView();
        var player = view.Snapshot.Player;
        // Unrelated receive updates must not erase coordinates currently being typed.
        if (seenGeneration == view.Generation && seenScene == player?.Scene && seenRole == player?.RoleId) return;
        output.Text = "";
        status.Text = "角色或地圖資料已變更；請重新確認起終點。";
        FillCurrentPosition(view);
    });

    private void Preview()
    {
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
        mapping.Text = session.ReadView().Labels.Scene(mapId) + "｜尚未取得同版地圖對應及導航資料。";
        status.Text = "輸入格式正確；尚未接入官方導航資料庫，無法產生路線。";
        // Do not echo plausible-looking waypoint lists or imply a successful route from field validation.
    }
}
