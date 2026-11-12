using System.Collections.Immutable;

namespace Lala.Core.World.Eve;

public sealed record EveDoorName(string? Name, string NameBytes, bool NameValid);

// NewEvent condition para_value is uint32; result para_value is int32. Do not
// merge these into a signed field or infer whether a condition currently passes.
public readonly record struct EveDoorConditionData(byte Id, byte ParaMain, ushort ParaKind,
    ushort ParaStyle, ushort ParaType, byte ParaOperator, uint ParaValue, byte GroupNumber,
    uint ParaClass1, uint ParaClass2);
public readonly record struct EveDoorResultData(byte Id, byte ParaMain, ushort ParaKind,
    ushort ParaStyle, ushort ParaType, byte ParaOperator, int ParaValue, byte GroupNumber,
    uint ParaClass1, uint ParaClass2);
public sealed record EveDoorCondition(EveDoorConditionData Data, ImmutableArray<EveDoorResultData> Results);
public sealed record EveDoorConvey(ushort ConveyId, ushort Destination, uint ArrivalX, uint ArrivalY, EveDoorName Name);
public sealed record EveDoorTransfer(EveDoorConvey Convey, EveDoorConditionData Condition);
public sealed record EveDoorTouchEvent(ushort Index, byte OccurType, EveDoorName Name,
    ImmutableArray<EveDoorCondition> Conditions, ImmutableArray<EveDoorTransfer> ConveyTransfers,
    ImmutableArray<ushort> MissingConveyIds, bool DestinationDecoded);
public sealed record EveDoorRow(ushort Index, EveDoorName Name, uint X, uint Y, ImmutableArray<byte> EventIds,
    uint Right, uint Bottom, byte SignType, uint SignX, uint SignY, uint ColX, uint ColY, uint ColZ,
    ImmutableArray<byte> TouchEventIds, ImmutableArray<EveDoorTouchEvent> TouchEventRecords);
public sealed record EveDoorScene(ushort SceneId, ImmutableArray<EveDoorRow> Doors);

/// <summary>Detached, immutable offline layout observations. DestinationDecoded means only
/// that the referenced convey rows were found; it never authorizes travel or event execution.
/// No source bytes, credentials, network or runtime state are retained.</summary>
public sealed class EveDoorProjection
{
    public ImmutableArray<EveDoorScene> Scenes { get; }
    public int DoorCount { get; }
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    public bool AuthorizesTravel => false;
    public bool AuthorizesRuntime => false;
    internal EveDoorProjection(ImmutableArray<EveDoorScene> scenes, int doorCount) =>
        (Scenes, DoorCount) = (scenes, doorCount);
}
