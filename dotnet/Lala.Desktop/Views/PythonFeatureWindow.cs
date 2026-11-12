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
            ["attributes"] = ("角色能力 · 配點", 570, 505), ["crafting-plan"] = ("自訂製作清單 · 最多 512 項", 900, 580),
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
    private void Changed() => Ui.OnUi(() =>
    {
        if (closed) return;
        if (generation != session.Generation)
        {
            if (key != "emoji") { Close(); return; }
            generation = session.Generation;
        }
        Refresh();
    });
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
        guard.Children.Add(PartyGuardControls());
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
        => AssistantControls();
    private Control Ark() => ArkControls();
    private Control Guild() => GuildControls();
    private Control Alchemy() => AlchemyControls();
    private Control Crafting() => CraftControls();
    private Control Queue() => CraftQueueControls();
    private Control Plan() => CraftPlanControls();
    private Control Efficiency() => EfficiencyControls();
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
        RefreshCraftPlanControls();
        RefreshSocialControls();
        RefreshAssistantControls();
        RefreshEfficiencyControls();
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
