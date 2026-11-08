using System.Net;
using Lala.Core.Resources;
using Lala.Core.Sessions;

// Deliberately no InternalsVisibleTo: this is a real external Core consumer.
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
await using (var account = AccountRuntime.Create(session, generation, profile, source, root))
{
    Require(!account.Snapshot.HasCurrentResources && account.Publication is null);
    var result = await account.RunAsync(cancel.Token);
    Require(result.ResourcesReleased && result.ResourceHistory.IsEmpty);
    Require(source.Calls == 0 && !Directory.Exists(root) && !account.Snapshot.CanSendCommands);
}
var inspection = await ResourceInventoryInspector.InspectAsync(root);
Require(inspection.Status == ResourceInventoryInspectionStatus.Missing && !inspection.CanLogin && !inspection.CanSendPackets);
Require(!Directory.Exists(root));
Console.WriteLine("Public Core contract check passed; no network or resource writes were requested.");
static void Require(bool condition) { if (!condition) throw new InvalidOperationException("Public Core contract check failed."); }
sealed class DecliningSource : IAccountCredentialSource
{
    public int Calls { get; private set; }
    public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken token)
    { Calls++; return ValueTask.FromResult<AccountLoginCredentials?>(null); }
}
