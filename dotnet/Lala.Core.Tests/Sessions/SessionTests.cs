using Lala.Core.Sessions;
using Xunit;
namespace Lala.Core.Tests.Sessions;
public class SessionTests
{
    [Fact] public void NewSessionRejectsStaleResults()
    {
        var session = new AccountSession();
        var old = session.Begin("one", "server-a");
        var next = session.Begin("two", "server-b");
        Assert.False(session.ConfirmResources(old.Generation, "1296", "1296", true));
        Assert.False(session.AllowsResourceGate(old.Generation, "walk"));
        Assert.True(session.ConfirmResources(next.Generation, "1296", "1296", true));
        Assert.True(session.AllowsResourceGate(next.Generation, "walk"));
    }
    [Fact] public void HoldCannotBeClearedInSameSession()
    {
        var session = new AccountSession(); var state = session.Begin("one", "a");
        Assert.True(session.ConfirmResources(state.Generation, "v", "v", true));
        Assert.True(session.Hold(state.Generation));
        Assert.False(session.ConfirmResources(state.Generation, "v", "v", true));
        Assert.False(session.AllowsResourceGate(state.Generation, "walk"));
        Assert.True(session.AllowsResourceGate(state.Generation, "stop_walk"));
        session.Disconnect(); Assert.False(session.AllowsResourceGate(state.Generation, "chat"));
    }
    [Theory]
    [InlineData("", "", true)] [InlineData("a", "b", true)] [InlineData("a", "a", false)]
    public void UnverifiedResourcesLatchHold(string official, string database, bool integrity)
    {
        var session = new AccountSession(); var state = session.Begin("one", "a");
        Assert.False(session.ConfirmResources(state.Generation, official, database, integrity));
        Assert.Equal(SessionPhase.Held, session.Snapshot.Phase);
    }
    [Theory]
    [InlineData("chat", null, null, true)]
    [InlineData("craft", "stop_auto", null, true)]
    [InlineData("daily_tasks", "auto", false, true)]
    [InlineData("daily_tasks", "auto", null, false)]
    [InlineData("daily_tasks", "auto", true, false)]
    [InlineData("automatic_flows", null, false, true)]
    [InlineData("automatic_flows", null, true, false)]
    [InlineData("walk", null, null, false)]
    [InlineData("unknown", "pause", false, false)]
    public void HoldPolicy(string kind, string? action, bool? enabled, bool expected)
        => Assert.Equal(expected, ResourceSafetyPolicy.AllowsDuringHold(kind, action, enabled));
}
