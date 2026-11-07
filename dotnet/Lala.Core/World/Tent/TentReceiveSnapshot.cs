namespace Lala.Core.World.Tent;

/// <summary>Caller-supplied pending/entry evidence consumed by apply_tent. This reducer
/// neither creates an action nor owns a clock or deadline. Optional fields preserve the
/// distinction between an ordinary pending operation and furniture-backed entry evidence.</summary>
public sealed record TentActionObservation(string Action)
{
    public double? Due { get; init; }
    public ushort? SourceScene { get; init; }
    public bool? FurnitureReceived { get; init; }
    public override string ToString() => nameof(TentActionObservation);
}

/// <summary>Immutable defaults/apply_tent receive projection. A hidden tent is not a
/// retracted tent; deployed/interior/return evidence is cleared only by the source's
/// specific transitions. No action, timeout, exit resolution or permission is implemented.</summary>
public sealed record TentReceiveSnapshot
{
    public static TentReceiveSnapshot Empty { get; } = new();
    public ushort? Scene { get; init; }
    public bool SceneKnown { get; init; }
    public bool Visible { get; init; }
    public ushort? DeployedScene { get; init; }
    public ushort? TentId { get; init; }
    public uint? X { get; init; }
    public uint? Y { get; init; }
    public byte? Kind { get; init; }
    public byte? Make { get; init; }
    public bool Inside { get; init; }
    public bool? AccessOpen { get; init; }
    public TentActionObservation? Pending { get; init; }
    public bool Uncertain { get; init; }
    public string Status { get; init; } = "帳篷狀態待伺服器同步";
    public ushort? InteriorScene { get; init; }
    public ushort? ReturnScene { get; init; }
    public TentActionObservation? EntryContext { get; init; }
    public override string ToString() => nameof(TentReceiveSnapshot);
}
