using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using ProgressBar = Avalonia.Controls.ProgressBar;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private Control CompanionsPage()
    {
        var companions = Column(7);
        int[] hp = [42580, 38910, 33200], sp = [7820, 6540, 5980];
        for (int i = 0; i < 3; i++)
        {
            int id = i; int mode = state.CompanionModes[i];
            var name = Sides(Label($"Lv.{60 - i * 2}  lalaplayer{i + 1:00}", 12, Ink, true), Pill(new[] { "出戰中", "待命中", "休息中" }[mode], mode == 0 ? "sword" : "clock", mode == 0 ? Green : Muted));
            var stats = Column(5, name,
                CompactStat("HP", hp[i].ToString("N0") + " / " + hp[i].ToString("N0"), Green, 100),
                CompactStat("SP", sp[i].ToString("N0") + " / " + sp[i].ToString("N0"), Accent, 100),
                CompactStat("好感 Lv." + (8 - i), $"{2360 - i * 400:N0} / 3,000", Brush.Parse("#E79CDB"), 78 - i * 9));
            var identity = Sides(Portrait(i, 48), stats, "50,*", 8);
            var actions = Column(6,
                ActionButton("設為出戰", "sword", () => { state.CompanionModes[id] = 0; AddEvent("預覽夥伴出戰"); ShowPage(8); }, true, true),
                ActionButton("讓夥伴休息", "coffee", () => { state.CompanionModes[id] = 2; AddEvent("預覽夥伴休息"); ShowPage(8); }, compact: true));
            companions.Children.Add(Surface(AdaptiveSides(identity, actions, "*,100", 330), new(9), 11, false));
        }
        var points = Label("", 13, Accent, true); var values = new List<TextBlock>(); var meters = new List<ProgressBar>();
        void RefreshPoints()
        {
            points.Text = "可分配點數  " + (state.AttributePoints - state.AttributeDraft.Sum());
            for (int i = 0; i < values.Count; i++) { values[i].Text = $"{state.Attributes[i] + state.AttributeDraft[i]}  (+{state.AttributeDraft[i]})"; meters[i].Value = state.Attributes[i] + state.AttributeDraft[i]; }
        }
        var attributes = Column(7);
        var names = new[] { ("力量", "sword"), ("體質", "shield"), ("敏捷", "walk"), ("智力", "file") };
        for (int i = 0; i < names.Length; i++)
        {
            int id = i; var (name, icon) = names[i]; var value = Label("", 11); values.Add(value);
            var meter = new ProgressBar { Maximum = 180, Height = 7, Foreground = Accent, Background = Brush.Parse("#20394E") }; meters.Add(meter);
            var minus = IconButton("minus", "減少" + name, () => { if (state.AttributeDraft[id] > 0) state.AttributeDraft[id]--; RefreshPoints(); }, 28);
            var plus = IconButton("plus", "增加" + name, () => { if (state.AttributePoints > state.AttributeDraft.Sum()) state.AttributeDraft[id]++; else Toast("可分配點數已用完。"); RefreshPoints(); }, 28);
            attributes.Children.Add(Surface(Sides(Row(6, new NeonIcon(icon, Accent, 17), Label(name, 11)),
                Sides(Column(5, value, meter), Row(5, minus, plus), "*,61", 8), "49,*", 7), new(8), 8, false));
        }
        RefreshPoints();
        return Page(FeatureMenu(), Card("夥伴出戰", "users", Label("選擇出戰夥伴並管理狀態（範例）", 10, Muted), companions,
                Row(7, new NeonIcon("users", Accent, 16), Pill("出戰編組  " + state.CompanionModes.Count(x => x == 0) + " / 3", "check", Accent))),
            Card("角色能力", "chart", points, Label("按 + / − 預覽配點，確認後套用至本次預覽。", 10, Muted), attributes,
                ActionButton("分配屬性", "star", () =>
                {
                    int spent = state.AttributeDraft.Sum(); if (spent == 0) { Toast("請先選擇要增加的屬性點數。"); return; }
                    for (int i = 0; i < 4; i++) { state.Attributes[i] += state.AttributeDraft[i]; state.AttributeDraft[i] = 0; }
                    state.AttributePoints -= spent; RefreshPoints(); AddEvent("預覽分配屬性 " + spent + " 點"); Toast("已套用本次預覽配點，未修改遊戲角色。");
                }, true),
                ActionButton("重置屬性", "refresh", () => { int[] defaults = [102, 98, 110, 120]; for (int i = 0; i < 4; i++) { state.Attributes[i] = defaults[i]; state.AttributeDraft[i] = 0; } state.AttributePoints = 12; RefreshPoints(); Toast("已還原範例配點，未消耗重置券。"); }, compact: true)));
    }
    private static Control CompactStat(string name, string text, IBrush brush, double percent) => Column(2,
        Sides(Label(name, 9, Muted), Label(text, 8)), new ProgressBar { Minimum = 0, Maximum = 100, Value = percent, MinWidth = 0, Height = 4, Foreground = brush });
}
