using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using CheckBox = Avalonia.Controls.CheckBox;
using ProgressBar = Avalonia.Controls.ProgressBar;
using Orientation = Avalonia.Layout.Orientation;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private Control ExpeditionPage()
    {
        var status = Label(state.ExpeditionRunning ? "● 示範派遣中" : "● 尚未啟動", 11, state.ExpeditionRunning ? Green : Muted);
        var taskRows = Column(3);
        var sorting = Combo("依推薦度排序", "依時間排序");
        string[] names = ["邊境物資護送", "魔物巢穴清剿", "野外採集支援", "遺跡遺物調查", "商隊護衛任務", "據點偵查巡邏"];
        string[] icons = ["shield", "sword", "star", "flask", "bag", "map"];
        int[] minutes = [60, 120, 30, 180, 240, 360];
        void BuildTasks()
        {
            taskRows.Children.Clear();
            var order = sorting.SelectedIndex == 1 ? Enumerable.Range(0, 6).OrderBy(i => minutes[i]).ToArray() : Enumerable.Range(0, 6).ToArray();
            foreach (int id in order)
            {
                var check = new CheckBox { IsChecked = state.ExpeditionTasks[id], MinHeight = 30, Padding = new(0) };
                Avalonia.Automation.AutomationProperties.SetName(check, "派遣任務 " + names[id]);
                check.IsCheckedChanged += (_, _) => state.ExpeditionTasks[id] = check.IsChecked == true;
                taskRows.Children.Add(Surface(Sides(Row(5, check, new NeonIcon(icons[id], id < 2 ? Gold : Accent, 16), Label(names[id], 11)),
                    Column(2, Label(TimeSpan.FromMinutes(minutes[id]).ToString(@"hh\:mm\:ss"), 9), Label("信仰 " + minutes[id] / 2, 8, Muted)), "*,60", 5), new(6, 2), 7, false));
            }
        }
        sorting.SelectionChanged += (_, _) => BuildTasks(); BuildTasks();
        var affinity = new ProgressBar { Maximum = 100, Value = state.ExpeditionAffinity, MinWidth = 0, Height = 6, Foreground = Accent };
        var affinityText = Label(state.ExpeditionAffinity + ".0%", 9, Muted);
        var npc = Surface(AdaptiveSides(Sides(Portrait(1, 41), Column(4, Label("艾莉亞（遠征管理員）", 11, Ink, true), affinityText, affinity), "43,*", 7),
            ActionButton("贈送禮物", "star", () => { state.ExpeditionAffinity = Math.Min(100, state.ExpeditionAffinity + 5); affinity.Value = state.ExpeditionAffinity; affinityText.Text = state.ExpeditionAffinity + ".0%"; Toast("已展示好感度變化，未消耗物品或送出禮物。"); }, compact: true), "*,102", 300), new(8), 10, false);
        var dungeon = new ContentControl();
        void RefreshDungeon() => dungeon.Content = DungeonCard(RefreshDungeon);
        RefreshDungeon();
        return Page(FeatureMenu(), Card("遠征（自動派遣）", "flag", Label("自動遠征流程與任務選擇預覽", 10, Muted),
                Surface(EqualRow(5, Column(4, Label("遠征狀態", 9, Muted), status), Column(4, Label("啟用隊伍", 9, Muted), Label("2 / 3 隊", 12, Ink, true)),
                    Column(4, Label("下次派遣", 9, Muted), Label("00:12:36", 11, Accent)), Column(4, Label("本輪結束", 9, Muted), Label("02:47:21", 11, Accent))), new(8), 10, false), npc,
                Sides(Label("可派遣任務（6）", 13, Ink, true), sorting, "*,135"), taskRows,
                EqualRow(5, ActionButton("儲存設定", "save", () => { state.SavedExpeditionTasks = state.ExpeditionTasks.ToArray(); Toast("已保存本次預覽的任務選擇，重啟後會還原。"); }, compact: true),
                    ActionButton("還原預設", "refresh", () => { for (int i = 0; i < 6; i++) state.ExpeditionTasks[i] = i < 2; BuildTasks(); }, compact: true)),
                EqualRow(6, ActionButton("停止派遣", "stop", () => { state.ExpeditionRunning = false; status.Text = "● 尚未啟動"; status.Foreground = Muted; AddEvent("停止遠征示範"); }, compact: true),
                    ActionButton("開始派遣", "play", () =>
                    {
                        if (!state.ExpeditionTasks.Any(x => x)) { Toast("請至少勾選一項範例任務。"); return; }
                        state.ExpeditionRunning = true; status.Text = "● 示範派遣中"; status.Foreground = Green; AddEvent("開始遠征示範"); Toast("已切換派遣樣式，未啟動遊戲遠征。");
                    }, true, true))), dungeon,
            Label("遠征時間、任務、NPC 與副本均為範例資料；不會執行派遣、領獎或建立正式房間。", 9, Muted));
    }
    private Control DungeonCard(Action refresh)
    {
        var roomChoices = new ContentControl();
        var portraits = new WrapPanel { Orientation = Orientation.Horizontal };
        for (int i = 0; i < state.RoomMembers; i++) { var avatar = Portrait(i, 26); avatar.Margin = new(0, 0, 5, 4); portraits.Children.Add(avatar); }
        portraits.Children.Add(IconButton("plus", "新增範例副本成員", () => { if (state.RoomMembers < 6) state.RoomMembers++; refresh(); }, 26));
        var autoReward = Switch(state.AutoReward, value => state.AutoReward = value);
        return Card("副本資料（副本 / 協力）", "layers",
            Surface(EqualRow(6, Column(3, Label("房間總數", 9, Muted), Label("128（範例）", 12)),
                Column(3, Label("目前所在房間", 9, Muted), Label(state.RoomCreated ? "S1 · PREVIEW-01" : "尚未加入", 10, Accent)),
                Column(3, Label("當前成員", 9, Muted), Label(state.RoomMembers + " / 6", 12))), new(8), 10, false),
            Surface(EqualRow(9, Column(5, Label("深淵遺跡 · 第 3 層", 12, Ink, true), Label("建議等級 Lv.120+\n建議人數 1–6\n預估時間 08:00", 9, Muted),
                    Pill(state.DungeonRunning ? "示範進行中" : "範例副本", "layers", Accent)), Column(7, Label("房間成員", 10, Muted), portraits)), new(9), 10, false),
            Sides(Row(6, new NeonIcon("star", Accent, 18), Label("自動領取免費協力獎勵", 11)), autoReward),
            EqualRow(6, ActionButton("搜尋副本清單", "search", () =>
                {
                    roomChoices.Content = Column(6, Label("可加入的範例房間", 11, Accent),
                        ActionButton("深淵遺跡 · 普通（4/6）", "users", () => { state.RoomCreated = true; state.RoomMembers = 4; refresh(); Toast("已加入範例房間，未連線遊戲。"); }, compact: true),
                        ActionButton("星穹試煉 · 協力（2/6）", "users", () => { state.RoomCreated = true; state.RoomMembers = 2; refresh(); }, compact: true));
                    Dispatcher.UIThread.Post(() => roomChoices.BringIntoView(), DispatcherPriority.Loaded);
                }, compact: true), ActionButton("查詢伺服器房間", "db", () => Toast("目前僅展示範例房間，不會向官方伺服器發送查詢。"), compact: true)), roomChoices,
            EqualRow(6, ActionButton("建立房間", "plus", () => { state.RoomCreated = true; state.DungeonRunning = false; refresh(); AddEvent("建立範例副本房間"); Toast("已建立本機範例房間，未送出遊戲封包。"); }, compact: true),
                ActionButton("開始副本", "play", () => { if (!state.RoomCreated) { Toast("請先建立或加入範例房間。"); return; } state.DungeonRunning = true; refresh(); AddEvent("開始副本示範"); }, true, true)),
            ActionButton(state.RewardClaimed ? "範例獎勵已領取" : "領取免費協力獎勵", "star", () =>
            {
                if (state.RewardClaimed) { Toast("範例獎勵已標記領取。"); return; } state.RewardClaimed = true; refresh(); Toast("已展示領獎狀態，沒有取得真實獎勵。");
            }, compact: true));
    }
}
