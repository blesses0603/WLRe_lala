using System.Net;
using Lala.Core.Resources;
using Lala.Core.Inventory;
using Lala.Core.Expedition;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.State;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Discovery;

// Deliberately no InternalsVisibleTo: this is a real external Core consumer.
AutoBattlePublicCheck.Run();
CraftingPreflightPublicCheck.Run();
LogicalNavigationPublicCheck.Run();
var receiveState = new ServiceStateCoordinator();
var chatState = receiveState.Apply(new ServerSocialEvent(new ChatMessageEvent(1, "世界", 7, [], "synthetic chat", 0)),
    new(receiveState.Snapshot(), new(1)));
var chatPublication = new AccountReceivePublication(Guid.NewGuid(), 1, AccountReceivePhase.Running, chatState);
Require(chatPublication.State.Chat.Messages.Length == 1 && chatPublication.ResourceHeld);
var integratedChatPublication = new AccountRuntimePublication(chatPublication, null);
Require(ReferenceEquals(chatState.Chat, integratedChatPublication.Receive.State.Chat));
Require(chatPublication.State.Chat.Messages[0].Name == "7");
Require(chatPublication.State.Chat.Messages[0].Receipt.Event is ChatMessageEvent { Text: "synthetic chat" });
Require(chatPublication.State.Chat.DroppedMessageCount == 0 && chatPublication.State.Chat.Names.Names.IsEmpty);
Require(ChatNameScope.Local != ChatNameScope.Server(0) && ChatNameScope.CrossUnknown != ChatNameScope.Server(0));
Require(!chatPublication.ToString().Contains("synthetic chat", StringComparison.Ordinal));
var session = new AccountSession();
var generation = session.Begin("synthetic", "offline-contract-check").Generation;
var source = new DecliningSource();
var profile = new AccountConnectionProfile(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 1), 0, 0, 1, 1, 1);
using var cancel = new CancellationTokenSource();
cancel.Cancel();
await using (var connection = new AccountConnectionRuntime(session, generation, profile, source))
{
    Require(source.Calls == 0 && connection.Snapshot.Phase == AccountConnectionPhase.Created);
    var result = await connection.RunAsync(cancel.Token);
    Require(result.Status.EndReason == AccountConnectionEndReason.Cancelled);
    Require(source.Calls == 0 && connection.Publication is null && !connection.Snapshot.CanSendCommands);
}
var input = new DecliningInput();
await using (var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), profile, input))
{
    Require(ReferenceEquals(preparation.Disclosure.Profile, profile) && preparation.Disclosure.Generation == generation);
    Require(preparation.Disclosure.RoleSelectionMode == AccountRoleSelectionMode.Fixed && preparation.Disclosure.FixedRoleIndex == 1);
    Require(preparation.Disclosure.AttemptNumber == 1 && !preparation.Snapshot.CanSendCommands);
    var result = await preparation.RunAsync(cancel.Token);
    Require(input.Calls == 0 && result.ResourcesReleased && preparation.Publication is null && !preparation.Snapshot.CanSendCommands);
}
await using (var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), profile, input,
    roleSelector: new DecliningRoleSelector()))
{
    Require(preparation.Disclosure.RoleSelectionMode == AccountRoleSelectionMode.Interactive && preparation.Disclosure.FixedRoleIndex is null);
    var result = await preparation.RunAsync(cancel.Token);
    Require(result.ResourcesReleased && !preparation.Snapshot.CanSendCommands);
}
using (var credentials = new AccountLoginCredentials("synthetic", "synthetic"))
    Require(!credentials.IsDisposed && !credentials.ToString().Contains("synthetic", StringComparison.Ordinal));
var root = Path.Combine(Path.GetTempPath(), "lala-public-contract-" + Guid.NewGuid().ToString("N"));
await using (var resources = AccountResourceRuntime.Create(session, root))
{
    Require(!resources.HasCurrentResources && !resources.TryReadCatalogs(out _));
    Require(!resources.CanLogin && !resources.CanSendPackets && !Directory.Exists(root));
    var result = await resources.BootstrapAsync(generation, cancel.Token);
    Require(result.Status == AccountResourcePreparationStatus.Cancelled);
    Require(!result.CanLogin && !result.CanSendPackets && !Directory.Exists(root));
}
Require(!Directory.Exists(root));
await using (var account = AccountRuntime.Create(session, generation, profile, source, root, roleSelector: new DecliningRoleSelector()))
{
    var created = account.Snapshot;
    Require(ReferenceEquals(created, account.Snapshot) && !created.IsCompleted);
    Require(!created.HasCurrentResources && account.Publication is null);
    var materials = account.InspectCraftingMaterials(1, 1);
    Require(ReferenceEquals(materials.Basis, account.PublicationSnapshot));
    Require(materials.Outcome == CraftingMaterialAssessmentOutcome.NoPublication && materials.Preflight is null);
    Require(materials.ItemId == 1 && materials.BatchCount == 1 && materials.ResourceHeld && !materials.CanSendCommands);
    Require(source.Calls == 0 && !Directory.Exists(root));
    var assessment = account.InspectExpeditionTask(1, [1]);
    Require(ReferenceEquals(assessment.Basis, account.PublicationSnapshot));
    Require(assessment.Issues.Contains(ExpeditionAssessmentIssue.NoPublication));
    Require(assessment.DurationSeconds is null && assessment.RewardEmptySlots is null && assessment.Success is null);
    Require(!assessment.RecoveryStockComplete && assessment.ResourceHeld && !assessment.CanSendCommands);
    Require(account.InspectExpeditionTask(1, [1, 1]).Issues.Contains(ExpeditionAssessmentIssue.InvalidSelection));
    var publication = account.PublicationSnapshot;
    Require(ReferenceEquals(publication, account.PublicationSnapshot) && publication.Publication is null);
    Require(ReferenceEquals(publication.Connection, created.Connection) && !publication.IsCompleted);
    Require(ReferenceEquals(publication, await account.WaitForPublicationChangeAsync(publication with { })));
    var published = account.WaitForPublicationChangeAsync(publication);
    var changed = account.WaitForChangeAsync(created);
    Require(!changed.IsCompleted && !published.IsCompleted);
    var result = await account.RunAsync(cancel.Token);
    Require(!ReferenceEquals(created, await changed));
    var completed = account.Snapshot;
    Require(completed.IsCompleted && ReferenceEquals(completed, await account.WaitForChangeAsync(completed)));
    Require(!ReferenceEquals(publication, await published));
    var finalPublication = account.PublicationSnapshot;
    Require(finalPublication.IsCompleted && finalPublication.Publication is null);
    Require(ReferenceEquals(finalPublication, await account.WaitForPublicationChangeAsync(finalPublication)));
    Require(finalPublication.ResourceHeld && !finalPublication.CanSendCommands);
    Require(ReferenceEquals(finalPublication, account.InspectCraftingMaterials(1, 1).Basis));
    Require(account.InspectCraftingMaterials(1, 1).Preflight is null);
    Require(ReferenceEquals(finalPublication, account.InspectExpeditionTask(1, [1]).Basis));
    Require(account.InspectExpeditionTask(1, [1]).Issues.Contains(ExpeditionAssessmentIssue.NoPublication));
    Require(result.ResourcesReleased && result.ResourceHistory.IsEmpty);
    Require(source.Calls == 0 && !Directory.Exists(root) && !account.Snapshot.CanSendCommands);
}
// Prepared integrated composition: public APIs only. These declarations/assertions
// are source-level coverage until this revised consumer is explicitly run and verified.
foreach (bool interactive in new[] { false, true })
{
    var identity = Guid.NewGuid();
    await using var account = AccountRuntime.CreatePrepared(session, generation, identity, profile, input, root,
        roleSelector: interactive ? new DecliningRoleSelector() : null);
    var disclosure = account.Disclosure ?? throw new InvalidOperationException("Prepared disclosure is required.");
    Require(disclosure.Login.SelectedIdentity == identity && disclosure.Login.Generation == generation);
    Require(ReferenceEquals(disclosure.Login.Profile, profile) && disclosure.Login.AttemptNumber == 1);
    Require(disclosure.Login.RoleSelectionMode == (interactive ? AccountRoleSelectionMode.Interactive : AccountRoleSelectionMode.Fixed));
    Require(disclosure.Login.FixedRoleIndex == (interactive ? (int?)null : profile.RoleIndex));
    Require(disclosure.Resources.AbsoluteDataRoot == Path.TrimEndingDirectorySeparator(Path.GetFullPath(root)));
    Require(disclosure.Resources.InventoryPath == Path.Combine(root, "official_sync", "derived_catalogs", "resource_inventory.sqlite3"));
    Require(disclosure.Resources.BundleCacheDirectory == Path.Combine(root, "official_sync", "bundles"));
    Require(disclosure.Resources.VersionMapUrl == "https://wlreftpsrc.chinesegamer.net/WLN/TW/ResourcePath_PC.dat");
    Require(disclosure.Resources.ResourceUrlPrefix == "https://wlreftpsrc.chinesegamer.net/WLN/TW/");
    var created = account.Snapshot;
    Require(created.Connection.Phase == AccountConnectionPhase.Created && !created.IsCompleted);
    Require(input.Calls == 0 && !created.HasCurrentResources && account.Publication is null && !Directory.Exists(root));
    var changed = account.WaitForChangeAsync(created);
    Require(!changed.IsCompleted);
    var run = account.RunAsync(cancel.Token);
    Require(ReferenceEquals(run, account.RunAsync()));
    var result = await run;
    Require(!ReferenceEquals(created, await changed));
    var completed = account.Snapshot;
    Require(completed.IsCompleted && ReferenceEquals(completed, await account.WaitForChangeAsync(completed)));
    Require(result.ResourcesReleased && result.ResourceHistory.IsEmpty && completed.ResourceHistory.IsEmpty);
    Require(input.Calls == 0 && source.Calls == 0 && account.Publication is null && !completed.CanSendCommands);
    Require(!Directory.Exists(root));
}
// Dispose-before-Run must retire the same inert composition without requesting input,
// dialing either TCP recipient, or starting resource acquisition/storage.
var inertPrepared = AccountRuntime.CreatePrepared(session, generation, Guid.NewGuid(), profile, input, root);
Require(inertPrepared.Disclosure is not null && input.Calls == 0 && !Directory.Exists(root));
await inertPrepared.DisposeAsync();
Require(inertPrepared.Snapshot.IsCompleted && inertPrepared.Publication is null);
Require((await inertPrepared.RunAsync()).ResourceHistory.IsEmpty && input.Calls == 0 && !Directory.Exists(root));
var inspection = await ResourceInventoryInspector.InspectAsync(root);
Require(inspection.Status == ResourceInventoryInspectionStatus.Missing && !inspection.CanLogin && !inspection.CanSendPackets);
Require(!Directory.Exists(root));
using (var discovery = OfficialServerDiscovery.Create())
{
    Require(discovery.Current is null);
    bool cancelled = false;
    try { await discovery.RefreshAsync(cancel.Token); }
    catch (OperationCanceledException) { cancelled = true; }
    Require(cancelled && discovery.Current is null);
}
Console.WriteLine("Public Core contract check passed; no network or resource writes were requested.");
static void Require(bool condition) { if (!condition) throw new InvalidOperationException("Public Core contract check failed."); }
sealed class DecliningSource : IAccountCredentialSource
{
    public int Calls { get; private set; }
    public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken token)
    { Calls++; return ValueTask.FromResult<AccountLoginCredentials?>(null); }
}

sealed class DecliningInput : IAccountLoginInput
{
    public int Calls { get; private set; }
    public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token)
    { Calls++; throw new InvalidOperationException("Pre-cancelled preparation must not acquire."); }
}

sealed class DecliningRoleSelector : IAccountRoleSelector
{
    public ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken token)
    {
        _ = request.Generation; _ = request.HandshakeAttempt; _ = request.RequestId; _ = request.Roles;
        _ = request.Choose(1);
        throw new InvalidOperationException("Pre-cancelled preparation must not select.");
    }
}
