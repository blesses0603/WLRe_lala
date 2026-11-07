using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.World.Tent;

/// <summary>Immutable receive-only observations. No tent placement or entry is inferred.</summary>
public abstract record TentEvent(byte Sub) : ServerEvent(65, Sub)
{
    public sealed override string ToString() => $"{Type} (S{Main}-{Sub})";
}

public sealed record TentCamp(uint OwnerId, ushort TentId, uint X, uint Y, byte Kind, byte Make)
{
    public override string ToString() => nameof(TentCamp);
}
public sealed record TentAddedEvent(TentCamp Tent) : TentEvent(1)
{
    public override string Type => "tent_added";
}
public sealed record TentSceneListEvent(ImmutableArray<TentCamp> Tents) : TentEvent(3)
{
    public override string Type => "tent_scene_list";
}
public sealed record TentRemovedEvent(uint OwnerId) : TentEvent(4)
{
    public override string Type => "tent_removed";
}
public sealed record TentAccessEvent(bool AccessOpen, bool ShowMessage) : TentEvent(7)
{
    public override string Type => "tent_access";
}
public sealed record TentErrorEvent(byte Code) : TentEvent(16)
{
    public override string Type => "tent_error";
}
public sealed record TentAppearanceEvent(byte Kind, byte Make) : TentEvent(18)
{
    public override string Type => "tent_appearance";
}
public sealed record TentLimitEvent() : TentEvent(2)
{
    public override string Type => "tent_limit";
}
public sealed record TentOwnerLeftEvent() : TentEvent(5)
{
    public override string Type => "tent_owner_left";
}
public sealed record TentEntryDeniedEvent() : TentEvent(8)
{
    public override string Type => "tent_entry_denied";
}
