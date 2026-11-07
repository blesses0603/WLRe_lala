using System.Collections.Immutable;
using System.Numerics;

namespace Lala.Core.Social.Ark;

/// <summary>A completed runtime_catalog read. Available means non-None, not trusted or active.</summary>
public sealed record ArkRuntimeObservation(bool Available, ArkCatalogToken? Token,
    ImmutableDictionary<uint, string> Texts)
{
    public static ArkRuntimeObservation Absent { get; } = new(false, null, ImmutableDictionary<uint, string>.Empty);
    public override string ToString() => nameof(ArkRuntimeObservation);
}

public enum ArkQuestionMemoryAvailability
{
    /// <summary>No adapter has run. Emit intent; never claim a store failure or a saved answer.</summary>
    Deferred,
    /// <summary>The caller has actual evidence the boundary is unavailable. Matches the
    /// caught _remember_question failure path; this value does not simulate a successful write.</summary>
    Unavailable
}

/// <summary>Player context is AFTER the local world observer; daily generation is explicit.
/// QuestionRuntime optionally represents apply_ark's second runtime_catalog read, allowing
/// an identity change between the current-question guard and text loading to fail closed.</summary>
public sealed record ArkReceiveContext(uint? PlayerRoleId, BigInteger DailyGeneration,
    ArkRuntimeObservation CurrentRuntime)
{
    public ArkRuntimeObservation? QuestionRuntime { get; init; }
    public ArkQuestionMemoryAvailability MemoryAvailability { get; init; } = ArkQuestionMemoryAvailability.Deferred;
    public override string ToString() => nameof(ArkReceiveContext);
}

public enum ArkQuestionMemoryOperation { Observe, Confirm, Reject }

/// <summary>Unexecuted storage intent only. Exact text/options, role, runtime token, daily
/// and Ark generations, selected index, and pending event bind the observation to its source.
/// Observe requires the full _remember_question observe/candidate/solver workflow, not just
/// a database read. Confirm is a server receipt to reconcile with stored conflicts, NOT a
/// persisted confirmation. Reject must preserve candidate quarantine semantics. An adapter
/// must revalidate all identities before use; no completion/replay API exists in this port.</summary>
public sealed record ArkQuestionMemoryIntent(ArkQuestionMemoryOperation Operation,
    ArkCatalogToken? Token, uint Role, BigInteger DailyGeneration, BigInteger ArkGeneration,
    ArkEventRow? Event, ArkQuestionSnapshot Question, uint? SelectedAnswer, bool RejectedCandidate)
{
    public override string ToString() => nameof(ArkQuestionMemoryIntent);
}

public sealed record ArkReceiveResult(ArkReceiveSnapshot State, ArkQuestionMemoryIntent? MemoryIntent = null)
{
    public override string ToString() => nameof(ArkReceiveResult);
}
