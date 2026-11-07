using System.Collections.Immutable;

namespace Lala.Core.Social;

/// <summary>Immutable projection of the retained Python State.guild. Empty is the initial
/// dictionary; a received roster is ready even with no members or a zero serial. Ready is
/// only an observation flag, never permission to send, join, donate, kick or chat.
/// Rank, chief, rules, signatures and other skipped profile fields are not state in Python.
/// The member mapping has no presentation-order contract.</summary>
public sealed record GuildEventSnapshot
{
    public static GuildEventSnapshot Empty { get; } = new();
    public bool Ready { get; init; }
    public string? Name { get; init; }
    public uint? Serial { get; init; }
    public byte? Level { get; init; }
    public ImmutableDictionary<uint, GuildMember> Members { get; init; } =
        ImmutableDictionary<uint, GuildMember>.Empty;

    // Do not put guild/member names into incidental diagnostic output.
    public override string ToString() => $"GuildEventSnapshot (ready={Ready}, members={Members.Count})";
}
