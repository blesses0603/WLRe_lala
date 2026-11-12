using System.Collections;
using System.Collections.Frozen;
using System.Collections.Immutable;

namespace Lala.Core.Catalogs;

// Source order is independent of frozen lookup enumeration. No mutable dictionary is exposed.
internal sealed class OrderedCatalog<TKey, TValue> : IReadOnlyDictionary<TKey, TValue> where TKey : notnull
{
    private readonly ImmutableArray<TKey> order;
    private readonly FrozenDictionary<TKey, TValue> rows;
    internal OrderedCatalog(Dictionary<TKey, TValue> source, IEnumerable<TKey> sourceOrder)
    {
        order = sourceOrder.ToImmutableArray();
        rows = source.ToFrozenDictionary();
    }
    public int Count => order.Length;
    public IEnumerable<TKey> Keys => order;
    public IEnumerable<TValue> Values => order.Select(key => rows[key]);
    public TValue this[TKey key] => rows[key];
    public bool ContainsKey(TKey key) => rows.ContainsKey(key);
    public bool TryGetValue(TKey key, out TValue value) => rows.TryGetValue(key, out value!);
    public IEnumerator<KeyValuePair<TKey, TValue>> GetEnumerator() =>
        order.Select(key => KeyValuePair.Create(key, rows[key])).GetEnumerator();
    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}
