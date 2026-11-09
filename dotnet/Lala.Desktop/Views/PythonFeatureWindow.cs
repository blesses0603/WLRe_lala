using Avalonia.Controls;
using Avalonia.Layout;

namespace Lala.Desktop;

/// <summary>Python feature_windows.py geometry and source-specific panels. These views have
/// no transport reference. All game effects stay disabled; received data is read-only.</summary>
public sealed class PythonFeatureWindow : DesktopWindow
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
        Ui.At(body, Ui.Text("介面已補入；尚未接通的操作保持停用。資料僅顯示核心已接收內容，資源仍 Held。", 12, Ui.Muted), 0, 1);
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
    private static Control Actions(params string[] labels) => new WrapPanel
    { Orientation = Orientation.Horizontal, Children = { } }.WithActions(labels);
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
            Ui.Row(Ui.Text("目標"), Edit("附近玩家／角色 ID"), Ui.Unavailable("開啟組隊")),
            Actions("邀請組隊", "申請入隊", "離隊／解散"),
            Columns("*,*", Ui.Card("隊伍成員", Table("PartyMembers", ["名稱／ID", "身分"])),
                Ui.Card("待確認邀請／申請", Table("PartyRequests", ["請求", "名稱／ID"]))),
            Actions("移除隊員", "轉交隊長", "接受", "拒絕")), Ui.Card("必要隊員名單", guard));
    }
    private Control Companion() => Page("選擇夥伴出戰", Ui.Text("選取夥伴查看能力與目前出戰狀態。", color: Ui.Muted),
        Table("Companions", ["編號", "夥伴", "等級", "HP", "SP", "狀態"], 330), Ui.Text("請從清單選擇夥伴。"), Actions("設為出戰", "休息"));
    private Control Instance(bool coop) => Page(coop ? "協力副本" : "主要副本", Ui.Text("尚未同步房間；登入與官方目錄完成後才可查詢。"),
        Actions("更新房間清單", "建立公開／私人房間", "加入選取房間", "離開房間", coop ? "準備／開始配對" : "進入副本"),
        Columns("3*,2*", Ui.Card("官方同步副本清單（選擇後建立房間）", Table(coop ? "CoopCatalog" : "InstanceCatalog", ["ID", "官方中文名稱／版本", "等級", "人數", "時間"], 250)),
            Ui.Card("伺服器房間清單（選取後加入）", Table(coop ? "CoopRooms" : "InstanceRooms", ["房間／副本", "人數／條件", "公開狀態"], 250))),
        coop ? Actions("領取免費協力獎勵", "放棄目前寶箱", "開啟免費獎勵自動領取") : Ui.Text("沒有已確認的副本房間。"));
    private Control Cube()
    {
        cubeStatus = Ui.Text("可開啟：等待同步");
        var auto = Check("自動開啟已分析完成的魔方"); auto.IsEnabled = false;
        return Page("時間魔方", auto, cubeStatus, Ui.Text("分析時間：等待伺服器同步"), Actions("開啟魔方"), Ui.Text("最多儲存 3 次。分析由伺服器自動累積。", color: Ui.Muted));
    }
    private Control Daily(bool weekly)
    {
        var auto = Check("自動領取已達標任務與活躍寶箱"); auto.IsEnabled = false;
        return Page("", Ui.Row(auto, Ui.Unavailable("領取可領項目")), Ui.Text("活躍值：等待同步"),
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
    private Control Ark()
    {
        arkStatus = Ui.Text("等待星之方舟與每日任務同步");
        var help = Ui.Text("派遣、戰鬥、問答尚未接入桌面；不付費刷新、加速或升級技能。", color: Ui.Muted); help.IsVisible = false;
        return Page("星之方舟", arkStatus,
            Ui.Row(Check("自動接續每日方舟任務"), Check("派遣情報員"), Check("戰鬥事件"), Check("問答自動答題")),
            Ui.Row(Ui.Text("採集小時"), Edit(text: "1"), Ui.Text("星力上限（本次登入）"), Edit(text: "120")),
            Ui.Row(Actions("套用設定", "暫停", "派遣一次", "執行選取事件"), Ui.Button("功能限制", () => help.IsVisible = !help.IsVisible)),
            Table("ArkEvents", ["事件", "星球", "類型", "執行方式"], 180),
            new TextBox { Text = "等待伺服器題目", IsReadOnly = true, AcceptsReturn = true, Height = 80 },
            Actions("回答選項 1", "回答選項 2", "回答選項 3", "回答選項 4"), help);
    }
    private Control Guild()
    {
        guildStatus = Ui.Text("組織：尚未同步｜簽到：等待同步");
        return Page("組織自動簽到與捐獻", guildStatus, Ui.Row(Check("自動簽到"), Check("自動捐獻")),
            Field("捐獻方案", Ui.Combo(["初級捐獻", "中級捐獻", "高級捐獻"])), Field("每日總目標", Edit(text: "3")),
            Field("金幣上限（本輪）", Edit(text: "450")), Actions("套用設定", "暫停組織自動操作", "立即簽到", "捐獻一次"),
            Ui.Text("等待組織與消費狀態同步；自動捐獻與額度規則尚未接入桌面。", color: Ui.Muted));
    }
    private Control Alchemy()
    {
        var fields = new Grid { ColumnDefinitions = new("80,*,90"), RowDefinitions = new("Auto,Auto,Auto,Auto,Auto,Auto"), RowSpacing = 8, ColumnSpacing = 8 };
        Ui.At(fields, Ui.Text("材料格"), 0); Ui.At(fields, Ui.Text("背包物品"), 1); Ui.At(fields, Ui.Text("每次數量"), 2);
        var selections = new List<ComboBox>();
        for (int i = 0; i < 5; i++) { Ui.At(fields, Ui.Text((i + 1).ToString()), 0, i + 1); var choice = Ui.Combo([], -1); selections.Add(choice); Ui.At(fields, choice, 1, i + 1); Ui.At(fields, Edit(text: "1"), 2, i + 1); }
        return Columns("*,210", Page("煉金", Ui.Row(Ui.Text("煉金術"), Ui.Combo(["無技能"]), Ui.Text("執行次數"), Edit(text: "3")), fields,
            Ui.Text("同一疊可重複選取；總消耗必須在開始前核對。", color: Ui.Muted)),
            Page("執行狀態", Ui.Text("等待背包與煉金資料同步"), Actions("預覽消耗／開始", "停止後續煉金"),
                Ui.Button("清空材料", () => { foreach (var selection in selections) selection.SelectedIndex = -1; })));
    }
    private Control Crafting()
    {
        var grid = new Grid { ColumnDefinitions = new("128,*,248"), ColumnSpacing = 8 };
        Ui.At(grid, Ui.Card("工作設備", new ListBox { ItemsSource = new[] { "♡ 我的最愛", "全部配方" }, Height = 320 }), 0);
        Ui.At(grid, Ui.Column(Ui.Card("製作項目", Table("CraftCatalog", ["名稱", "所需設備"], 300)), Actions("上一頁", "下一頁")), 1);
        Ui.At(grid, Ui.Card("配方詳情", Ui.Column(Ui.Text("請選擇製作物"), Ui.Text("設備／時間待官方資料同步"),
            Ui.Row(Ui.Text("批數"), Edit(text: "1")), Actions("加入排程", "加入自訂"), Table("CraftMaterials", ["材料", "背包", "雜物櫃", "需求"], 200))), 2);
        return Page("製作", Ui.Row(Ui.Button("自訂清單", () => windows.OpenPythonFeature("crafting-plan")),
            Ui.Unavailable("進入自家帳篷"), Ui.Button("製作排程", () => windows.OpenPythonFeature("crafting-queue"))),
            Ui.Row(Check("只列小屋已有設備"), Ui.Text("搜尋"), Edit("名稱／ID")), grid);
    }
    private Control Queue() => Page("製作排程", Ui.Text("製作進度：等待伺服器同步"), new ProgressBar { Minimum = 0, Maximum = 100, Value = 0 },
        Table("CraftQueue", ["順序", "製作物", "批數", "剩餘時間"], 210), Actions("開始／接續", "暫停", "停止接續", "上移", "下移", "移除"));
    private Control Plan() => Page("自訂製作清單", Ui.Text("加入配方、調整批數與順序，再開始執行；開始後會消耗材料。"),
        Table("CraftPlan", ["順序", "家具／製作物", "批數", "總產量"], 270), Actions("加入目前配方", "上移", "下移", "移除", "清空", "儲存", "載入"),
        Ui.Row(Ui.Text("選取項目總批數"), Edit(text: "1"), Ui.Unavailable("更新批數")), Actions("開始／繼續清單", "暫停清單"),
        Ui.Text("製作方案編輯與匯入／匯出尚未接線；不會送出或消耗材料。", color: Ui.Muted));
    private Control Efficiency() => Page("經驗效率", Ui.Row(Ui.Text("統計對象"), Ui.Combo([], -1), Ui.Text("效率單位"), Ui.Combo(["天", "時", "分"], 2), Ui.Unavailable("重設統計")),
        Ui.Card("", Ui.Column(Ui.Text("等待登入角色與經驗資料"), Ui.Text("首場作基準，從第二個有效樣本計算效率"), new ProgressBar { Maximum = 100, Value = 0 })),
        Table("Efficiency", ["統計範圍", "經驗／分", "升級倒數", "一轉190倒數"], 160), Ui.Text("只統計本機角色與已確認的所屬夥伴／坐騎；效率投影尚未接入。", color: Ui.Muted));
    private Control Attributes()
    {
        var body = new StackPanel { Spacing = 8 };
        foreach (var label in new[] { "智力 INT", "力量 STR", "體質 CON", "靈力 WIS", "敏捷 AGI" })
            body.Children.Add(Columns("*,80,Auto", Ui.Text(label), Ui.Text("待同步"), Actions("－", "＋", "＋10")));
        return Page("角色能力配點", Ui.Text("角色資料待同步"), Ui.Text("剩餘點數：待同步"), body,
            Ui.Text("尚未配點；確認前只會預覽，不會消耗點數。"), Actions("取消預覽", "確認配點"));
    }
    private void Refresh()
    {
        if(key=="emoji"){emoji?.Update(session.ReadEmojiGallery());return;}
        var view = session.ReadView(); var s = view.Snapshot;
        if (tables.TryGetValue("Companions", out var companions)) companions.SetRows(s.Companions.CompanionOrder
            .Where(s.Companions.Companions.ContainsKey).Select(i => { var c = s.Companions.Companions[i].Data; return (i.ToString(), new[] { i.ToString(), c.Name ?? $"夥伴 {c.NpcId}", c.Level.ToString(), c.Hp?.ToString() ?? "待同步", c.Sp?.ToString() ?? "待同步", s.Companions.ActiveNpcId == c.NpcId ? "出戰" : "休息" }); }));
        if (tables.TryGetValue("PartyMembers", out var members))
        {
            var team = s.Party.OwnTeam(s.Player?.RoleId);
            members.SetRows(team?.Members.Select(id => (id.ToString(), new[] { s.Party.PlayerName(id, s.Player?.RoleId, s.Player?.Name), team.LeaderId == id ? "隊長" : "隊員" })) ?? []);
            tables["PartyRequests"].SetRows(s.Party.Requests.Values.Select(r => (r.Key, new[] { r.Type, s.Party.PlayerName(r.RoleId) })));
        }
        if (tables.TryGetValue("CraftQueue", out var queue)) queue.SetRows(s.Crafting.Crafting.QueueOrder.Where(s.Crafting.Crafting.Queue.ContainsKey)
            .Select(i => { var row = s.Crafting.Crafting.Queue[i]; return (i.ToString(), new[] { i.ToString(), view.Labels.Item(row.ItemId), row.Count.ToString(), "待時間投影" }); }));
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
