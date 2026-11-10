using Lala.Core.Inventory;
using Avalonia.Controls;
using Avalonia.Layout;

namespace Lala.Desktop;

/// <summary>Python feature_windows.py geometry and source-specific panels. These views have
/// no transport reference. All game effects stay disabled; received data is read-only.</summary>
public sealed partial class PythonFeatureWindow : DesktopWindow
{
    internal static readonly IReadOnlyDictionary<string, (string Title, int Width, int Height)> Definitions =
        new Dictionary<string, (string, int, int)>
        {
            ["party"] = ("組隊", 950, 620), ["companion"] = ("夥伴出戰", 1040, 650),
            ["instance"] = ("副本／協力房間管理", 1040, 600), ["benefits"] = ("福利", 860, 620),
            ["other"] = ("其他功能", 1080, 740), ["alchemy"] = ("煉金", 1040, 650),
            ["crafting"] = ("製作", 1080, 650), ["efficiency"] = ("經驗效率", 960, 610),
            ["attributes"] = ("角色能力 · 配點", 570, 505), ["crafting-plan"] = ("自訂家具製作清單 · 不限項數", 900, 580),
            ["crafting-queue"] = ("製作排程", 820, 420), ["emoji"] = ("遊戲表情", 284, 104)
        };
    private readonly DesktopSession session;
    private readonly DesktopWindows windows;
    private readonly string key;
    private long generation;
    private bool closed;
    private EmojiGalleryView? emoji;
    private bool emojiClosing,emojiClosed;
    private readonly Dictionary<string, TextTable> tables = [];
    private TextBlock? cubeStatus, guildStatus, arkStatus;
    public PythonFeatureWindow(string key, DesktopSession session, DesktopWindows windows)
        : base("飄流Re:LaLa · " + Definitions[key].Title, Definitions[key].Width, Definitions[key].Height)
    {
        this.key = key; this.session = session; this.windows = windows; generation = session.Generation;
        Build(); session.Changed += Changed;
        Closing += async (_,args)=>
        {
            if(emoji is null||emojiClosed)return;args.Cancel=true;if(emojiClosing)return;
            emojiClosing=true;await StopEmojiAsync();
            Avalonia.Threading.Dispatcher.UIThread.Post(Close);
        };
        Closed += (_, _) => { closed = true; session.Changed -= Changed; };
        Refresh();
    }
    internal async Task StopEmojiAsync()
    {
        if(emoji is null)return;closed=true;session.Changed-=Changed;await emoji.DisposeAsync();emojiClosed=true;
    }
    private void Changed() => Ui.OnUi(() => { if (!closed) { if (generation != session.Generation) { generation = session.Generation; if(key!="emoji")Build(); } Refresh(); } });
    private void Build()
    {
        tables.Clear(); cubeStatus = guildStatus = arkStatus = null;
        commandButtons.Clear();
        actionNote = Ui.Text("請先登入並等待資料同步。", 12, Ui.Muted);
        actionNote.Name = "FeatureActionStatus";
        roomPasswords.Clear(); roomMembers.Clear(); dailyToggles.Clear(); pointDraft.Clear(); pointLabels.Clear(); pointBalance = null;
        Control content = key switch
        {
            "party" => Party(), "companion" => Companion(), "instance" => Ui.Tabs(("主要", Instance(false)), ("協力", Instance(true))),
            "benefits" => Ui.Tabs(("魔方", Cube()), ("每日任務", Daily(false)), ("每週任務", Daily(true)), ("每日助手", Assistant())),
            "other" => Ui.Tabs(("方舟", Ark()), ("組織", Guild())), "alchemy" => Alchemy(), "crafting" => Crafting(),
            "efficiency" => Efficiency(), "attributes" => Attributes(), "crafting-plan" => Plan(), "crafting-queue" => Queue(),
            "emoji" => Page("", Ui.Text("官方表情尚未就緒；聊天仍可使用文字。")), _ => throw new ArgumentOutOfRangeException(nameof(key))
        };
        if (key == "emoji")
        {
            CanResize=true;emoji=new();emoji.Selected+=token=>windows.Dashboard.InsertEmojiDraft(token,generation);
            emoji.Ready+=count=>
            {
                var screen=Screens.Primary;double scale=screen?.Scaling??1;
                double maxWidth=Math.Min(1240,(screen?.WorkingArea.Width??1280)/scale-48),maxHeight=Math.Min(760,(screen?.WorkingArea.Height??800)/scale-80);
                var minimum=EmojiGalleryView.PreferredGrid(count,52,58,maxWidth,maxHeight);
                var preferred=EmojiGalleryView.PreferredGrid(count,68,74,maxWidth,maxHeight)??minimum;
                if(minimum is {} min&&preferred is {} size){MinWidth=min.Width+24;MinHeight=min.Height+68;Width=size.Width+24;Height=size.Height+68;}
            };
            SetBody(emoji,fluid:true);return;
        }
        var body = new Grid { RowDefinitions = new("*,Auto"), RowSpacing = 5 };
        Ui.At(body, content, 0);
        Ui.At(body, actionNote, 0, 1);
        SetBody(body);
    }
    private static Control Page(string title, params Control[] children)
    {
        var panel = new StackPanel { Spacing = 8, Margin = new(6) };
        if (title.Length > 0) panel.Children.Add(Ui.Text(title, 20, bold: true));
        foreach (var child in children) panel.Children.Add(child);
        return new ScrollViewer { Content = panel, HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled };
    }
    private static Control Columns(string widths, params Control[] children)
    {
        var grid = new Grid { ColumnDefinitions = new(widths), ColumnSpacing = 10 };
        for (int i = 0; i < children.Length; i++) Ui.At(grid, children[i], i);
        return grid;
    }
    private static CheckBox Check(string title) => new() { Content = title, IsChecked = false };
    private static TextBox Edit(string placeholder = "", string? text = null) => new() { PlaceholderText = placeholder, Text = text, MaxLength = 128, MinWidth = 80 };
    private static Control Field(string title, Control input) => Ui.Field(title, input, "180,*");
    private TextTable Table(string name, string[] headings, int height = 200)
    {
        var table = new TextTable(headings, string.Join(',', headings.Select(_ => "*")), name) { Height = height };
        table.SetRows([], "等待資料同步；不以合成內容補入正式畫面。"); tables.Add(name, table); return table;
    }
    private Control Party()
    {
        var guard = new StackPanel { Spacing = 8 };
        guard.Children.Add(Check("名單未到齊時，遇戰自動逃跑"));
        var entries = Enumerable.Range(1, 4).Select(i => Edit("名稱／ID")).ToArray();
        for (int i = 0; i < entries.Length; i++) guard.Children.Add(Ui.Row(Ui.Text((i + 1).ToString()), entries[i], Ui.Text("未指定")));
        guard.Children.Add(Actions("帶入目前隊伍", "儲存並套用"));
        guard.Children.Add(Ui.Button("清空", () => { foreach (var entry in entries) entry.Text = ""; }));
        guard.Children.Add(Ui.Text("草稿尚未套用；必要隊員規則尚未接入桌面執行。", 12, Ui.Muted));
        return Columns("*,300", Page("隊伍管理", Ui.Text("隊伍狀態由伺服器同步"),
            Ui.Row(Ui.Text("目標"), partyTarget = Edit("角色 ID"), GameButton("開啟組隊", () => new("party", "flag"))),
            Actions("邀請組隊", "申請入隊", "離隊／解散"),
            Columns("*,*", Ui.Card("隊伍成員", Table("PartyMembers", ["名稱／ID", "身分"])),
                Ui.Card("待確認邀請／申請", Table("PartyRequests", ["請求", "名稱／ID"]))),
            Actions("移除隊員", "轉交隊長", "接受", "拒絕")), Ui.Card("必要隊員名單", guard));
    }
    private Control Companion() => Page("選擇夥伴出戰", Ui.Text("選取夥伴查看能力與目前出戰狀態。", color: Ui.Muted),
        Table("Companions", ["編號", "夥伴", "等級", "HP", "SP", "狀態"], 330), Ui.Text("請從清單選擇夥伴。"), Actions("設為出戰", "休息"));
    private Control Instance(bool coop) => Page(coop ? "協力副本" : "主要副本", Ui.Text("從官方清單選取副本；加入房間前請先更新伺服器房間清單。"),
        InstanceControls(coop),
        Columns("3*,2*", Ui.Card("官方同步副本清單（選擇後建立房間）", Table(coop ? "CoopCatalog" : "InstanceCatalog", ["ID", "官方中文名稱／版本", "等級", "人數", "時間"], 250)),
            Ui.Card("伺服器房間清單（選取後加入）", Table(coop ? "CoopRooms" : "InstanceRooms", ["房間／副本", "人數／條件", "公開狀態"], 250))),
        coop ? InstanceRewardControls() : InstanceActions(false, "開始挑戰", "進入副本"));
    private Control Cube()
    {
        cubeStatus = Ui.Text("可開啟：等待同步");
        var auto = DailyToggle("自動開啟已分析完成的魔方", "cube");
        return Page("時間魔方", auto, cubeStatus, Ui.Text("分析時間：等待伺服器同步"), Actions("開啟魔方"), Ui.Text("最多儲存 3 次。分析由伺服器自動累積。", color: Ui.Muted));
    }
    private Control Daily(bool weekly)
    {
        var auto = DailyToggle("自動領取已達標任務與活躍寶箱", weekly ? "weekly" : "daily");
        return Page("", Ui.Row(auto, GameButton("領取可領項目", () => new("daily", "ready"))), Ui.Text("活躍值與獎勵以伺服器回報為準"),
            Table(weekly ? "WeeklyTasks" : "DailyTasks", ["任務", "進度", "條件", "狀態"], 250),
            Actions("領取選取任務", "開啟相關功能", "領取活躍寶箱"), Ui.Text("選取任務可查看執行方式；進度由伺服器確認。"));
    }
    private Control Assistant()
    {
        var toggles = new WrapPanel();
        foreach (var label in new[] { "魔方開啟", "任務／寶箱領獎", "組織簽到", "組織捐獻", "方舟派遣", "方舟戰鬥", "方舟問答" }) toggles.Children.Add(Check(label));
        return Page("每日助手", toggles, Columns("*,*", Ui.Column(Field("金幣上限（本輪）", Edit()), Field("每日捐獻總次數 1–5", Edit())),
            Ui.Column(Field("星力上限（本次登入）", Edit()), Field("派遣小時 1–6", Edit()))),
            Field("捐獻方案", Ui.Combo(["初級捐獻", "中級捐獻", "高級捐獻"])), Actions("套用助手設定", "暫停全部接續"),
            Table("AssistantTasks", ["今日任務", "伺服器進度", "執行分類", "說明"], 160), Ui.Text("勾選只修改草稿；尚未接入設定套用或自動接續。", color: Ui.Muted));
    }
    private Control Ark() => ArkControls();
    private Control Guild() => GuildControls();
    private Control Alchemy() => AlchemyControls();
    private Control Crafting() => CraftControls();
    private Control Queue() => CraftQueueControls();
    private Control Plan() => Page("自訂製作清單", Ui.Text("加入配方、調整批數與順序，再開始執行；開始後會消耗材料。"),
        Table("CraftPlan", ["順序", "家具／製作物", "批數", "總產量"], 270), Actions("加入目前配方", "上移", "下移", "移除", "清空", "儲存", "載入"),
        Ui.Row(Ui.Text("選取項目總批數"), Edit(text: "1"), Ui.Unavailable("更新批數")), Actions("開始／繼續清單", "暫停清單"),
        Ui.Text("製作方案編輯與匯入／匯出尚未接線；不會送出或消耗材料。", color: Ui.Muted));
    private Control Efficiency() => Page("經驗效率", Ui.Row(Ui.Text("統計對象"), Ui.Combo([], -1), Ui.Text("效率單位"), Ui.Combo(["天", "時", "分"], 2), Ui.Unavailable("重設統計")),
        Ui.Card("", Ui.Column(Ui.Text("等待登入角色與經驗資料"), Ui.Text("首場作基準，從第二個有效樣本計算效率"), new ProgressBar { Maximum = 100, Value = 0 })),
        Table("Efficiency", ["統計範圍", "經驗／分", "升級倒數", "一轉190倒數"], 160), Ui.Text("只統計本機角色與已確認的所屬夥伴／坐騎；效率投影尚未接入。", color: Ui.Muted));
    private Control Attributes()
        => AttributeControls();
    private void Refresh()
    {
        if(key=="emoji"){emoji?.Update(session.ReadEmojiGallery());return;}
        var view = session.ReadView(); var s = view.Snapshot;
        RefreshGameControls();
        RefreshServiceTables();
        RefreshAlchemyControls();
        RefreshCraftControls();
        RefreshSocialControls();
        if (tables.TryGetValue("Companions", out var companions)) companions.SetRows(s.Companions.CompanionOrder
            .Where(s.Companions.Companions.ContainsKey).Select(i => { var c = s.Companions.Companions[i].Data; return (i.ToString(), new[] { i.ToString(), c.Name ?? $"夥伴 {c.NpcId}", c.Level.ToString(), c.Hp?.ToString() ?? "待同步", c.Sp?.ToString() ?? "待同步", s.Companions.ActiveNpcId == c.NpcId ? "出戰" : "休息" }); }));
        if (tables.TryGetValue("PartyMembers", out var members))
        {
            var team = s.Party.OwnTeam(s.Player?.RoleId);
            members.SetRows(team?.Members.Select(id => (id.ToString(), new[] { s.Party.PlayerName(id, s.Player?.RoleId, s.Player?.Name), team.LeaderId == id ? "隊長" : "隊員" })) ?? []);
            tables["PartyRequests"].SetRows(s.Party.Requests.Values.Select(r => (r.Key, new[] { r.Type, s.Party.PlayerName(r.RoleId) })));
        }
        if (tables.TryGetValue("CraftQueue", out var queue)) queue.SetRows(s.Crafting.Crafting.QueueOrder.Where(s.Crafting.Crafting.Queue.ContainsKey)
            .Select(i => { var row = s.Crafting.Crafting.Queue[i]; return (i.ToString(), new[] { i.ToString(), view.Labels.Item(row.ItemId), row.Count.ToString(), Math.Max(0, row.BaseTime - CraftingReducer.Elapsed(s.Crafting.Crafting, row, System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency)).ToString("F0") + " 秒" }); }));
        if (cubeStatus is not null) cubeStatus.Text = s.TimeCube.Ready ? $"可開啟：{s.TimeCube.Count} / 3｜{s.TimeCube.Status}" : "可開啟：等待同步";
        if (guildStatus is not null) guildStatus.Text = $"組織：{s.Guild.Name ?? "尚未同步"}｜{s.GuildActions.Status}";
        if (arkStatus is not null) arkStatus.Text = s.Ark.Status;
    }
}
internal static class PythonFeatureActions
{
    internal static WrapPanel WithActions(this WrapPanel panel, string[] labels)
    {
        foreach (var label in labels) { var button = Ui.Unavailable(label); button.Margin = new(0, 0, 6, 4); panel.Children.Add(button); }
        return panel;
    }
}
