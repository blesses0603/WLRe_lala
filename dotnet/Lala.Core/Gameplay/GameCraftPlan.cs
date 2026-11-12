using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Gameplay;

public sealed record GameCraftPlanEntry(ushort ItemId, int Batches);

/// <summary>Account-lifetime progress only; a stored UI plan never proves a server receipt.</summary>
internal sealed class CraftPlanCursor(ImmutableArray<GameCraftPlanEntry> entries)
{
    internal ImmutableArray<GameCraftPlanEntry> Entries { get; } = entries;
    internal int Added { get; private set; }
    internal GameCraftPlanEntry? Next => Added < Entries.Length ? Entries[Added] : null;
    internal static void Validate(ImmutableArray<GameCraftPlanEntry> entries)
    {
        if (entries.IsDefault || entries.Length > 512 || entries.Any(e => e is null || e.ItemId == 0 || e.Batches is < 1 or > 255))
            throw new ProtocolException("製作清單最多 512 項，每項需有效物品 ID 與 1～255 批。");
    }
    internal void ConfirmAdded(int expectedIndex)
    {
        if (expectedIndex != Added || Next is null) throw new ProtocolException("製作清單進度已改變，已停止重複加入。");
        Added++;
    }
}
