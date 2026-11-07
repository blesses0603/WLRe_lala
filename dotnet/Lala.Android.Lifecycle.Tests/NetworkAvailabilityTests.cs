using Lala.Android.Platform;
using Xunit;

namespace Lala.Android.Lifecycle.Tests;

public sealed class NetworkAvailabilityTests
{
    [Fact]
    public void MissingInitialNetworkIsOffline()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Initialize(null, hasInternet: true, validated: true);
        Assert.False(state.IsAvailable);
    }

    [Theory]
    [InlineData(false, false, false)]
    [InlineData(true, false, false)]
    [InlineData(false, true, false)]
    [InlineData(true, true, true)]
    public void InitialSnapshotRequiresBothInternetAndValidation(bool internet, bool validated, bool expected)
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Initialize(1, internet, validated);
        Assert.Equal(expected, state.IsAvailable);
    }

    [Fact]
    public void AvailableWaitsForCapabilitiesAndCaptivePortalCanLaterValidate()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Available(1);
        Assert.False(state.IsAvailable);
        state.CapabilitiesChanged(1, hasInternet: true, validated: false);
        Assert.False(state.IsAvailable);
        state.CapabilitiesChanged(1, hasInternet: true, validated: true);
        Assert.True(state.IsAvailable);
        state.CapabilitiesChanged(1, hasInternet: true, validated: false);
        Assert.False(state.IsAvailable);
    }

    [Fact]
    public void LateLostAndCapabilitiesFromPreviousDefaultCannotReplaceNewNetwork()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Available(1);
        state.CapabilitiesChanged(1, true, true);
        state.Available(2);
        Assert.False(state.IsAvailable);
        state.CapabilitiesChanged(2, true, true);
        state.Lost(1);
        state.CapabilitiesChanged(1, false, false);
        Assert.True(state.IsAvailable);
        state.Lost(2);
        state.CapabilitiesChanged(1, true, true);
        state.CapabilitiesChanged(2, true, true);
        Assert.False(state.IsAvailable);
    }

    [Fact]
    public void DuplicateAvailableDoesNotEraseKnownCapabilities()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Available(1);
        state.CapabilitiesChanged(1, true, true);
        state.Available(1);
        Assert.True(state.IsAvailable);
    }

    [Fact]
    public void InitialSnapshotCannotOverrideCallbackReceivedDuringSnapshotQuery()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Available(2);
        state.Lost(2);
        state.Initialize(1, true, true);
        Assert.False(state.IsAvailable);
    }

    [Fact]
    public void OfflineInitialSnapshotCannotOverrideNewValidatedNetwork()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: true);
        state.Available(2);
        state.CapabilitiesChanged(2, true, true);
        state.Initialize(null, false, false);
        Assert.True(state.IsAvailable);
    }

    [Fact]
    public void Api23LosingOneNetworkPreservesAnotherValidatedNetwork()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: false);
        state.Available(1);
        state.CapabilitiesChanged(1, true, true);
        state.Available(2);
        state.CapabilitiesChanged(2, true, true);
        state.Lost(1);
        Assert.True(state.IsAvailable);
        state.Lost(2);
        Assert.False(state.IsAvailable);
        state.CapabilitiesChanged(1, true, true);
        Assert.False(state.IsAvailable);
    }

    [Fact]
    public void Api23AnUnvalidatedAlternativeDoesNotKeepNetworkOnline()
    {
        var state = new NetworkAvailability(defaultNetworkOnly: false);
        state.Initialize(1, true, true);
        state.Available(1);
        state.Available(2);
        state.CapabilitiesChanged(2, true, false);
        state.Lost(1);
        Assert.False(state.IsAvailable);
    }
}
