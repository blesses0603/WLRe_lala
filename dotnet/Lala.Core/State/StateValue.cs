using System.Collections.Immutable;
using System.Numerics;

namespace Lala.Core.State;

public enum StateValueKind { Scalar, Map, List, Tuple }

/// <summary>
/// Closed, deeply immutable state data. No caller-owned arrays, dictionaries or arbitrary
/// objects are retained. String map keys are intentional; this is not a Python object serializer.
/// </summary>
public sealed class StateValue
{
    private readonly object? value;
    private StateValue(StateValueKind kind, object? value) => (Kind, this.value) = (kind, value);

    public StateValueKind Kind { get; }
    public static StateValue Null { get; } = new(StateValueKind.Scalar, null);

    /// <summary>Only immutable Python-like scalar values are accepted. Unknown objects fail closed.</summary>
    public static StateValue Scalar(object? value) => value switch
    {
        null => Null,
        string or bool or char or sbyte or byte or short or ushort or int or uint or long or ulong
            or float or double or decimal or BigInteger => new(StateValueKind.Scalar, value),
        _ => throw new ArgumentException("State scalars must be immutable text, booleans or numbers.", nameof(value))
    };

    public static StateValue Map(params (string Key, StateValue Value)[] entries) =>
        Map(entries.Select(entry => KeyValuePair.Create(entry.Key, entry.Value)));

    public static StateValue Map(IEnumerable<KeyValuePair<string, StateValue>> entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        var builder = ImmutableDictionary.CreateBuilder<string, StateValue>(StringComparer.Ordinal);
        foreach (var (key, item) in entries)
        {
            ArgumentNullException.ThrowIfNull(key);
            ArgumentNullException.ThrowIfNull(item);
            builder.Add(key, item);
        }
        return new(StateValueKind.Map, builder.ToImmutable());
    }

    public static StateValue List(params StateValue[] items) => List((IEnumerable<StateValue>)items);
    public static StateValue List(IEnumerable<StateValue> items) => Sequence(StateValueKind.List, items);
    public static StateValue Tuple(params StateValue[] items) => Tuple((IEnumerable<StateValue>)items);
    public static StateValue Tuple(IEnumerable<StateValue> items) => Sequence(StateValueKind.Tuple, items);

    private static StateValue Sequence(StateValueKind kind, IEnumerable<StateValue> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        var builder = ImmutableArray.CreateBuilder<StateValue>();
        foreach (var item in items)
        {
            ArgumentNullException.ThrowIfNull(item);
            builder.Add(item);
        }
        return new(kind, builder.ToImmutable());
    }

    public object? ScalarValue => Kind == StateValueKind.Scalar ? value :
        throw new InvalidOperationException("This state value is not a scalar.");
    public ImmutableDictionary<string, StateValue> MapValue => Kind == StateValueKind.Map ?
        (ImmutableDictionary<string, StateValue>)value! :
        throw new InvalidOperationException("This state value is not a map.");
    public ImmutableArray<StateValue> SequenceValue => Kind is StateValueKind.List or StateValueKind.Tuple ?
        (ImmutableArray<StateValue>)value! : throw new InvalidOperationException("This state value is not a sequence.");
    public StateValue this[string key] => MapValue[key];
    public StateValue this[int index] => SequenceValue[index];

    internal StateValue SetKey(string key, StateValue item) => new(StateValueKind.Map, MapValue.SetItem(key, item));
    internal StateValue RemoveKey(string key) => new(StateValueKind.Map, MapValue.Remove(key));
    internal StateValue WithSequence(ImmutableArray<StateValue> items) => new(Kind, items);
    internal void RequireList()
    {
        if (Kind != StateValueKind.List) throw new InvalidOperationException("Only list members can be changed directly.");
    }
}
