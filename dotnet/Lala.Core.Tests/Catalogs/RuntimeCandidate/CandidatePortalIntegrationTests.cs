using System.Collections.Immutable;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Tests.World.Eve;
using Lala.Core.World.Portals;
using Xunit;

namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;

public sealed class CandidatePortalIntegrationTests
{
    internal const string Version = "1286_2026_10_29_13_42_37_94";
    [Theory]
    [MemberData(nameof(CandidatePortalOracleCases.Cases), MemberType=typeof(CandidatePortalOracleCases))]
    public void Ten_table_candidate_reconciles_event_exits_without_optional_sources(string name,int id)
    {
        var fixture=CandidatePortalOracleCases.Read(id); Assert.Equal(name,fixture.GetProperty("name").GetString());
        var inputs=Inputs(fixture); var candidate=OfflineRuntimeCandidateDecoder.Decode(inputs,Version);
        AssertObservations(fixture.GetProperty("expected"),candidate);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources,candidate.SourceSha256.Keys);
        // Retained observations cannot depend on mutable supplied buffers or dictionary contents.
        foreach (var raw in inputs.Values)
        {
            Assert.True(System.Runtime.InteropServices.MemoryMarshal.TryGetArray(raw,out var bytes));
            Array.Fill(bytes.Array!,(byte)0xff);
        }
        inputs.Clear();
        AssertObservations(fixture.GetProperty("expected"),candidate);
        Assert.False(candidate.HasVerifiedProvenance); Assert.False(candidate.RuntimeAdmitted);
        Assert.False(candidate.AssetsReady); Assert.False(candidate.CanSendPackets);
        Assert.Contains("portal_metadata",candidate.UnavailableOptionalSources);
    }

    [Fact]
    public void Late_table_failure_and_cancellation_do_not_replace_prior_portal_observations()
    {
        var fixture=CandidatePortalOracleCases.Read(1); var inputs=Inputs(fixture);
        var prior=OfflineRuntimeCandidateDecoder.Decode(inputs,Version); var observations=prior.PortalObservations;
        Assert.Single(observations.Reconciled.Destinations);
        inputs["NpcCareerData_C"]=ReadOnlyMemory<byte>.Empty;
        Assert.Throws<CatalogDecodeException>(() => OfflineRuntimeCandidateDecoder.Decode(inputs,Version));
        Assert.Same(observations,prior.PortalObservations); AssertObservations(fixture.GetProperty("expected"),prior);
        using var cancelled=new CancellationTokenSource(); cancelled.Cancel();
        Assert.Throws<OperationCanceledException>(() => OfflineRuntimeCandidateDecoder.Decode(Inputs(fixture),Version,cancelled.Token));
        AssertObservations(fixture.GetProperty("expected"),prior);
    }

    [Fact]
    public void Full_decoder_applies_fixed_expansion_budget_before_large_event_observations_publish()
    {
        var fixture=CandidatePortalOracleCases.Read(1); var inputs=Inputs(fixture);
        var prior=OfflineRuntimeCandidateDecoder.Decode(inputs,Version);
        inputs["Eve"]=Convert.FromBase64String(CandidatePortalOracleCases.Read(0).GetProperty("budget_eve").GetString()!);
        var error=Assert.Throws<PortalProjectionException>(() => OfflineRuntimeCandidateDecoder.Decode(inputs,Version));
        Assert.Contains("budget exceeded",error.Message,StringComparison.Ordinal);
        AssertObservations(fixture.GetProperty("expected"),prior);
        Assert.DoesNotContain(typeof(OfflineRuntimeCandidateDecoder).GetMethods().SelectMany(m => m.GetParameters()),
            p => p.ParameterType==typeof(PortalProjectionBudget));
    }

    [Fact]
    public void Candidate_observations_do_not_offer_optional_or_runtime_authority_injection()
    {
        Assert.Empty(typeof(OfflineRuntimePortalObservations).GetConstructors());
        Assert.All(typeof(OfflineRuntimeCandidateDecoder).GetMethods().Where(m => m.DeclaringType==typeof(OfflineRuntimeCandidateDecoder)),
            m => Assert.DoesNotContain(m.GetParameters(),p => p.ParameterType==typeof(OfflineEventPortalProjection) || p.ParameterType==typeof(OfflineRuntimePortalObservations)));
        var candidate=OfflineRuntimeCandidateDecoder.Decode(Inputs(CandidatePortalOracleCases.Read(1)),Version);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<EventPortalKey,EventPortalDestination>)candidate.PortalObservations.Reconciled.Destinations).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<string>)candidate.PortalObservations.UnavailableOptionalSources).Clear());
        Assert.False(candidate.PortalObservations.Coverage.AllSourcesAvailable);
    }

    internal static Dictionary<string,ReadOnlyMemory<byte>> Inputs(JsonElement fixture) => fixture.GetProperty("inputs").EnumerateObject()
        .ToDictionary(p => p.Name,p => (ReadOnlyMemory<byte>)Convert.FromBase64String(p.Value.GetString()!),StringComparer.Ordinal);
    internal static void AssertOwnedFlowObservations(OfflineRuntimeCandidate candidate) => AssertObservations(CandidatePortalOracleCases.Read(0).GetProperty("expected"),candidate);
    internal static void AssertObservations(JsonElement expected,OfflineRuntimeCandidate candidate)
    {
        var observations=candidate.PortalObservations; var projection=observations.Reconciled;
        Assert.Equal(new[] { "StageMapData_C","EveDoorLinks","DoorLinkData_C" },observations.UnavailableOptionalSources);
        Assert.False(observations.Coverage.AllSourcesAvailable);
        Assert.Equal("missing",observations.Coverage.SourceStatus["StageMapData_C"]);
        Assert.Equal("missing",observations.Coverage.SourceStatus["EveDoorLinks"]);
        Assert.Equal(0,observations.Coverage.OfficialLinkReferenceCount);
        Assert.Equal(0,observations.Coverage.DoorLinkDataRouteCount);
        Assert.Equal(expected.GetProperty("positions").GetArrayLength(),projection.Positions.Count);
        Assert.Equal(expected.GetProperty("destinations").GetArrayLength(),projection.Destinations.Count);
        Assert.Equal(expected.GetProperty("issues").GetArrayLength(),projection.Issues.Count);
        foreach(var row in expected.GetProperty("positions").EnumerateArray()) PortalParityJson.AssertSubset(row.GetProperty("value"),PortalParityJson.Position(projection.Positions[Key(row)]));
        foreach(var row in expected.GetProperty("destinations").EnumerateArray()) PortalParityJson.AssertSubset(row.GetProperty("value"),PortalParityJson.Destination(projection.Destinations[Key(row)]));
        foreach(var row in expected.GetProperty("issues").EnumerateArray()) Assert.Equal(row.GetProperty("value").GetString(),projection.Issues[Key(row)]);
        PortalParityJson.AssertSubset(expected.GetProperty("coverage"),JsonSerializer.SerializeToElement(observations.Coverage,new JsonSerializerOptions { PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower }));
        Assert.All(projection.Positions.Values,p => Assert.Equal("eve_convey_door_scaled",p.SourceKind));
        Assert.All(projection.Destinations.Values,p => { Assert.Equal("eve_convey",p.BindingKind); Assert.Null(p.LinkIndex); Assert.False(p.TriggerVerified); });
    }
    private static EventPortalKey Key(JsonElement row) => new(row.GetProperty("key")[0].GetUInt16(),row.GetProperty("key")[1].GetUInt16());
}
