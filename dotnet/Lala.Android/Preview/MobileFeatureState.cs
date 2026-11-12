namespace Lala.Android.Preview;

/// <summary>Local, in-memory examples only. Never shared with a game session or credentials.</summary>
internal sealed partial class MobilePreviewState
{
    internal bool AnnouncementVisible { get; set; } = true;
    internal int TeamTab { get; set; }
    internal HashSet<int> Party { get; } = [0];
    internal HashSet<int> Requests { get; } = [1, 2, 3];
    internal int Following { get; set; } = -1;
    internal int Guarding { get; set; } = -1;
    internal List<PreviewMessage> Messages { get; } =
    [
        new("lalaplayer01", "有人想一起冒險嗎？這是聊天氣泡示範。", "世界", 0),
        new("RiverMoon", "+1！可以先看看附近玩家和組隊卡片。", "組隊", 1),
        new("星璃", "青色發光樣式很好看，這些訊息都只在本機預覽。", "世界", 2),
        new("WindLeaf", "我也想一起！可以試試下方的邀請按鈕。", "組隊", 0)
    ];
    internal int[] CompanionModes { get; } = [0, 1, 2];
    internal int[] Attributes { get; } = [102, 98, 110, 120];
    internal int[] AttributeDraft { get; } = [0, 0, 0, 0];
    internal int AttributePoints { get; set; } = 12;
    internal bool[] ExpeditionTasks { get; } = [true, true, false, false, false, false];
    internal bool[] SavedExpeditionTasks { get; set; } = [true, true, false, false, false, false];
    internal bool ExpeditionRunning { get; set; }
    internal int ExpeditionAffinity { get; set; } = 80;
    internal bool RoomCreated { get; set; }
    internal int RoomMembers { get; set; } = 4;
    internal bool DungeonRunning { get; set; }
    internal bool RewardClaimed { get; set; }
    internal bool AutoReward { get; set; } = true;
    internal int AlchemyMode { get; set; }
    internal int AlchemyCount { get; set; } = 100;
    internal bool[] AlchemyMaterials { get; } = [true, true, true, true, true];
    internal bool AlchemyRunning { get; set; }
    internal int AlchemyProgress { get; set; }
    internal int Recipe { get; set; }
    internal int CraftQuantity { get; set; } = 1;
    internal string RecipeQuery { get; set; } = "";
    internal bool FavoritesOnly { get; set; }
    internal HashSet<int> FavoriteRecipes { get; } = [0, 2];
    internal bool CraftRunning { get; set; }
    internal bool CraftContinue { get; set; } = true;
    internal bool CraftLoop { get; set; }
    internal List<PreviewCraftJob> CraftQueue { get; } = [new(0, 1, 32), new(2, 10), new(1, 1)];
    internal int SettingsTab { get; set; }
    internal bool AiEnabled { get; set; } = true;
    internal int TaskMode { get; set; }
    internal int ScanInterval { get; set; } = 120;
    internal int RecoveryHp { get; set; } = 70;
    internal int RecoverySp { get; set; } = 40;
    internal int SupplyCount { get; set; } = 20;
    internal int GuardHp { get; set; } = 25;
    internal int CleanupPercent { get; set; } = 85;
    internal int ExchangeInterval { get; set; } = 300;
    internal string SavedSettingsJson { get; set; } = "";
    internal int ToolStored { get; set; } = 1284;
    internal int ToolCrystals { get; set; } = 12;
    internal int ToolTaskProgress { get; set; } = 3;
    internal bool ToolGiftClaimed { get; set; }
    internal List<PreviewRule> Rules { get; } =
    [
        new("自動恢復", "heart", 2), new("自動補給", "cube", 3), new("守衛／警戒", "shield", 4), new("清理與維護", "star", 5)
    ];
}

internal sealed record PreviewMessage(string Sender, string Text, string Channel, int Portrait, bool Own = false, string Reply = "", string At = "14:26");
internal sealed class PreviewCraftJob(int recipe, int quantity, int progress = 0)
{
    internal int Recipe { get; } = recipe;
    internal int Quantity { get; } = quantity;
    internal int Progress { get; set; } = progress;
}
internal sealed class PreviewRule(string name, string icon, int category)
{
    internal string Name { get; } = name;
    internal string Icon { get; } = icon;
    internal int Category { get; } = category;
    internal bool Enabled { get; set; } = true;
}
