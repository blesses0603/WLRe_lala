using System.Text.Json;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.State;

public class StateOwnershipTests
{
    private static StateValue S(object? value) => StateValue.Scalar(value);
    private static OwnedState NewState() => new(StateValue.Map(
        ("inventory", StateValue.Map(("items", StateValue.List(StateValue.Map(("count", S(5))))))),
        ("expedition", StateValue.Map(("status", S("idle")))),
        ("auto_battle", StateValue.Map(("enabled", S(false)))),
        ("player", StateValue.Map(("x", S(3)))),
        ("roles", StateValue.List())).MapValue);

    [Theory]
    [MemberData(nameof(PythonStateVectors.Grants), MemberType = typeof(PythonStateVectors))]
    public void EveryPythonFieldGrantGuardsReplacementAndNestedWrites(string owner, string[] allowed, string[] denied)
    {
        Assert.Equal(allowed.Order(), StateOwnership.Fields[owner].Order());
        var state = new OwnedState(allowed.Concat(denied).Select(field => KeyValuePair.Create(field,
            StateValue.Map(("nested", StateValue.List(StateValue.Map(("value", S(0)))))))));
        // Handles captured before a scope do not carry write authorization into it.
        var handles = allowed.Concat(denied).ToDictionary(field => field, state.Edit);
        using var editing = state.Editing(owner);
        foreach (var field in allowed)
        {
            handles[field].At("nested").At(0).SetItem("value", S(1));
            handles[field].At("nested").Append(S(2));
            state[field] = S(3);
            Assert.Equal(3, state[field].ScalarValue);
        }
        foreach (var field in denied)
        {
            foreach (Action write in new Action[]
            {
                () => handles[field].At("nested").At(0).SetItem("value", S(1)),
                () => handles[field].At("nested").Append(S(2)),
                () => state[field] = S(3)
            })
                Assert.Equal($"{owner} cannot mutate State.{field}", Assert.Throws<InvalidOperationException>(write).Message);
            Assert.Equal(0, state[field]["nested"][0]["value"].ScalarValue);
        }
    }

    [Fact]
    public void PublishedServiceGrantsCannotBeMutated()
    {
        Assert.Equal(11, StateOwnership.Fields.Count);
        Assert.Throws<NotSupportedException>(() =>
            ((IDictionary<string, System.Collections.Immutable.ImmutableHashSet<string>>)StateOwnership.Fields).Clear());
        Assert.Throws<NotSupportedException>(() => ((ISet<string>)StateOwnership.Fields["expedition"]).Add("player"));
        var state = NewState();
        using var scope = state.Editing("expedition");
        Assert.Throws<InvalidOperationException>(() => state["Inventory"] = S(0));
        Assert.Throws<InvalidOperationException>(() => state["player"] = S(0));
    }

    [Fact]
    public void NestedServiceErrorsRestoreAuthorityWithoutRollingBackSuccessfulWrites()
    {
        var state = NewState();
        var trace = new List<string>();
        void Record(string label, Action action)
        {
            try { action(); trace.Add(label + ":ok"); }
            catch (InvalidOperationException error) { trace.Add(label + ":" + error.Message); }
        }
        using (state.Editing("expedition"))
        {
            Record("inventory", () => state.Edit("inventory").At("items").At(0).SetItem("count", S(4)));
            Record("outer_denied", () => state.Edit("auto_battle").SetItem("enabled", S(true)));
            Assert.Throws<FormatException>(() => state.Write("auto_battle", inner =>
            {
                Record("inner", () => inner.Edit("auto_battle").SetItem("enabled", S(true)));
                Record("inner_denied", () => inner.Edit("expedition").SetItem("status", S("wrong")));
                throw new FormatException("synthetic service failure");
            }));
            Assert.Equal("expedition", state.CurrentOwner);
            Record("restored_denied", () => state.Edit("auto_battle").SetItem("enabled", S(false)));
            Record("restored", () => state.Edit("expedition").SetItem("status", S("done")));
        }
        Assert.Null(state.CurrentOwner);
        Record("unscoped", () => state.Edit("player").SetItem("x", S(4)));
        var snapshot = state.Snapshot();
        var nestedHandle = state.Edit("inventory").At("items").At(0);
        OnThread(() =>
        {
            Record("thread_write", () => nestedHandle.SetItem("count", S(0)));
            Record("thread_snapshot", () => state.Snapshot());
        });
        Assert.Equal(PythonStateVectors.NestedTrace, trace);
        using var expected = JsonDocument.Parse(PythonStateVectors.NestedSnapshot);
        foreach (var property in expected.RootElement.EnumerateObject())
            AssertJson(property.Value, snapshot[property.Name]);
    }

    [Fact]
    public void InputCollectionsAndSnapshotsNeverExposeMutableReferences()
    {
        var items = new[] { S(1), S(2) };
        var map = new Dictionary<string, StateValue> { ["items"] = StateValue.List(items) };
        var initial = new Dictionary<string, StateValue> { ["inventory"] = StateValue.Map(map) };
        var state = new OwnedState(initial);
        var before = state.Snapshot();
        items[0] = S(99);
        map.Clear();
        initial.Clear();
        Assert.Equal(1, before["inventory"]["items"][0].ScalarValue);
        state.Edit("inventory").At("items").SetItem(0, S(3));
        state.Edit("inventory").SetItem("extra", S(true));
        Assert.Equal(1, before["inventory"]["items"][0].ScalarValue);
        Assert.False(before["inventory"].MapValue.ContainsKey("extra"));
        Assert.Equal(3, state["inventory"]["items"][0].ScalarValue);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, StateValue>)before.Fields).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, StateValue>)before["inventory"].MapValue).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<StateValue>)before["inventory"]["items"].SequenceValue)[0] = S(4));
        OnThread(() => Assert.Equal(1, before["inventory"]["items"][0].ScalarValue));
    }

    [Fact]
    public void ArbitraryMutableScalarObjectsAreRejectedWithoutCallingTheirCode()
    {
        foreach (var unsupported in new object[] { new object(), new byte[1], new List<int>(), new Dictionary<string, int>(), new PoisonObject() })
            Assert.Throws<ArgumentException>(() => StateValue.Scalar(unsupported));
        Assert.Null(StateValue.Null.ScalarValue);
        Assert.Equal("狀態", S("狀態").ScalarValue);
        Assert.Equal(new System.Numerics.BigInteger(ulong.MaxValue), S(new System.Numerics.BigInteger(ulong.MaxValue)).ScalarValue);
        Assert.Throws<ArgumentNullException>(() => StateValue.List([null!]));
        Assert.Throws<ArgumentNullException>(() => StateValue.Map(("invalid", null!)));
        Assert.Throws<ArgumentException>(() => new OwnedState(new Dictionary<string, StateValue> { ["_scope"] = S(1) }));
    }

    [Fact]
    public void OwnerReadsWritesScopesAndSnapshotCreationRejectOtherThreads()
    {
        var state = NewState();
        var handle = state.Edit("inventory").At("items");
        var snapshot = state.Snapshot();
        OnThread(() =>
        {
            foreach (Action operation in new Action[]
            {
                state.AssertWriter,
                () => _ = state["player"],
                () => state["player"] = S(0),
                () => state.Edit("player"),
                () => state.Snapshot(),
                () => state.Editing("expedition"),
                () => state.Write("expedition", _ => throw new Exception("Must not run")),
                () => _ = state.CurrentOwner,
                () => _ = handle.Value,
                () => handle.At(0),
                () => handle.At("key"),
                () => handle.Set(S(0)),
                () => handle.SetItem(0, S(0)),
                () => handle.Append(S(0)),
                () => handle.Extend([]),
                () => handle.Insert(0, S(0)),
                () => handle.RemoveAt(0),
                handle.Reverse,
                handle.Clear,
                () => handle.SetItem("wrong_type", S(0)),
                () => handle.RemoveKey("missing")
            })
                Assert.Contains("owning network thread", Assert.Throws<InvalidOperationException>(operation).Message);
            // Publications can intentionally seed a different, independently owned state.
            var independent = new OwnedState(snapshot.Fields);
            independent.Edit("inventory").At("items").Clear();
            Assert.Empty(independent["inventory"]["items"].SequenceValue);
            Assert.Single(snapshot["inventory"]["items"].SequenceValue);
        });
        Assert.Single(state["inventory"]["items"].SequenceValue);
    }

    [Fact]
    public void ScopeTokensRejectOutOfOrderAndWrongThreadDisposalWithoutLosingAuthority()
    {
        var state = NewState();
        var outer = state.Editing("expedition");
        var inner = state.Editing("expedition");
        Assert.Throws<InvalidOperationException>(outer.Dispose);
        Assert.Equal("expedition", state.CurrentOwner);
        OnThread(() => Assert.Throws<InvalidOperationException>(inner.Dispose));
        Assert.Equal("expedition", state.CurrentOwner);
        inner.Dispose();
        inner.Dispose();
        Assert.Equal("expedition", state.CurrentOwner);
        Assert.Throws<InvalidOperationException>(() => state.Edit("player").Clear());
        outer.Dispose();
        outer.Dispose();
        Assert.Null(state.CurrentOwner);
        state.Edit("player").Clear();
    }

    [Fact]
    public void InvalidScopeEntryDoesNotReplaceCurrentAuthority()
    {
        var state = NewState();
        using (state.Editing("expedition"))
        {
            Assert.Throws<ArgumentException>(() => state.Editing("Expedition"));
            Assert.Throws<ArgumentException>(() => state.Editing("missing"));
            Assert.Throws<ArgumentNullException>(() => state.Editing(null!));
            Assert.Equal("expedition", state.CurrentOwner);
            Assert.Throws<InvalidOperationException>(() => state["player"] = S(0));
        }
        Assert.Null(state.CurrentOwner);
    }

    [Fact]
    public void NoOpCollectionMutationsStillRequireCurrentFieldAuthority()
    {
        var state = NewState();
        var roles = state.Edit("roles");
        var player = state.Edit("player");
        using var scope = state.Editing("expedition");
        foreach (Action mutation in new Action[]
        {
            roles.Clear, roles.Reverse, () => roles.Extend([]),
            () => roles.RemoveAt(0), () => roles.Insert(0, S(0)),
            () => roles.SetItem(0, S(0)), () => player.RemoveKey("absent"),
            () => player.SetItem("x", S(3)), () => roles.Set(StateValue.List())
        }) Assert.Contains("cannot mutate", Assert.Throws<InvalidOperationException>(mutation).Message);
    }

    [Fact]
    public void ListAndMapOperationsPreserveOrderAndPublishOnlyCompletedEdits()
    {
        var state = NewState();
        var roles = state.Edit("roles");
        roles.Append(S(1));
        roles.Extend([S(2), S(3)]);
        roles.Insert(1, S(4));
        roles.SetItem(0, S(5));
        Assert.Equal(3, roles.RemoveAt(3).ScalarValue);
        roles.Reverse();
        Assert.Equal(new object[] { 2, 4, 5 }, roles.Value.SequenceValue.Select(v => v.ScalarValue));
        var checkpoint = state.Snapshot();
        Assert.Throws<IndexOutOfRangeException>(() => roles.RemoveAt(99));
        Assert.Throws<ArgumentOutOfRangeException>(() => roles.SetItem(-1, S(7)));
        Assert.Throws<ArgumentOutOfRangeException>(() => roles.Insert(99, S(7)));
        Assert.Throws<ArgumentOutOfRangeException>(() => roles.At(-1));
        Assert.Throws<FormatException>(() => roles.Extend(BrokenSequence()));
        Assert.Throws<ArgumentNullException>(() => roles.Append(null!));
        Assert.Same(checkpoint.Fields, state.Snapshot().Fields);
        var player = state.Edit("player");
        Assert.False(player.RemoveKey("absent"));
        Assert.True(player.RemoveKey("x"));
        player.SetItem("label", S("同行"));
        Assert.Equal("同行", player.Value["label"].ScalarValue);
        player.Clear(); roles.Clear();
        Assert.Empty(player.Value.MapValue);
        Assert.Empty(roles.Value.SequenceValue);
    }

    [Fact]
    public void TupleMembersAreImmutableButContainersInsideTuplesRetainRootFieldOwnership()
    {
        var state = NewState();
        state.Edit("inventory").SetItem("tuple", StateValue.Tuple(StateValue.Map(("count", S(1))), StateValue.List(S(2))));
        var tuple = state.Edit("inventory").At("tuple");
        var before = state.Snapshot();
        tuple.At(0).SetItem("count", S(3));
        tuple.At(1).Append(S(4));
        Assert.Equal(3, tuple.Value[0]["count"].ScalarValue);
        Assert.Equal(1, before["inventory"]["tuple"][0]["count"].ScalarValue);
        Assert.Single(before["inventory"]["tuple"][1].SequenceValue);
        Assert.Equal(StateValueKind.Tuple, tuple.Value.Kind);
        Assert.Throws<InvalidOperationException>(() => tuple.SetItem(0, S(0)));
        Assert.Throws<InvalidOperationException>(() => tuple.At(0).Set(S(0)));
        Assert.Throws<InvalidOperationException>(() => tuple.Append(S(0)));
        Assert.Throws<InvalidOperationException>(tuple.Clear);
        using (state.Editing("tent"))
            Assert.Contains("cannot mutate State.inventory", Assert.Throws<InvalidOperationException>(() => tuple.At(0).SetItem("count", S(99))).Message);
    }

    [Fact]
    public void RetainedPathResolvesNewValueAndDoesNotCarryOldAuthority()
    {
        var state = NewState();
        var path = state.Edit("inventory").At("items").At(0);
        state["inventory"] = StateValue.Map(("items", StateValue.List(StateValue.Map(("count", S(10))))));
        path.SetItem("count", S(11));
        Assert.Equal(11, state["inventory"]["items"][0]["count"].ScalarValue);
        using (state.Editing("tent"))
            Assert.Throws<InvalidOperationException>(() => path.Clear());
        state["inventory"] = StateValue.Map();
        var before = state.Snapshot();
        Assert.Throws<KeyNotFoundException>(() => path.SetItem("count", S(12)));
        Assert.Same(before.Fields, state.Snapshot().Fields);
    }

    [Fact]
    public void TopLevelFieldsCanBeAddedOnlyByUnscopedOwnerOrTheirGrantedService()
    {
        var state = new OwnedState();
        using (state.Editing("expedition"))
        {
            state["inventory"] = StateValue.Map();
            Assert.Throws<InvalidOperationException>(() => state["player"] = StateValue.Map());
        }
        state["player"] = StateValue.Map();
        Assert.Throws<ArgumentException>(() => state["_writer"] = S(0));
        Assert.Throws<ArgumentException>(() => state[""] = S(0));
        Assert.Throws<KeyNotFoundException>(() => state.Edit("absent"));
    }

    private static IEnumerable<StateValue> BrokenSequence()
    {
        yield return S(99);
        throw new FormatException("Synthetic enumeration failure");
    }

    private sealed class PoisonObject
    {
        public override string ToString() => throw new Exception("Do not format arbitrary state payloads");
    }

    private static void OnThread(Action action)
    {
        Exception? error = null;
        var thread = new Thread(() => { try { action(); } catch (Exception caught) { error = caught; } }) { IsBackground = true };
        thread.Start();
        Assert.True(thread.Join(TimeSpan.FromSeconds(10)), "State test worker did not finish.");
        if (error is not null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error).Throw();
    }

    private static void AssertJson(JsonElement expected, StateValue actual)
    {
        switch (expected.ValueKind)
        {
            case JsonValueKind.Object:
                Assert.Equal(expected.EnumerateObject().Count(), actual.MapValue.Count);
                foreach (var property in expected.EnumerateObject()) AssertJson(property.Value, actual[property.Name]);
                break;
            case JsonValueKind.Array:
                Assert.Equal(expected.GetArrayLength(), actual.SequenceValue.Length);
                for (int i = 0; i < expected.GetArrayLength(); i++) AssertJson(expected[i], actual[i]);
                break;
            case JsonValueKind.String: Assert.Equal(expected.GetString(), actual.ScalarValue); break;
            case JsonValueKind.Number: Assert.Equal(expected.GetInt32(), actual.ScalarValue); break;
            case JsonValueKind.True: Assert.Equal(true, actual.ScalarValue); break;
            case JsonValueKind.False: Assert.Equal(false, actual.ScalarValue); break;
            case JsonValueKind.Null: Assert.Null(actual.ScalarValue); break;
            default: throw new InvalidOperationException("Unexpected fixture JSON.");
        }
    }
}
