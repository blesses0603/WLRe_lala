using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World;
using Lala.Core.World.Eve;
using Xunit;

namespace Lala.Core.Tests.Automation;

public sealed class NpcChoiceCommandTests
{
    private static EveInteractionRow Interaction(byte form = 1) => new(7, form, 0,
        [new(9, 100, 1, 1), new(99, 101, 1, 3), new(2, 102, 1, 3), new(8, 0, 0, 4)]);
    private static readonly IReadOnlyDictionary<ushort, TalkDataRow> Talks = new Dictionary<ushort, TalkDataRow>
    { [100] = new("測試標題", 0), [101] = new("選項一", 0), [102] = new("選項二", 0) };
    private static EveV115Indexes Indexes(EveInteractionRow? interaction = null) => new([new(101, [], [interaction ?? Interaction()])], false, true, 0, 1);
    private static OfflineRuntimeCandidate Catalog(EveInteractionRow? interaction = null) =>
        // Only choice-parser fields are used in this packet-plan test. This is no runtime activation.
        new(Indexes(interaction), new Dictionary<ushort, ItemDataRow>(), Talks, new Dictionary<uint, string>(), null!, new Dictionary<ushort, StageDataRow>(), null!,
            new Dictionary<ushort, string>(), null!, new Dictionary<ushort, ExpeditionNpcData>(), new Dictionary<string, string>(), null!);
    private static ServiceStateSnapshot State(string phase = "choice_unavailable") => new(local: new(
        new SessionEventSnapshot { Phase = "world_ready", InitialDataComplete = true, EventFlow = new() { Blocked = true },
            NpcDialogue = new() { Active = true, Phase = phase, Scene = 101, NpcId = 10, NpcIndex = 1, EffectType = 6, EffectPacket = 42, OptionIndex = 7 } },
        new WorldEventSnapshot { Phase = "world_ready", Player = new(17, 0, 101, 20, 30, 0, 0, 0, 0, 0, 0, false, [], "測試", 0) }));

    [Fact]
    public void Normal_choices_use_display_order_and_bind_scene_text_and_exact_effect()
    {
        var menu = GameNpcChoices.Read(Indexes(), Talks, 101, 7)!;
        Assert.Equal("測試標題", menu.Title); Assert.Equal(new[] { 0, 1 }, menu.Options.Select(o => o.Index));
        var state = State(); var action = new GameAction("npc", "choose", 102, 1, Count: 7, Scene: 101, Key: "42");
        var plan = ManualGameCommands.Plan(action, state, Catalog(), 0, "synthetic");
        Assert.Equal(20, plan.Packet.Main); Assert.Equal(9, plan.Packet.Sub); Assert.Equal(new byte[] { 31 }, plan.Packet.Payload.ToArray());
        Assert.True(plan.ContinueNpcChoice);
        var pending = plan.Begin(state).Local.Session.NpcDialogue;
        Assert.Equal((byte)1, pending.SelectedChoice); Assert.True(pending.ChoiceContinuationPending);
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Target = 101 }, state, Catalog(), 0, "synthetic"));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Key = "41" }, state, Catalog(), 0, "synthetic"));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Scene = 102 }, state, Catalog(), 0, "synthetic"));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Count = 8 }, state, Catalog(), 0, "synthetic"));
    }

    [Fact]
    public void Shops_and_ambiguous_or_missing_text_menus_never_become_normal_choices()
    {
        Assert.Null(GameNpcChoices.Read(Indexes(Interaction(3)), Talks, 101, 7));
        Assert.Null(GameNpcChoices.Read(Indexes(), new Dictionary<ushort, TalkDataRow>(), 101, 7));
        Assert.Null(GameNpcChoices.Read(new([new(101, [], [Interaction(), Interaction()])], false, true, 0, 2), Talks, 101, 7));
        var altered = Interaction() with { Items = [new(1, 100, 1, 1), new(2, 101, 2, 3)] };
        Assert.Null(GameNpcChoices.Read(Indexes(altered), Talks, 101, 7));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(new("npc", "close_choice", Count: 7, Scene: 101, Key: "42"), State(), Catalog(Interaction(3)), 0, "synthetic"));
    }

    [Fact]
    public void Dialogue_continue_contains_the_required_zero_byte_and_close_is_distinct()
    {
        var next = ManualGameCommands.Plan(new("npc", "next"), State("talk"), Catalog(), 0, "synthetic");
        Assert.Equal(6, next.Packet.Sub); Assert.Equal(new byte[] { 0 }, next.Packet.Payload.ToArray());
        var close = ManualGameCommands.Plan(new("npc", "close_choice", Count: 7, Scene: 101, Key: "42"), State(), Catalog(), 0, "synthetic");
        Assert.Equal(9, close.Packet.Sub); Assert.Equal(new byte[] { 40 }, close.Packet.Payload.ToArray()); Assert.False(close.ContinueNpcChoice);
    }
}
