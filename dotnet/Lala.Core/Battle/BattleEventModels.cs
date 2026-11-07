using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.Battle;

public readonly record struct BattleSlot(byte Col, byte Row)
{
    public override string ToString() => Col.ToString(CultureInfo.InvariantCulture) + ":" +
        Row.ToString(CultureInfo.InvariantCulture);
}

/// <summary>A local send observation, not a request, acknowledgement, or permission to send.
/// The caller must only supply this after a successful send. Optional fields retain the
/// minimal observations accepted by the Python reducer as well as skill/item observations.</summary>
public sealed record BattleCommandSentEvent(byte Col, byte Row, byte? TargetCol = null,
    byte? TargetRow = null, ushort? SkillId = null, ushort? ItemId = null, byte? BagIndex = null)
{
    public string Type => "battle_command_sent";
    public BattleSlot Slot => new(Col, Row);
}

public enum BattleCommandStatus { Sent, Resolved }

public sealed record BattleCommandSnapshot(BattleCommandSentEvent Event, BattleCommandStatus Status)
{
    public BattleSlot Slot => Event.Slot;
}

/// <summary>The immutable layout remains available as received. Hp/Sp are the current
/// authoritative values, including UInt32 S51 replacements that exceed the layout's UInt16 SP.
/// Attributes and exit flags belong to this slot occupant and disappear on a unit replacement.</summary>
public sealed record BattleUnitState
{
    internal BattleUnitState(BattleUnit layout)
    {
        Layout = layout;
        Hp = layout.Hp;
        Sp = layout.Sp;
    }

    public BattleUnit Layout { get; }
    /// <summary>Current S11-252 appearance; Layout retains the originally received unit.
    /// A new unit record clears this overlay. Sparse appearance never changes HP/SP.</summary>
    public ImmutableArray<EquipmentAppearance>? EquipmentOverrides { get; internal init; }
    public ImmutableArray<EquipmentAppearance> Equips => EquipmentOverrides ?? Layout.Equips;
    public BattleSlot Slot => new(Layout.Col, Layout.Row);
    public uint Hp { get; internal init; }
    public uint Sp { get; internal init; }
    public ImmutableDictionary<byte, uint> Attributes { get; internal init; } =
        ImmutableDictionary<byte, uint>.Empty;
    public bool Exited { get; internal init; }
}

/// <summary>A pure battle-domain publication, not a complete session or account State.
/// Null optional scalars mean that the Python field has not been observed yet. Commands,
/// units and last actions preserve source insertion/report order. No clocks, transport,
/// mutable dictionaries, player HP, or speculative combat calculations are retained.</summary>
public sealed record BattleEventSnapshot
{
    public static BattleEventSnapshot Empty { get; } = new();

    public BigInteger BattleCount { get; internal init; }
    public BigInteger Actions { get; internal init; }
    public byte? WinnerSide { get; internal init; }
    public byte? Stage { get; internal init; }
    public byte? FightNumber { get; internal init; }
    public ushort? Round { get; internal init; }
    public bool? Active { get; internal init; }
    public byte? WarStyle { get; internal init; }
    public ImmutableArray<BattleUnitState> Units { get; internal init; } = [];
    public ImmutableArray<BattleCommandSnapshot> Commands { get; internal init; } = [];
    public bool HasCommands { get; internal init; }
    public ImmutableArray<AttackAction> LastActions { get; internal init; } = [];
    public bool HasLastActions { get; internal init; }

    public BattleUnitState? UnitAt(BattleSlot slot) => Units.FirstOrDefault(unit => unit.Slot == slot);
    public BattleCommandSnapshot? CommandAt(BattleSlot slot) => Commands.FirstOrDefault(command => command.Slot == slot);
}
