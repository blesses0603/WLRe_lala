using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private Control MapPage()
    {
        var x = Input("X"); x.Text = state.TargetX.ToString(); x.MinWidth = 0;
        var y = Input("Y"); y.Text = state.TargetY.ToString(); y.MinWidth = 0;
        var selected = Label($"目的地（{state.TargetX}, {state.TargetY}）", 10, Gold);
        var feedback = Label(state.MapFeedback, 10, Accent);
        var map = new PreviewMapArtwork(Asset("town-preview.png"), state, true);
        map.TargetChanged = (targetX, targetY) =>
        {
            x.Text = targetX.ToString(); y.Text = targetY.ToString(); selected.Text = $"目的地（{targetX}, {targetY}）";
            state.MapFeedback = "已選取範例目的地，路線僅供視覺預覽。";
            feedback.Text = state.MapFeedback;
        };
        var mapFrame = new Grid { ClipToBounds = true };
        mapFrame.Children.Add(map);
        var overlays = new Grid { Margin = new(8), IsHitTestVisible = false, RowDefinitions = new("Auto,*,Auto") };
        overlays.Children.Add(Sides(Pill("城鎮示意圖", "map", Accent), Label("N ↑", 14, Ink, true)));
        var legend = Sides(Pill("我 (156, 87)", "pin", Accent), Pill("已選目的地", "pin", Gold)); Grid.SetRow(legend, 2); overlays.Children.Add(legend); mapFrame.Children.Add(overlays);
        var zoom = Column(4, IconButton("plus", "放大地圖", () => { map.Zoom = Math.Min(2.5, map.Zoom + .25); map.InvalidateVisual(); }),
            IconButton("minus", "縮小地圖", () => { map.Zoom = Math.Max(1, map.Zoom - .25); map.InvalidateVisual(); }),
            IconButton("target", "回到目前位置", () => { state.TargetX = 156; state.TargetY = 87; x.Text = "156"; y.Text = "87"; selected.Text = "目的地（156, 87）"; map.Zoom = 1; map.InvalidateVisual(); }));
        zoom.HorizontalAlignment = HorizontalAlignment.Right; zoom.VerticalAlignment = VerticalAlignment.Center; zoom.Margin = new(0, 0, 7, 0); mapFrame.Children.Add(zoom);
        void SetTarget(int targetX, int targetY)
        {
            state.TargetX = targetX; state.TargetY = targetY; x.Text = targetX.ToString(); y.Text = targetY.ToString();
            selected.Text = $"目的地（{targetX}, {targetY}）"; map.InvalidateVisual(); feedback.Text = "已選取目的地，尚未移動角色。";
        }
        void PreviewRoute(string mode)
        {
            if (!int.TryParse(x.Text, out int targetX) || !int.TryParse(y.Text, out int targetY) || targetX is < 0 or > 320 || targetY is < 0 or > 200)
            { Toast("請輸入示意圖範圍：X 0–320、Y 0–200。"); return; }
            SetTarget(targetX, targetY); state.MapFeedback = mode + $"至 ({targetX}, {targetY})：路線示範，未傳送移動指令。";
            feedback.Text = state.MapFeedback; AddEvent(state.MapFeedback); Toast(state.MapFeedback);
        }
        var nearby = Column(0);
        foreach (var (name, subtitle, distance, targetX, targetY) in new[] { ("卡普拉職員", "卡普拉服務", "12 格", 182, 62), ("道具商人", "雜貨 / 補給", "18 格", 62, 92), ("南門出口", "前往南普隆德拉", "26 格", 160, 180) })
        {
            nearby.Children.Add(ActionButton(name + " · " + subtitle + "   " + distance, "pin", () => SetTarget(targetX, targetY), compact: true));
        }
        return Page(HomeTabs(6), Card("小地圖", "map", Label("查看當前場景、座標與傳送位置（示意圖）", 10, Muted),
                EqualRow(6, Surface(Column(4, Label("當前場景", 9, Muted), Label("普隆德拉 城中心", 12, Ink, true)), new(8), 9, false),
                    Surface(Column(4, Label("當前座標", 9, Muted), Label("X 156, Y 87", 12, Ink, true)), new(8), 9, false)),
                Surface(mapFrame, new(0), 11), selected,
                Sides(Row(5, new NeonIcon("target", Accent, 18), Label("目標座標", 11)), EqualRow(6, x, y), "85,*"),
                ActionButton("設為目的地", "pin", () => PreviewRoute("設定目的地")),
                EqualRow(6, ActionButton("步行前往", "walk", () => PreviewRoute("步行"), compact: true),
                    ActionButton("傳送口前往", "refresh", () => PreviewRoute("傳送口"), compact: true),
                    ActionButton("直接前往", "arrow", () => PreviewRoute("直接前往"), true, true)),
                EqualRow(6, ActionButton("NPC / 出口選單", "user", () => Toast("下方可點選範例 NPC 或出口，更新目的地。"), compact: true),
                    ActionButton("逐圖核對", "map", () => Toast("目前使用城鎮示意圖；正式圖資與導航尚未接入。"), compact: true)), feedback),
            Card("附近 NPC / 出口", "pin", nearby), Label("此為設計用示意地圖與虛線，並非真實可通行路徑。", 9, Muted));
    }
}
