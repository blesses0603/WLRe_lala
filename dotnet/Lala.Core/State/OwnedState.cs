using System.Collections.Immutable;

namespace Lala.Core.State;

/// <summary>
/// Single-writer foundation, not the complete game State or an event reducer. Construct on
/// the network owner thread. Scopes are synchronous and must not span an await. Only
/// immutable snapshots/values may cross threads. Unscoped owner writes are coordinator writes.
/// </summary>
public sealed class OwnedState
{
    // Thread identity avoids granting ownership to a later thread with a recycled numeric ID.
    private readonly Thread writer = Thread.CurrentThread;
    private ImmutableDictionary<string, StateValue> fields;
    private MutationScope? scope;

    public OwnedState(IEnumerable<KeyValuePair<string, StateValue>>? initialFields = null)
    {
        fields = initialFields is null ? ImmutableDictionary.Create<string, StateValue>(StringComparer.Ordinal)
            : StateValue.Map(initialFields).MapValue;
        foreach (string name in fields.Keys) ValidateField(name);
    }

    public string? CurrentOwner { get { AssertWriter(); return scope?.Owner; } }

    public StateValue this[string field]
    {
        get { AssertWriter(); return fields[field]; }
        set
        {
            AssertCanWrite(field);
            ArgumentNullException.ThrowIfNull(value);
            fields = fields.SetItem(field, value);
        }
    }

    public StateEditor Edit(string field)
    {
        AssertWriter();
        ValidateField(field);
        if (!fields.ContainsKey(field)) throw new KeyNotFoundException($"Unknown state field: {field}");
        return new(this, field, []);
    }

    public StateSnapshot Snapshot()
    {
        AssertWriter();
        // Sharing immutable nodes does not share any mutable state with the publisher.
        return new(fields);
    }

    public void AssertWriter()
    {
        if (!ReferenceEquals(Thread.CurrentThread, writer))
            throw new InvalidOperationException("State may only be accessed by its owning network thread; use snapshots and commands");
    }

    internal void AssertCanWrite(string field)
    {
        AssertWriter();
        ValidateField(field);
        if (scope is not null && !StateOwnership.Fields[scope.Owner].Contains(field))
            throw new InvalidOperationException($"{scope.Owner} cannot mutate State.{field}");
    }

    private static void ValidateField(string field)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(field);
        if (field.StartsWith('_')) throw new ArgumentException("State fields cannot use internal names.", nameof(field));
    }

    /// <summary>Inner service scopes replace, rather than union with, outer grants.</summary>
    public IDisposable Editing(string owner)
    {
        AssertWriter();
        ArgumentNullException.ThrowIfNull(owner);
        if (!StateOwnership.Fields.ContainsKey(owner))
            throw new ArgumentException("Unknown state mutation owner.", nameof(owner));
        scope = new(this, owner, scope);
        return scope;
    }

    /// <summary>Synchronous equivalent of the Python writes(owner) decorator. No rollback is implied.</summary>
    public void Write(string owner, Action<OwnedState> action)
    {
        ArgumentNullException.ThrowIfNull(action);
        using var editing = Editing(owner);
        action(this);
    }

    internal void Change(string field, ImmutableArray<StatePathPart> path, bool replaceTarget,
        Func<StateValue, StateValue> change)
    {
        AssertCanWrite(field);
        var updated = ChangeAt(fields[field], 0);
        fields = fields.SetItem(field, updated);
        return;

        StateValue ChangeAt(StateValue current, int depth)
        {
            if (depth == path.Length) return change(current);
            var part = path[depth];
            if (part.Key is { } key) return current.SetKey(key, ChangeAt(current[key], depth + 1));
            var items = current.SequenceValue;
            if (current.Kind == StateValueKind.Tuple && replaceTarget && depth == path.Length - 1)
                throw new InvalidOperationException("Tuple members cannot be replaced directly.");
            return current.WithSequence(items.SetItem(part.Index, ChangeAt(items[part.Index], depth + 1)));
        }
    }

    private sealed class MutationScope(OwnedState state, string owner, MutationScope? previous) : IDisposable
    {
        private bool disposed;
        internal string Owner { get; } = owner;

        public void Dispose()
        {
            state.AssertWriter();
            if (disposed) return;
            if (!ReferenceEquals(state.scope, this))
                throw new InvalidOperationException("State mutation scopes must be disposed in reverse entry order.");
            state.scope = previous;
            disposed = true;
        }
    }
}

internal readonly record struct StatePathPart(string? Key, int Index);

/// <summary>
/// A retained path handle is safe: every read/write checks its owner thread and every write
/// checks the current service scope against the root field. Paths resolve the current tree,
/// not a stale mutable object. Collection indexes use C# non-negative indexing.
/// </summary>
public sealed class StateEditor
{
    private readonly OwnedState state;
    private readonly string field;
    private readonly ImmutableArray<StatePathPart> path;

    internal StateEditor(OwnedState state, string field, ImmutableArray<StatePathPart> path) =>
        (this.state, this.field, this.path) = (state, field, path);

    public StateValue Value
    {
        get
        {
            var current = state[this.field];
            foreach (var part in path) current = part.Key is { } key ? current[key] : current[part.Index];
            return current;
        }
    }

    public StateEditor At(string key)
    {
        state.AssertWriter();
        ArgumentNullException.ThrowIfNull(key);
        return new(state, field, path.Add(new(key, 0)));
    }

    public StateEditor At(int index)
    {
        state.AssertWriter();
        ArgumentOutOfRangeException.ThrowIfNegative(index);
        return new(state, field, path.Add(new(null, index)));
    }

    public void Set(StateValue value)
    {
        state.AssertCanWrite(field);
        ArgumentNullException.ThrowIfNull(value);
        state.Change(field, path, true, _ => value);
    }

    public void SetItem(string key, StateValue value)
    {
        state.AssertCanWrite(field);
        ArgumentNullException.ThrowIfNull(key);
        ArgumentNullException.ThrowIfNull(value);
        state.Change(field, path, false, current => current.SetKey(key, value));
    }

    public bool RemoveKey(string key)
    {
        state.AssertCanWrite(field);
        ArgumentNullException.ThrowIfNull(key);
        bool removed = false;
        state.Change(field, path, false, current =>
        {
            removed = current.MapValue.ContainsKey(key);
            return current.RemoveKey(key);
        });
        return removed;
    }

    public void SetItem(int index, StateValue value)
    {
        state.AssertCanWrite(field);
        ArgumentNullException.ThrowIfNull(value);
        state.Change(field, path, false, current =>
        {
            current.RequireList();
            return current.WithSequence(current.SequenceValue.SetItem(index, value));
        });
    }

    public void Append(StateValue value) => Extend([value]);

    public void Extend(IEnumerable<StateValue> values)
    {
        state.AssertCanWrite(field);
        // Materialize before changing the root: failed enumeration cannot partially edit state.
        var additions = StateValue.List(values).SequenceValue;
        state.Change(field, path, false, current =>
        {
            current.RequireList();
            return current.WithSequence(current.SequenceValue.AddRange(additions));
        });
    }

    public void Insert(int index, StateValue value)
    {
        state.AssertCanWrite(field);
        ArgumentNullException.ThrowIfNull(value);
        state.Change(field, path, false, current =>
        {
            current.RequireList();
            return current.WithSequence(current.SequenceValue.Insert(index, value));
        });
    }

    public StateValue RemoveAt(int index)
    {
        StateValue? removed = null;
        state.Change(field, path, false, current =>
        {
            current.RequireList();
            removed = current[index];
            return current.WithSequence(current.SequenceValue.RemoveAt(index));
        });
        return removed!;
    }

    public void Reverse() => state.Change(field, path, false, current =>
    {
        current.RequireList();
        return current.WithSequence(current.SequenceValue.Reverse().ToImmutableArray());
    });

    public void Clear() => state.Change(field, path, false, current => current.Kind switch
    {
        StateValueKind.Map => StateValue.Map(),
        StateValueKind.List => StateValue.List(),
        _ => throw new InvalidOperationException("Only maps and lists can be cleared.")
    });
}
