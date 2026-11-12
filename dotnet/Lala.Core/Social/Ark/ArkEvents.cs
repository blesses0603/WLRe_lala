using System.Collections.Frozen;
using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Social.Ark;

/// <summary>Receive-only observations. No event authorizes dispatch, spending, answers or fights.</summary>
public abstract record ArkEvent(byte Main, byte Sub) : ServerEvent(Main, Sub)
{
    public sealed override string ToString() => $"{Type} (S{Main}-{Sub})";
}

public sealed record ArkAgent(byte Index, byte Id, ImmutableArray<byte> Skills, byte Planet);
public sealed record ArkShip(ushort Total, short Awarded, ushort Remaining, byte Planet, ImmutableArray<byte> Agents);
public sealed record ArkEventRow(byte Index, ushort Id, byte Kind, byte Planet, bool Main);
public sealed record ArkAward(byte Kind, uint Id, uint Value);
public sealed record ArkCollectedItem(ushort Id, ushort Count);

public sealed record ArkStarcoinEvent(uint Amount, uint Offset, bool Add, bool Show) : ArkEvent(75, 24)
{
    public override string Type => "ark_starcoin";
}
public sealed record ArkErrorEvent(byte Code) : ArkEvent(191, 0)
{
    public override string Type => "ark_error";
}
public sealed record ArkSnapshotEvent(byte Planet, ushort Explore, FrozenDictionary<byte, ArkAgent> Agents,
    ArkShip Ship) : ArkEvent(191, 1)
{
    public override string Type => "ark_snapshot";
}
public sealed record ArkEventsEvent(FrozenDictionary<byte, ArkEventRow> Events, bool New) : ArkEvent(191, 2)
{
    public override string Type => "ark_events";
}
public sealed record ArkDispatchEvent(byte Planet, byte Ship, ImmutableArray<byte> Agents, ushort Total) : ArkEvent(191, 3)
{
    public override string Type => "ark_dispatch";
}
public sealed record ArkCollectRewardEvent(ushort Total, ImmutableArray<ArkCollectedItem> Items) : ArkEvent(191, 4)
{
    public override string Type => "ark_collect_reward";
}
public sealed record ArkCollectEndEvent(byte Planet, byte Ship) : ArkEvent(191, 5)
{
    public override string Type => "ark_collect_end";
}
public sealed record ArkSkillEvent(byte Index, byte Skill, byte Level) : ArkEvent(191, 6)
{
    public override string Type => "ark_skill";
}
public sealed record ArkNewAgentEvent(byte Index, byte Id) : ArkEvent(191, 7)
{
    public override string Type => "ark_new_agent";
}
public sealed record ArkCompleteEvent(byte Index, ushort Id) : ArkEvent(191, 10)
{
    public override string Type => "ark_complete";
}
public sealed record ArkQuestionEvent(uint Question, ArkAward Award, ImmutableArray<uint> Options) : ArkEvent(191, 11)
{
    public override string Type => "ark_question";
}
public sealed record ArkAnswerResultEvent(bool Correct, byte Answer) : ArkEvent(191, 12)
{
    public override string Type => "ark_answer_result";
}
public sealed record ArkFightResultEvent(bool Won, ushort? Id = null, ImmutableArray<ArkAward>? Awards = null) : ArkEvent(191, 15)
{
    public override string Type => "ark_fight_result";
}
public sealed record ArkMainEventsEvent(FrozenDictionary<byte, ArkEventRow> Events) : ArkEvent(191, 16)
{
    public override string Type => "ark_main_events";
}
public sealed record ArkExploreEvent(byte Planet, ushort Explore) : ArkEvent(191, 17)
{
    public override string Type => "ark_explore";
}
public sealed record ArkMainAddedEvent(byte Planet, ushort Id, byte Kind) : ArkEvent(191, 18)
{
    public override string Type => "ark_main_added";
}
public sealed record ArkCollectCountEvent(byte Ship, short Count) : ArkEvent(191, 19)
{
    public override string Type => "ark_collect_count";
}
