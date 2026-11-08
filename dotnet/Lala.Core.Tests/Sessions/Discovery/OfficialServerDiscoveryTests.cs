using System.Reflection;
using System.Security.Cryptography;
using Lala.Core.Resources;
using Lala.Core.Sessions.Discovery;
using Xunit;
using static Lala.Core.Tests.Sessions.Discovery.DiscoveryTestSupport;

namespace Lala.Core.Tests.Sessions.Discovery;

public sealed class OfficialServerDiscoveryTests
{
    [Fact]
    public async Task Public_factory_is_inert_precancelled_refresh_makes_no_requests_and_has_no_injection_route()
    {
        using var discovery = OfficialServerDiscovery.Create();
        Assert.Null(discovery.Current);
        Assert.Empty(typeof(OfficialServerDiscovery).GetConstructors());
        Assert.Single(typeof(OfficialServerDiscovery).GetMethods(BindingFlags.Public | BindingFlags.Static));
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => discovery.RefreshAsync(cancellation.Token));
        Assert.Null(discovery.Current);
        Assert.Throws<ResourceValidationException>(() => OfficialServerDiscovery.Create("example.com"));
        Assert.Throws<ResourceValidationException>(() => OfficialServerDiscovery.Create("wlreftpsrc.chinesegamer.net:443"));
    }

    [Fact]
    public async Task Offline_source_never_grants_official_origin_and_line_selection_is_explicit_read_only()
    {
        var source = new Source();
        using var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        Assert.Equal(0, source.Observations); Assert.Equal(0, source.Fetches);
        var result = await discovery.RefreshAsync();
        Assert.Same(result, discovery.Current);
        Assert.Equal(2, source.Observations); Assert.Equal(1, source.Fetches);
        Assert.Equal(Url, result.ExactUrl); Assert.Equal(DataVersion, result.Version.DataVersion);
        Assert.False(result.TlsOriginObserved); Assert.False(result.PublisherSignatureVerified);
        Assert.False(result.VerificationEndpointVerified); Assert.False(result.CanLogin); Assert.False(result.CanSendPackets);
        Assert.False(result.TrySelectLine(0, out _)); Assert.False(result.TrySelectLine(1, out _));
        Assert.True(result.TrySelectLine(101, out var line)); Assert.Equal("8.8.8.8", line!.Host);
        Assert.False(line.CanLogin); Assert.False(line.CanSendPackets);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(source.Raw)), result.ContentSha256);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData([.. Bytes(Url), 0, .. source.Raw])), result.CatalogIdentity);
    }

    [Theory]
    [InlineData("data")] [InlineData("exe")] [InlineData("DataPackage")] [InlineData("MainPackage")]
    public async Task Changed_identity_never_replaces_previous_success(string field)
    {
        var source = new Source();
        using var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var previous = await discovery.RefreshAsync();
        source.Observe = (number, _) => ValueTask.FromResult(number % 2 == 1 ? Snapshot() : field switch
        {
            "data" => Snapshot(data: "1.3.24"), "exe" => Snapshot(exe: "1.3.1"),
            "DataPackage" => Snapshot(dataPackage: "1297_2026_11_04_13_34_19_13"),
            _ => Snapshot(mainPackage: "1297_2026_11_04_13_34_19_13")
        });
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(() => discovery.RefreshAsync());
        Assert.Equal(OfficialServerDiscoveryFailure.VersionChanged, failure.Failure);
        Assert.Same(previous, discovery.Current);
    }

    [Fact]
    public async Task Timestamp_change_is_not_identity_change_and_failed_parse_retains_previous()
    {
        var source = new Source { Observe = (number, _) => ValueTask.FromResult(Snapshot(checkedAt: number.ToString())) };
        using var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var previous = await discovery.RefreshAsync();
        source.Raw = Bytes("not JSON");
        await Assert.ThrowsAsync<OfficialServerDiscoveryException>(() => discovery.RefreshAsync());
        Assert.Same(previous, discovery.Current);
    }

    [Fact]
    public async Task Concurrent_refresh_is_rejected_and_disposal_prevents_late_publication()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var source = new Source { Fetch = async (_, _) => { entered.SetResult(); await release.Task; return List(); } };
        var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var refresh = discovery.RefreshAsync();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await Assert.ThrowsAsync<InvalidOperationException>(() => discovery.RefreshAsync());
        discovery.Dispose(); discovery.Dispose(); Assert.Equal(1, source.Disposals);
        release.SetResult();
        await Assert.ThrowsAsync<ObjectDisposedException>(() => refresh);
        Assert.Null(discovery.Current);
        await Assert.ThrowsAsync<ObjectDisposedException>(() => discovery.RefreshAsync());
    }

    [Theory]
    [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public async Task Cancellation_at_each_acquisition_stage_prevents_publication(int stage)
    {
        using var cancellation = new CancellationTokenSource();
        var source = new Source
        {
            Observe = (number, _) => { if (number == 1 && stage == 1 || number == 2 && stage == 3) cancellation.Cancel(); return ValueTask.FromResult(Snapshot()); },
            Fetch = (_, _) => { if (stage == 2) cancellation.Cancel(); return ValueTask.FromResult(List()); }
        };
        using var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => discovery.RefreshAsync(cancellation.Token));
        Assert.Equal(cancellation.Token, failure.CancellationToken); Assert.Null(discovery.Current);
    }
}
