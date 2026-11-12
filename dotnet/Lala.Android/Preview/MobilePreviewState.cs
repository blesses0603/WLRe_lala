namespace Lala.Android.Preview;

/// <summary>View-only state retained through activity recreation. Contains no credentials,
/// resource admission, account session or command sender.</summary>
internal sealed partial class MobilePreviewState
{
    internal int Page { get; set; }
    internal int Progress { get; set; } = 100;
    internal bool RoleSelected { get; set; }
    internal int AccountCount { get; set; } = 2;
    internal int ActiveAccount { get; set; }
    internal int Role { get; set; }
    internal int Mode { get; set; }
    internal bool ContinueFlow { get; set; } = true;
    internal bool TentOpen { get; set; }
    internal int SelectedItem { get; set; }
    internal string ItemQuery { get; set; } = "";
    internal int BagTab { get; set; }
    internal int TargetX { get; set; } = 182;
    internal int TargetY { get; set; } = 62;
    internal string MapFeedback { get; set; } = "點選地圖，預覽目的地與路線。";
    internal string ResourceCheckedAt { get; set; } = "尚未執行示範";
    internal List<string> Events { get; } = [];
    internal bool DemoMode { get; set; }
    internal int OfficialLineId { get; set; }
}
