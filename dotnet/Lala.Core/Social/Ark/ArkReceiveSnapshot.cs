using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.State;

namespace Lala.Core.Social.Ark;

/// <summary>Observed runtime identity, not catalog provenance or authorization.</summary>
public sealed record ArkCatalogToken(bool Attempted, string? IdentityKey)
{
    public override string ToString() => nameof(ArkCatalogToken);
}

public sealed record ArkStarcoinSnapshot(bool Ready = false, bool Reliable = false,
    uint? Amount = null, BigInteger Revision = default);
public sealed record ArkDispatchQuote(byte Planet, byte Agent, ushort Duration, BigInteger Price)
{
    // Preserve unconsumed quote fields without introducing a planner.
    public StateValue OtherFields { get; init; } = StateValue.Map();
}

/// <summary>Imported evidence of an existing operation. No constructor/API sends, reserves,
/// claims a candidate or starts an operation. OtherFields preserves unconsumed caller evidence.</summary>
public sealed record ArkPendingObservation(string Kind, uint Role, ArkCatalogToken? Token,
    BigInteger DailyGeneration)
{
    public double? Due { get; init; }
    public ArkDispatchQuote? Quote { get; init; }
    public uint Balance { get; init; }
    public bool Paid { get; init; }
    public bool ShipAck { get; init; }
    public ArkEventRow? Event { get; init; }
    public bool Complete { get; init; }
    public bool Result { get; init; }
    public ImmutableArray<ArkAward> Awards { get; init; } = [];
    public StateValue OtherFields { get; init; } = StateValue.Map();
    public override string ToString() => nameof(ArkPendingObservation);
}

public sealed record ArkQuestionSnapshot(uint Question, ArkAward Award, ImmutableArray<uint> Options,
    string Text, ImmutableArray<string> Labels)
{
    public byte? Selected { get; init; }
    public uint? KnownAnswer { get; init; }
    // Null retains a missing Python field; empty string retains an explicitly cleared field.
    public string? AnswerSource { get; init; }
    public string? AnswerKind { get; init; }
    public string? CandidateReason { get; init; }
    public string? CandidateRevision { get; init; }
    public string? CandidateSource { get; init; }
    public bool? SelectedCandidate { get; init; }
    public override string ToString() => nameof(ArkQuestionSnapshot);
}

/// <summary>Immutable receive-only defaults/apply_ark projection. Null Ship represents the
/// source's empty dictionary, not a known idle ship. All counters retain Python integer range.
/// Enabled/settings/quote/answers are carried observations, never permission to act.</summary>
public sealed record ArkReceiveSnapshot
{
    public static ArkReceiveSnapshot Empty { get; } = new();
    public bool Enabled { get; init; } = true;
    public bool DispatchEnabled { get; init; } = true;
    public bool FightsEnabled { get; init; } = true;
    public bool QuestionsEnabled { get; init; } = true;
    public ArkPendingObservation? Pending { get; init; }
    public bool Uncertain { get; init; }
    public uint? Role { get; init; }
    public bool Ready { get; init; }
    public bool EventsReady { get; init; }
    public byte Planet { get; init; }
    public ushort Explore { get; init; }
    public ImmutableDictionary<byte, ArkAgent> Agents { get; init; } = ImmutableDictionary<byte, ArkAgent>.Empty;
    public ArkShip? Ship { get; init; }
    public ImmutableDictionary<byte, ArkEventRow> Events { get; init; } = ImmutableDictionary<byte, ArkEventRow>.Empty;
    public ImmutableDictionary<byte, ArkEventRow> MainEvents { get; init; } = ImmutableDictionary<byte, ArkEventRow>.Empty;
    // main_added stores the source event dictionary, including its type key.
    public ImmutableHashSet<byte> AddedMainEvents { get; init; } = [];
    public ArkStarcoinSnapshot Starcoin { get; init; } = new();
    public BigInteger Budget { get; init; } = 120;
    public byte Hours { get; init; } = 1;
    public BigInteger Reserved { get; init; }
    public BigInteger Confirmed { get; init; }
    public BigInteger SettingsRevision { get; init; }
    public ArkCatalogToken? CatalogToken { get; init; }
    public StateValue Rows { get; init; } = StateValue.List();
    public StateValue Quote { get; init; } = StateValue.Null;
    public ArkQuestionSnapshot? Question { get; init; }
    public ImmutableDictionary<string, uint> Answers { get; init; } = ImmutableDictionary<string, uint>.Empty;
    public StateValue Attempted { get; init; } = StateValue.List();
    public BigInteger Generation { get; init; }
    public string QuestionStoreStatus { get; init; } = "已審核候選仍可能答錯；伺服器確認答案另行保存";
    public string Status { get; init; } = "等待星之方舟與每日任務同步";
    public override string ToString() => nameof(ArkReceiveSnapshot);
}
