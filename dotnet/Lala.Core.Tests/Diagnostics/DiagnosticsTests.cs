using Lala.Core.Diagnostics;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Diagnostics;

public class DiagnosticsTests
{
    [Theory]
    [MemberData(nameof(PythonDiagnosticVectors.CommandCases), MemberType = typeof(PythonDiagnosticVectors))]
    public void CommandNameMatchesPython(object? value, string? expected, string? error, string diagnostic)
    {
        var command = new Dictionary<string, object?> { ["type"] = value, ["password"] = "synthetic-never-log" };
        if (error is not null)
        {
            var exception = Assert.Throws<ProtocolException>(() => CommandEnvelope.Validate(command));
            Assert.Equal(error, exception.Message);
            Assert.DoesNotContain("synthetic-never-log", exception.ToString());
        }
        else Assert.Equal(expected, CommandEnvelope.Validate(command));
        Assert.Equal(diagnostic, CommandEnvelope.RejectedType(command));
    }
    [Fact]
    public void NonMappingsRejectedWithoutFormattingPayload()
    {
        foreach (var invalid in new object?[] { null, 7, "private-command-payload", new object[0], new SecretObject() })
        {
            var error = Assert.Throws<ProtocolException>(() => CommandEnvelope.Validate(invalid));
            Assert.Equal("指令格式錯誤：預期含有 type 的資料物件", error.Message);
            Assert.Equal("invalid", CommandEnvelope.RejectedType(invalid));
        }
        Assert.Throws<ProtocolException>(() => CommandEnvelope.Validate(new Dictionary<string, object?>()));
    }
    private sealed class SecretObject
    {
        public override string ToString() => throw new Exception("Must not format arbitrary payload");
    }
    [Fact]
    public void HealthEvidenceSequenceMatchesPythonIncludingWallJumpAndClosure()
    {
        double now = 100;
        var wall = DateTimeOffset.FromUnixTimeSeconds(1700000000);
        var events = new List<ConnectionEvidence>();
        var health = new ConnectionHealth(events.Add, () => now, () => wall);
        foreach (var step in PythonDiagnosticVectors.HealthSequence())
        {
            string op = (string)step[0]!; now = 100 + Convert.ToDouble(step[1]);
            int before = events.Count;
            switch (op)
            {
                case "publish": health.Publish((bool)step[2]!); break;
                case "receive": health.Received(); break;
                case "wall_back": wall = wall.AddDays(-1); break;
                case "close": health.Close(ConnectionCloseReason.ServerClosed); break;
            }
            if (step[3] is null) Assert.Equal(before, events.Count);
            else
            {
                Assert.Equal(before + 1, events.Count);
                var e = events[^1];
                Assert.Equal((string)step[3]!, e.StatusName);
                Assert.Equal(Convert.ToDouble(step[4]), e.AgeSeconds);
                double? expectedWall = step[5] is null ? null : Convert.ToDouble(step[5]);
                Assert.Equal(expectedWall, e.LastReceivedAtUtc?.ToUnixTimeMilliseconds() / 1000.0);
                Assert.Equal(Convert.ToInt64(step[6]), e.Packets);
            }
            Assert.Equal((bool)step[7]!, health.Closed);
        }
    }
    [Fact]
    public void QuietNeverClosesAndReceivedResumesEvidence()
    {
        double now = 0; var events = new List<ConnectionEvidence>();
        var health = new ConnectionHealth(events.Add, () => now);
        health.Publish(); Assert.Equal("waiting", events[^1].StatusName);
        now = 120; health.Publish(); Assert.Equal("quiet", events[^1].StatusName); Assert.False(health.Closed);
        health.Received(); health.Publish(true); Assert.Equal("receiving", events[^1].StatusName);
        Assert.False(health.Closed); Assert.Equal(0, events[^1].AgeSeconds);
    }
    [Fact]
    public void ExplicitIntervalKeepaliveAndUtcEvidence()
    {
        double now = 10; var events = new List<ConnectionEvidence>();
        var wall = new DateTimeOffset(2026, 11, 7, 22, 0, 0, TimeSpan.FromHours(8));
        var health = new ConnectionHealth(events.Add, () => now, () => wall, 5, 2) { Keepalive = true };
        health.Received(); health.Publish();
        Assert.Equal(TimeSpan.Zero, events[^1].LastReceivedAtUtc!.Value.Offset);
        Assert.True(events[^1].Keepalive);
        now = 11; Assert.False(health.Publish());
        now = 12; Assert.True(health.Publish());
        now = 15; health.Publish(); Assert.Equal("quiet", events[^1].StatusName); Assert.False(health.Closed);
        health.Close(ConnectionCloseReason.Stopped); Assert.Equal("closed", events[^1].StatusName);
        Assert.Equal(ConnectionCloseReason.Stopped, events[^1].Reason);
    }
    [Fact]
    public void BackwardClockAgeIsClampedAndForcedEmissionBypassesInterval()
    {
        double now = 10; ConnectionEvidence? latest = null;
        var health = new ConnectionHealth(e => latest = e, () => now);
        health.Received(); health.Publish(); now = 9;
        Assert.False(health.Publish()); Assert.True(health.Publish(true)); Assert.Equal(0, latest!.AgeSeconds);
    }
}
