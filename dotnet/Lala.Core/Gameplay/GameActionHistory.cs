using System.Collections.Immutable;

namespace Lala.Core.Gameplay;

/// <summary>One bounded row per operation. Progress replaces that operation's row;
/// unrelated operations (including equal labels) retain their own outcome.</summary>
internal sealed class GameActionHistory
{
    private sealed record Row(object Operation, string Text);
    private ImmutableArray<Row> rows = [];
    private ImmutableArray<string> lines = [];
    internal uint? Role { get; private set; }
    internal ImmutableArray<string> Lines => lines;

    internal void Record(object operation, uint? role, GameActionStatus status)
    {
        if (Role != role) { rows = []; Role = role; }
        string text = $"{DateTimeOffset.UtcNow.ToOffset(TimeSpan.FromHours(8)):HH:mm:ss}　{status.Label}：{status.Message}";
        int index = -1;
        for (int i = 0; i < rows.Length; i++)
            if (ReferenceEquals(rows[i].Operation, operation)) { index = i; break; }
        var row = new Row(operation, text);
        rows = index < 0 ? rows.Add(row) : rows.SetItem(index, row);
        if (rows.Length > 200) rows = rows.RemoveRange(0, rows.Length - 200);
        lines = rows.Select(row => row.Text).ToImmutableArray();
    }
}
