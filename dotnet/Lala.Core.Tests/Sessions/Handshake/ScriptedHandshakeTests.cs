using System.Collections.Immutable;
using System.Reflection;
using System.Text.Json;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Handshake;
using Xunit;

namespace Lala.Core.Tests.Sessions.Handshake;

public sealed class ScriptedHandshakeTests
{
    private static Packet Login(int kind) => CandidateCommands.Login("synthetic_user", "fake_password", kind, 1, 2);
    private static RoleSnapshot Role(byte index = 1, bool locked = false) => new(index, "Synthetic", 1, 1,
        1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, locked, new(0, 0, 0, 0, 0, 0, 0, 0, 0));
    private static ServerEvent Roles(params RoleSnapshot[] roles) => new ServerLayoutEvent(new RoleListAvailableEvent(roles.ToImmutableArray()));
    private static ServerEvent Player() => new ServerLayoutEvent(new WorldPlayerEvent(
        new WorldPlayer(42, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, false, [], "Synthetic", 0)));
    private static Guid Id(ScriptedHandshake h) => h.Snapshot.Attempt;
    private static ScriptedHandshakeWrite? Complete(ScriptedHandshake h, ScriptedHandshakeWrite? write)
    {
        Assert.NotNull(write);
        using (write) return h.CompleteWrite(write.Attempt, write.Leg, write.Operation, write.Bytes, ScriptedWriteOutcome.Complete);
    }
    private static ScriptedHandshake At(int stage)
    {
        var h = new ScriptedHandshake(0xAD);
        if (stage == 0) return h;
        Complete(h, h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0)));
        if (stage == 1) return h;
        h.Observe(Id(h), HandshakeLeg.Verification, new LoginResultEvent(0, 0));
        if (stage == 2) return h;
        Complete(h, h.BeginLogin(Id(h), HandshakeLeg.Formal, Login(2)));
        if (stage == 3) return h;
        h.Observe(Id(h), HandshakeLeg.Formal, new LoginResultEvent(0, 2));
        if (stage == 4) return h;
        h.Observe(Id(h), HandshakeLeg.Formal, Roles(Role()));
        if (stage == 5) return h;
        Complete(h, h.SelectRole(Id(h), 1));
        return h;
    }
    private static Dictionary<string, byte[]> Vectors()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Lala.Core.Tests.Sessions.Handshake.python-vectors.json")!;
        using var doc = JsonDocument.Parse(stream);
        return doc.RootElement.EnumerateArray().ToDictionary(x => x.GetProperty("name").GetString()!, x => Convert.FromHexString(x.GetProperty("wire").GetString()!));
    }

    [Fact]
    public void PythonWireVectorsMatchEveryCandidate()
    {
        var vectors = Vectors();
        var packets = new Dictionary<string, Packet> { ["verification"] = Login(0), ["formal"] = Login(2),
            ["role1"] = CandidateCommands.SelectRole(1), ["role2"] = CandidateCommands.SelectRole(2),
            ["heartbeat"] = new(63, 5), ["map_ack"] = new(12, 1), ["appear_ack"] = new(3, 2) };
        foreach (var (key, packet) in packets) Assert.Equal(vectors[key], WireCodec.Encode(packet, 0xAD));
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public void HappyPathRequiresBothInitializationObservationsAndBothCompletedWrites(bool reverse)
    {
        using var h = At(6);
        var vectors = Vectors();
        Assert.Null(h.Observe(Id(h), HandshakeLeg.Formal, reverse ? new InitialDataCompleteEvent() : Player()));
        using var map = h.Observe(Id(h), HandshakeLeg.Formal, reverse ? Player() : new InitialDataCompleteEvent());
        Assert.NotNull(map); Assert.Equal(vectors["map_ack"], map.Bytes);
        Assert.Equal(HandshakePhase.MapAckWrite, h.Snapshot.Phase);
        using var appear = Complete(h, map);
        Assert.NotNull(appear); Assert.Equal(vectors["appear_ack"], appear.Bytes);
        Assert.Equal(HandshakePhase.AppearAckWrite, h.Snapshot.Phase);
        Complete(h, appear);
        Assert.Equal(HandshakePhase.ScriptedComplete, h.Snapshot.Phase);
        Assert.False(h.Snapshot.CanSendPackets); Assert.False(h.Snapshot.IsLive);
    }

    [Theory]
    [InlineData(1)] [InlineData(3)] [InlineData(4)] [InlineData(5)] [InlineData(6)]
    public void HeartbeatIsExactAndDoesNotAdvance(int stage)
    {
        using var h = At(stage); var phase = h.Snapshot.Phase;
        using var write = h.Observe(Id(h), stage == 1 ? HandshakeLeg.Verification : HandshakeLeg.Formal, new HeartbeatRequestEvent());
        Assert.NotNull(write); Assert.Equal(Vectors()["heartbeat"], write.Bytes);
        Complete(h, write); Assert.Equal(phase, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)] [InlineData(4)] [InlineData(5)]
    public void EarlyWorldEvidenceFailsClosed(int stage)
    {
        using var h = At(stage);
        h.Observe(Id(h), stage <= 2 ? HandshakeLeg.Verification : HandshakeLeg.Formal, Player());
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(1, 0, 1)] [InlineData(1, 1, 0)] [InlineData(1, 0, 2)]
    [InlineData(3, 0, 0)] [InlineData(3, 1, 2)] [InlineData(3, 0, 3)]
    public void RejectedOrWrongKindLoginFails(int stage, byte result, byte kind)
    {
        using var h = At(stage);
        h.Observe(Id(h), stage == 1 ? HandshakeLeg.Verification : HandshakeLeg.Formal, new LoginResultEvent(result, kind));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)] [InlineData(4)] [InlineData(5)]
    public void IncorrectReceiptRetiresWithoutReplay(int mode)
    {
        using var h = At(0); using var write = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(write);
        var bytes = write.Bytes.ToArray();
        if (mode == 0) bytes[0] ^= 1;
        h.CompleteWrite(mode == 1 ? Guid.NewGuid() : Id(h), mode == 2 ? HandshakeLeg.Formal : write.Leg,
            mode == 3 ? Guid.NewGuid() : write.Operation, mode == 4 ? bytes.AsSpan(1) : bytes,
            mode == 5 ? ScriptedWriteOutcome.Uncertain : ScriptedWriteOutcome.Complete);
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        Assert.Null(h.CompleteWrite(Id(h), write.Leg, write.Operation, write.Bytes, ScriptedWriteOutcome.Complete));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(1)] [InlineData(3)]
    public void UnsuccessfulWriteNeverAdvances(int outcome)
    {
        using var h = At(0); using var w = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(w); h.CompleteWrite(Id(h), w.Leg, w.Operation, w.Bytes, (ScriptedWriteOutcome)outcome);
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Fact]
    public void LoginReplyBeforeWriteCompletionFails()
    {
        using var h = At(0); using var w = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        h.Observe(Id(h), HandshakeLeg.Verification, new LoginResultEvent(0, 0));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public void UnavailableRolesFail(int mode)
    {
        using var h = At(4);
        h.Observe(Id(h), HandshakeLeg.Formal, mode switch {
            0 => Roles(), 1 => Roles(Role(1, true)), 2 => Roles(Role(), Role()), _ => Roles(Role(3)) });
        h.SelectRole(Id(h), 1); Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(3)] [InlineData(-1)]
    public void InvalidSelectionFails(int index)
    {
        using var h = At(5); Assert.Null(h.SelectRole(Id(h), index));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Fact]
    public void SelectionReplayAndCrossLegResultsFail()
    {
        using var h = At(6); Assert.Null(h.SelectRole(Id(h), 1));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        using var other = At(3); other.Observe(Id(other), HandshakeLeg.Verification, new LoginResultEvent(0, 0));
        Assert.Equal(HandshakePhase.Failed, other.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)] [InlineData(4)] [InlineData(5)] [InlineData(6)]
    public void CancellationHoldAndInputFailureAreLatchedAtEveryPhase(int stage)
    {
        for (int reason = 0; reason < 3; reason++)
        {
            using var h = At(stage);
            if (reason == 0) h.Cancel(); else if (reason == 1) h.Hold(); else h.EndInput();
            var phase = h.Snapshot.Phase;
            h.Observe(Id(h), HandshakeLeg.Formal, new LoginResultEvent(0, 2));
            Assert.Null(h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0)));
            Assert.Equal(phase, h.Snapshot.Phase);
        }
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public void HoldBetweenAckWritesPreventsCompletion(bool afterMap)
    {
        using var h = At(6); h.Observe(Id(h), HandshakeLeg.Formal, Player());
        using var map = h.Observe(Id(h), HandshakeLeg.Formal, new InitialDataCompleteEvent());
        using var appear = afterMap ? Complete(h, map) : null;
        h.Hold(); var write = afterMap ? appear : map; Assert.NotNull(write);
        Complete(h, write); Assert.Equal(HandshakePhase.Held, h.Snapshot.Phase);
    }

    [Fact]
    public void TransientWritesAreRedactedAndClearable()
    {
        using var h = At(0); var write = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(write); Assert.DoesNotContain("fake_password", write.ToString());
        Assert.DoesNotContain("synthetic_user", h.Snapshot.ToString());
        write.Dispose(); Assert.All(write.Bytes, b => Assert.Equal(0, b));
    }

    [Theory]
    [InlineData("")] [InlineData("é")]
    public void InvalidSyntheticCredentialsNeverBuild(string credential)
        => Assert.Throws<ProtocolException>(() => CandidateCommands.Login(credential, "fake", 0, 1, 2));

    [Fact]
    public void OversizeSyntheticCredentialNeverBuilds()
        => Assert.Throws<ProtocolException>(() => CandidateCommands.Login(new string('a', 256), "fake", 0, 1, 2));
    [Theory]
    [InlineData(0)] [InlineData(2)] [InlineData(6)]
    public void UndefinedConnectionLegCannotBypassVerification(int stage)
    {
        using var h = At(stage);
        Assert.Null(h.BeginLogin(Id(h), (HandshakeLeg)99, Login(2)));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Fact]
    public void NullOrDefaultSyntheticInputsFailClosed()
    {
        using var h = At(0);
        Assert.Null(h.BeginLogin(Id(h), HandshakeLeg.Verification, null!));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        using var roles = At(4); roles.Observe(Id(roles), HandshakeLeg.Formal, Roles(new RoleSnapshot[] { null! }));
        Assert.Equal(HandshakePhase.Failed, roles.Snapshot.Phase);
        using var defaults = At(4);
        defaults.Observe(Id(defaults), HandshakeLeg.Formal, new ServerLayoutEvent(new RoleListAvailableEvent(default)));
        Assert.Equal(HandshakePhase.Failed, defaults.Snapshot.Phase);
        using var observation = At(3); observation.Observe(Id(observation), HandshakeLeg.Formal, null!);
        Assert.Equal(HandshakePhase.Failed, observation.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)] [InlineData(4)] [InlineData(5)]
    public void RetirementAtEveryPendingWriteRejectsLateExactReceipts(int pendingStage)
    {
        for (int reason = 0; reason < 3; reason++)
        {
            using var h = At(pendingStage switch { 0 => 0, 1 => 2, 2 => 5, 5 => 3, _ => 6 });
            ScriptedHandshakeWrite? write;
            if (pendingStage == 0) write = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
            else if (pendingStage == 1) write = h.BeginLogin(Id(h), HandshakeLeg.Formal, Login(2));
            else if (pendingStage == 2) write = h.SelectRole(Id(h), 1);
            else if (pendingStage == 5) write = h.Observe(Id(h), HandshakeLeg.Formal, new HeartbeatRequestEvent());
            else
            {
                h.Observe(Id(h), HandshakeLeg.Formal, Player());
                write = h.Observe(Id(h), HandshakeLeg.Formal, new InitialDataCompleteEvent());
                if (pendingStage == 4) write = Complete(h, write);
            }
            Assert.NotNull(write);
            if (reason == 0) h.Cancel(); else if (reason == 1) h.Hold(); else h.EndInput();
            var phase = h.Snapshot.Phase; Complete(h, write);
            Assert.Equal(phase, h.Snapshot.Phase);
        }
    }

    [Fact]
    public void DuplicateReceiptAndForeignAttemptObservationRetire()
    {
        using var h = At(0); using var write = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(write);
        h.CompleteWrite(Id(h), write.Leg, write.Operation, write.Bytes, ScriptedWriteOutcome.Complete);
        h.CompleteWrite(Id(h), write.Leg, write.Operation, write.Bytes, ScriptedWriteOutcome.Complete);
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        using var other = At(3);
        other.Observe(Id(h), HandshakeLeg.Formal, new LoginResultEvent(0, 2));
        Assert.Equal(HandshakePhase.Failed, other.Snapshot.Phase);
    }

    [Fact]
    public void InitializationBeforeSelectionWriteCompletesFails()
    {
        using var h = At(5); using var write = h.SelectRole(Id(h), 1);
        h.Observe(Id(h), HandshakeLeg.Formal, new InitialDataCompleteEvent());
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Fact]
    public void LoginCandidateShapeIsStrict()
    {
        foreach (var packet in new Packet[] { new(1, 1), new(63, 7, [0]),
            new(63, 7, [0, 1, 1, 2, 1, 97, 1, 98]), new(63, 7, [0, 0, 1, 2, 1, 255, 1, 98]),
            new(63, 7, [0, 0, 1, 2, 1, 97, 1, 98, 0]) })
        {
            using var h = At(0); Assert.Null(h.BeginLogin(Id(h), HandshakeLeg.Verification, packet));
            Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        }
    }

    [Fact]
    public void CoordinatorLoginAndSelectionOutputsMatchPythonVectors()
    {
        using var h = At(0); var vectors = Vectors();
        using var verification = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(verification); Assert.Equal(vectors["verification"], verification.Bytes);
        Complete(h, verification);
        h.Observe(Id(h), HandshakeLeg.Verification, new LoginResultEvent(0, 0));
        using var formal = h.BeginLogin(Id(h), HandshakeLeg.Formal, Login(2));
        Assert.NotNull(formal); Assert.Equal(vectors["formal"], formal.Bytes); Complete(h, formal);
        h.Observe(Id(h), HandshakeLeg.Formal, new LoginResultEvent(0, 2));
        h.Observe(Id(h), HandshakeLeg.Formal, Roles(Role(2)));
        using var selection = h.SelectRole(Id(h), 2);
        Assert.NotNull(selection); Assert.Equal(vectors["role2"], selection.Bytes);
    }

    [Theory]
    [InlineData(0)] [InlineData(255)]
    public void OwnedEncodingMatchesWireCodecWithOtherXorKeys(int key)
    {
        using var h = new ScriptedHandshake(key); using var write = h.BeginLogin(Id(h), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(write); Assert.Equal(WireCodec.Encode(Login(0), key), write.Bytes);
    }

    [Fact]
    public void RoleOneOwnedBytesMatchPython()
    {
        using var h = At(5); using var write = h.SelectRole(Id(h), 1);
        Assert.NotNull(write); Assert.Equal(Vectors()["role1"], write.Bytes);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public void RolesCannotPrecedeFormalSuccess(int stage)
    {
        using var h = At(stage);
        h.Observe(Id(h), stage <= 2 ? HandshakeLeg.Verification : HandshakeLeg.Formal, Roles(Role()));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Fact]
    public void FormalLoginCannotSkipVerificationAndVerificationCannotRepeat()
    {
        using var fresh = At(0); Assert.Null(fresh.BeginLogin(Id(fresh), HandshakeLeg.Formal, Login(2)));
        Assert.Equal(HandshakePhase.Failed, fresh.Snapshot.Phase);
        using var verified = At(2); Assert.Null(verified.BeginLogin(Id(verified), HandshakeLeg.Verification, Login(0)));
        Assert.Equal(HandshakePhase.Failed, verified.Snapshot.Phase);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public void UncertainOrPartialWorldAckNeverCompletes(bool secondAck)
    {
        foreach (var outcome in new[] { ScriptedWriteOutcome.Partial, ScriptedWriteOutcome.Uncertain, ScriptedWriteOutcome.Failed })
        {
            using var h = At(6); h.Observe(Id(h), HandshakeLeg.Formal, Player());
            var write = h.Observe(Id(h), HandshakeLeg.Formal, new InitialDataCompleteEvent());
            if (secondAck) write = Complete(h, write);
            Assert.NotNull(write);
            using (write) h.CompleteWrite(Id(h), write.Leg, write.Operation, write.Bytes, outcome);
            Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        }
    }

    [Fact]
    public void HeartbeatBetweenWorldObservationsPreservesEvidence()
    {
        using var h = At(6); h.Observe(Id(h), HandshakeLeg.Formal, Player());
        Complete(h, h.Observe(Id(h), HandshakeLeg.Formal, new HeartbeatRequestEvent()));
        using var map = h.Observe(Id(h), HandshakeLeg.Formal, new InitialDataCompleteEvent());
        Assert.NotNull(map); Assert.Equal(HandshakePhase.MapAckWrite, h.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)] [InlineData(4)] [InlineData(5)]
    public void EarlyInitializationCannotBeReusedLater(int stage)
    {
        using var h = At(stage);
        h.Observe(Id(h), stage <= 2 ? HandshakeLeg.Verification : HandshakeLeg.Formal, new InitialDataCompleteEvent());
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
    }

    [Fact]
    public void NullPlayerAndUndefinedOutcomeFailClosed()
    {
        using var h = At(6); h.Observe(Id(h), HandshakeLeg.Formal, new ServerLayoutEvent(new WorldPlayerEvent(null!)));
        Assert.Equal(HandshakePhase.Failed, h.Snapshot.Phase);
        using var other = At(0); using var write = other.BeginLogin(Id(other), HandshakeLeg.Verification, Login(0));
        Assert.NotNull(write);
        other.CompleteWrite(Id(other), write.Leg, write.Operation, write.Bytes, (ScriptedWriteOutcome)99);
        Assert.Equal(HandshakePhase.Failed, other.Snapshot.Phase);
    }

    [Fact]
    public void MaximumValidSyntheticCredentialsAndTruncatedLengths()
    {
        using var h = At(0);
        var packet = CandidateCommands.Login(new string('a', 255), new string('b', 255), 0, 1, 2);
        using var write = h.BeginLogin(Id(h), HandshakeLeg.Verification, packet);
        Assert.NotNull(write); Assert.Equal(WireCodec.Encode(packet, 0xAD), write.Bytes);
        using var invalid = At(0);
        invalid.BeginLogin(Id(invalid), HandshakeLeg.Verification, new Packet(63, 7, [0, 0, 1, 2, 255, 97]));
        Assert.Equal(HandshakePhase.Failed, invalid.Snapshot.Phase);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)]
    public void RetirementRevokesHistoricalScriptedCompletion(int reason)
    {
        using var h = At(6); h.Observe(Id(h), HandshakeLeg.Formal, Player());
        Complete(h, Complete(h, h.Observe(Id(h), HandshakeLeg.Formal, new InitialDataCompleteEvent())));
        Assert.Equal(HandshakePhase.ScriptedComplete, h.Snapshot.Phase);
        if (reason == 0) h.Cancel(); else if (reason == 1) h.Hold(); else h.EndInput();
        Assert.NotEqual(HandshakePhase.ScriptedComplete, h.Snapshot.Phase);
        Assert.False(h.Snapshot.CanSendPackets); Assert.False(h.Snapshot.IsLive);
    }

}
