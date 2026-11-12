using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;

namespace Lala.Android.Live;

internal sealed record MobileOfficialLine(int Id, string Group, string Label, bool Supported)
{ public override string ToString() => Group + " / " + Label; }
internal sealed record MobileOfficialSnapshot(
    IReadOnlyList<MobileOfficialLine> Lines, OfficialVersionSnapshot? Version, ResourcePreparationProgress ResourceProgress,
    bool Busy, bool ResourcesReady, bool Connected, bool CanChat, bool CanAct, bool NotificationsAllowed,
    bool ServiceBound, string Status, AccountRoleSelectionRequest? RoleRequest, AccountRuntimePublication? Publication)
{
    public IReadOnlyList<GameAutomationStatus> Automations { get; init; } = [];
    public GameNavigationStatus Navigation { get; init; } = new(false, "尚未啟動導航");
    public override string ToString() => nameof(MobileOfficialSnapshot);
}
internal interface IMobileOfficialClient
{
    MobileOfficialSnapshot Snapshot { get; }
    Task RefreshAsync();
    void CancelPreparation();
    bool Login(int lineId, ReadOnlySpan<char> account, ReadOnlySpan<char> password);
    void SelectRole(Guid requestId, int index);
    void Disconnect();
    void RequestNotifications();
    Task SendChatAsync(string channel, string text, uint? target = null);
    Task ExecuteAsync(GameAction action);
    Task SetAutomationAsync(string kind, bool enabled);
    Task NavigateAsync(ushort scene, ushort x, ushort y);
    Task StopNavigationAsync();
    PortraitRenderRequest? Portrait(bool companion);
    PortraitRenderRequest? RolePortrait(Guid requestId, byte index);
    SmallMapRenderRequest? SmallMap(ushort scene);
    byte[]? ItemImage(ushort itemId);
}
