using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Social.Ark;

/// <summary>Pure bounded defaults/apply_ark port. Decode before reducing. No clock, store,
/// candidate solver, catalog activation, command, scheduler, session, inventory or packet send.
/// Question persistence is explicit output; it cannot establish an accepted/known answer.</summary>
public static class ArkReceiveReducer
{
    public const string DeferredMemoryStatus = "題庫處理尚未接入；未讀寫或驗證答案，請人工選答";
    public const string UnavailableMemoryStatus = "題庫無法讀寫或驗證，請人工選答；本次答案未保存";

    public static ArkReceiveResult Apply(ArkReceiveSnapshot state, ServerEvent observation, ArkReceiveContext context)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(context);
        if (observation.Type == "role_list_available") return new(ArkReceiveSnapshot.Empty);
        if (observation is ServerLayoutEvent { Event: WorldPlayerEvent world })
            return new((state.Role is not null && state.Role != world.Player.RoleId ? ArkReceiveSnapshot.Empty : state)
                with { Role = world.Player.RoleId });
        if (observation is not ArkEvent || state.Role is null or 0 || state.Role != context.PlayerRoleId) return new(state);
        var pending = state.Pending;
        if (observation is ArkQuestionEvent or ArkAnswerResultEvent && pending is { Kind: "question" } &&
            (!context.CurrentRuntime.Available || pending.Token != context.CurrentRuntime.Token ||
             pending.Role != context.PlayerRoleId || pending.Role != state.Role || pending.DailyGeneration != context.DailyGeneration))
            return new(Freeze(state, "問答回覆的角色／版本／每日任務週期已改變"));

        var next = state;
        switch (observation)
        {
            case ArkStarcoinEvent coin:
                BigInteger delta = coin.Add ? coin.Offset : -(BigInteger)coin.Offset;
                var reliable = coin.Offset == 0 || state.Starcoin.Ready && state.Starcoin.Reliable &&
                    state.Starcoin.Amount is { } amount && amount + delta == coin.Amount;
                next = state with { Starcoin = new(true, reliable, coin.Amount, state.Starcoin.Revision + 1) };
                if (pending is { Kind: "dispatch", Quote: { } quote })
                    next = reliable && delta == -quote.Price && coin.Offset != 0 && !pending.Paid &&
                           coin.Amount == pending.Balance - quote.Price
                        ? next with { Pending = pending with { Paid = true } }
                        : Freeze(next, "派遣期間星力異動無法唯一確認");
                break;
            case ArkSnapshotEvent snapshot:
                if (pending is not null) next = Freeze(next, "方舟操作期間收到完整快照");
                next = next with { Ready = true, Planet = snapshot.Planet, Explore = snapshot.Explore,
                    Agents = snapshot.Agents.ToImmutableDictionary(), Ship = snapshot.Ship };
                break;
            case ArkEventsEvent events:
                if (pending?.Kind is "fight" or "question") next = Freeze(next, "操作期間方舟事件清單更新");
                next = next with { Events = events.Events.ToImmutableDictionary(), EventsReady = true,
                    Generation = state.Generation + 1, Attempted = StateValue.List() };
                break;
            case ArkMainEventsEvent events:
                next = state with { MainEvents = events.Events.ToImmutableDictionary(), AddedMainEvents = [] };
                break;
            case ArkExploreEvent explore:
                next = state with { Planet = explore.Planet, Explore = explore.Explore };
                break;
            case ArkMainAddedEvent added:
                next = state with { MainEvents = state.MainEvents.SetItem(added.Planet,
                    new(added.Planet, added.Id, added.Kind, added.Planet, true)),
                    AddedMainEvents = state.AddedMainEvents.Add(added.Planet) };
                break;
            case ArkDispatchEvent dispatch:
                if (!state.Ready || dispatch.Agents.Any(i => i != 0 && !state.Agents.ContainsKey(i)))
                    return new((pending is not null ? Freeze(state, "派遣回覆含未同步的情報員") : state) with { Ready = false });
                if (pending is { Kind: "dispatch", Quote: { } expected })
                    next = pending.ShipAck || dispatch.Planet != expected.Planet ||
                        !dispatch.Agents.SequenceEqual(new byte[] { expected.Agent, 0 }) || dispatch.Total != expected.Duration
                        ? Freeze(next, "派遣回覆與要求不符") : next with { Pending = pending with { ShipAck = true } };
                var dispatchedAgents = next.Agents;
                foreach (var index in dispatch.Agents)
                    if (index != 0) dispatchedAgents = dispatchedAgents.SetItem(index, dispatchedAgents[index] with { Planet = dispatch.Planet });
                next = next with { Ship = new(dispatch.Total, 0, dispatch.Total, dispatch.Planet, dispatch.Agents), Agents = dispatchedAgents };
                break;
            case ArkCollectEndEvent end:
                if (state.Ship?.Planet != end.Planet)
                    return new((pending is not null ? Freeze(state, "搜索艇結束回覆星球不符") : state) with { Ready = false });
                var returnedAgents = state.Agents;
                foreach (var index in state.Ship.Agents)
                    if (returnedAgents.TryGetValue(index, out var agent)) returnedAgents = returnedAgents.SetItem(index, agent with { Planet = 0 });
                next = state with { Agents = returnedAgents, Ship = new(0, 0, 0, 0, [0, 0]) };
                break;
            case ArkCollectCountEvent count when state.Ship is not null:
                next = state with { Ship = state.Ship with { Awarded = count.Count } };
                break;
            case ArkSkillEvent skill:
                if (state.Agents.TryGetValue(skill.Index, out var skilled))
                    next = state with { Agents = state.Agents.SetItem(skill.Index, skilled with { Skills = skilled.Skills.SetItem(skill.Skill - 1, skill.Level) }) };
                if (pending?.Kind == "dispatch") next = Freeze(next, "派遣期間情報員技能變更");
                break;
            case ArkNewAgentEvent agent:
                if (state.Agents.ContainsKey(agent.Index))
                    next = (pending is not null ? Freeze(state, "新增情報員索引與既有資料衝突") : state) with { Ready = false };
                else next = state with { Agents = state.Agents.Add(agent.Index, new(agent.Index, agent.Id, [1, 1], 0)) };
                break;
            case ArkCompleteEvent complete:
                var group = complete.Id >= 10000 ? state.MainEvents : state.Events;
                if (group.TryGetValue(complete.Index, out var row) && row.Id == complete.Id)
                    next = complete.Id >= 10000 ? state with { MainEvents = group.SetItem(complete.Index, row with { Id = 0 }) }
                        : state with { Events = group.SetItem(complete.Index, row with { Id = 0 }) };
                else if (pending is not null) next = Freeze(next, "完成事件與伺服器清單不符");
                if (pending?.Kind is "fight" or "question")
                {
                    if (pending.Event is { } expectedEvent && complete.Index == expectedEvent.Index && complete.Id == expectedEvent.Id)
                    {
                        // Python may update a detached local pending dictionary after freeze.
                        if (next.Pending is not null) next = next with { Pending = pending with { Complete = true } };
                    }
                    else next = Freeze(next, "收到其他方舟事件的完成通知");
                }
                break;
            case ArkFightResultEvent fight when pending?.Kind == "fight":
                if (!fight.Won) next = state with { Pending = null, Enabled = false, SettingsRevision = state.SettingsRevision + 1,
                    Status = "方舟戰鬥未獲勝，已停止自動接續" };
                else if (pending.Result || fight.Id != pending.Event?.Id ||
                    !(fight.Awards ?? []).Where(a => a.Kind != 0).SequenceEqual(pending.Awards))
                    next = Freeze(state, "戰鬥事件獎勵與同版資料不符");
                else next = state with { Pending = pending with { Result = true } };
                break;
            case ArkQuestionEvent question:
                if (pending?.Kind != "question" || state.Question is not null)
                    return new(Freeze(state, "收到無法對應的方舟問答"));
                if (question.Award.Kind is not (6 or 22) || question.Award.Kind == 6 && question.Award.Id != 8)
                    return new(Freeze(state, "問答獎勵種類未支援"));
                var runtime = context.QuestionRuntime ?? context.CurrentRuntime;
                var texts = runtime.Available && runtime.Token == pending.Token ? runtime.Texts : ImmutableDictionary<uint, string>.Empty;
                if (!texts.ContainsKey(question.Question) || question.Options.Any(i => !texts.ContainsKey(i)))
                    return new(Freeze(state, "問答缺少同版題目文字"));
                var loaded = new ArkQuestionSnapshot(question.Question, question.Award, question.Options,
                    texts[question.Question], [.. question.Options.Select(i => texts[i])]);
                next = state with { Question = loaded, Pending = pending with { Due = null },
                    Status = "已載入題目；自動作答依題庫狀態及問答開關判定" };
                return Remember(next, pending, loaded, context.MemoryAvailability, ArkQuestionMemoryOperation.Observe);
            case ArkAnswerResultEvent answer when pending?.Kind == "question":
                var current = state.Question;
                if (current?.Selected is null || pending.Result) next = Freeze(state, "收到無法對應的問答結果");
                else if (answer.Correct && answer.Answer != current.Selected) next = Freeze(state, "答對回覆與已送出選項不符");
                else
                {
                    next = state with { Pending = pending with { Result = true },
                        Status = answer.Correct ? "答案正確，等待事件完成" : "答案錯誤，等待事件完成" };
                    return Remember(next, pending, current, context.MemoryAvailability,
                        answer.Correct ? ArkQuestionMemoryOperation.Confirm : ArkQuestionMemoryOperation.Reject);
                }
                break;
            case ArkErrorEvent error when pending is not null:
                next = Freeze(state, $"伺服器拒絕方舟操作（代碼 {error.Code}）");
                break;
        }
        return new(next);
    }

    private static ArkReceiveResult Remember(ArkReceiveSnapshot state, ArkPendingObservation pending,
        ArkQuestionSnapshot question, ArkQuestionMemoryAvailability availability, ArkQuestionMemoryOperation operation)
    {
        uint? selected = question.Selected is >= 1 and <= 4 && question.Options.Length == 4
            ? question.Options[question.Selected.Value - 1] : null;
        var rejectedCandidate = operation == ArkQuestionMemoryOperation.Reject &&
            (question.SelectedCandidate == true || question.AnswerKind is "computed" or "reviewed_candidate" && selected == question.KnownAnswer);
        var intent = new ArkQuestionMemoryIntent(operation, pending.Token, pending.Role, pending.DailyGeneration,
            state.Generation, pending.Event, question, selected, rejectedCandidate);
        return new(state with
        {
            Question = question with { KnownAnswer = null, AnswerKind = "", AnswerSource = "" },
            QuestionStoreStatus = availability == ArkQuestionMemoryAvailability.Unavailable ? UnavailableMemoryStatus : DeferredMemoryStatus
        }, intent);
    }

    private static ArkReceiveSnapshot Freeze(ArkReceiveSnapshot state, string note) => state with
    { Pending = null, Uncertain = true, Status = note + "；停止重送，請重新登入同步" };
}
