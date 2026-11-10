using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Catalogs;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.Social.Ark;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    private static GameActionPlan Donate(GameAction a, ServiceStateSnapshot s, GameSocialCatalog? catalog, double now)
    {
        var g = s.GuildActions; var gold = s.Local.Session.Gold;
        Require(catalog is not null && s.Guild.Ready && s.Guild.Serial is > 0 && s.Guild.Members.ContainsKey(s.Player!.RoleId) && g.Role == s.Player.RoleId && g.Guild == s.Guild.Serial,
            "尚未確認組織身分與同版價格資料。");
        Require(g.Pending is null && !g.Uncertain && g.Remaining is > 0 && g.Allow && s.Guild.Level is {} level && catalog!.GuildLimits.ContainsKey(level), "沒有可確認的捐獻資格或剩餘次數。");
        int target = a.Count; long budget = a.Values?.GetValueOrDefault("budget") ?? 0;
        byte limit = catalog!.GuildLimits[s.Guild.Level!.Value];
        Require(target is >= 1 and <= 5 && g.Remaining <= limit && limit - g.Remaining < target, "今日捐獻已達設定目標。");
        Require(a.Index is 8 or 9 or 10 && catalog.Sell.ContainsKey((ushort)a.Index), "請選擇有效的捐獻方案。");
        var row = catalog.Sell[(ushort)a.Index];
        Require(row.Kind == 0 && row.LimitFlag == 0 && (row.LimitKind == 0 || row.SaveIndex != 0), "此方案有尚未核對的扣物品或功能限制。");
        Require(row.SaveIndex == 0 || g.CountsReady && g.Counts.ContainsKey(row.SaveIndex), "消費次數尚未同步。");
        int count = row.SaveIndex == 0 ? 0 : g.Counts[row.SaveIndex]; bool first = count < row.BaseCount;
        byte kind = first ? row.BaseKind : row.SecondKind; ushort formulaId = first ? row.BaseFormula : row.SecondFormula;
        Require(kind is 4 or 5 && (row.TotalCount == 0 || count < row.TotalCount), "方案非金幣／免費，或消費次數已達上限。");
        Require(kind == 5 || catalog.Formulas.TryGetValue(formulaId, out var formula) && formula.Kind == 2, "價格公式未核對。");
        int price = kind == 5 ? 0 : catalog.Formulas[formulaId].Value;
        Require(gold is { Ready: true, Reliable: true, Amount: {} amount } && amount >= price && budget >= 0 && g.Reserved + price <= budget, "金幣不足、未可靠同步，或超過設定的本輪上限。");
        var quote = new GuildDonationQuote(price, kind, row.Id, row.SaveIndex, count);
        var pending = new GuildDonationPending(s.Player!.RoleId, s.Guild.Serial!.Value, new(true, catalog.Identity), g.Epoch, now + 20,
            quote, g.Remaining!.Value, gold.Amount!.Value, price == 0, row.SaveIndex == 0);
        return new(new(10, 5, new PacketWriter().U16(row.Id).Build()), "guild", $"組織捐獻（{price} 金幣）",
            next => CommandState.With(next, guildActions: next.GuildActions with { Pending = pending, CatalogToken = pending.Token, Reserved = g.Reserved + price }),
            next => next.GuildActions.Pending is GuildDonationPending { GoldAck: true, SellAck: true, RemainingAck: true } p && next.GuildActions.Remaining == p.BeforeRemaining - 1 && next.Local.Session.Gold.Reliable,
            next => CommandState.With(next, guildActions: next.GuildActions with { Pending = null, Confirmed = next.GuildActions.Confirmed + price }));
    }

    private static GameActionPlan ArkAction(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, GameSocialCatalog? catalog, double now, string resourceKey)
    {
        var ark = s.Ark;
        Require(catalog?.Identity == resourceKey && ark.Ready && ark.Role == s.Player!.RoleId && !ark.Uncertain, "方舟、角色或同版資料尚未同步。");
        var token = new ArkCatalogToken(true, resourceKey);
        if (a.Operation == "answer")
        {
            Require(ark.Pending is { Kind: "question" } pending && pending.Token == token && pending.DailyGeneration == s.DailyTasks.Generation &&
                ark.Question is { Selected: null } && a.Index is >= 1 and <= 4, "沒有可回覆的當前方舟問答。");
            return new(new(191, 7, [(byte)a.Index]), "ark", "回答方舟問答",
                next => CommandState.With(next, ark: next.Ark with { Question = next.Ark.Question! with { Selected = (byte)a.Index }, Pending = next.Ark.Pending! with { Due = now + 20 } }),
                next => next.Ark.Pending is { Kind: "question", Result: true, Complete: true },
                next => CommandState.With(next, ark: next.Ark with { Pending = null }));
        }
        Require(ark.Pending is null, "前次方舟操作仍等待確認。");
        if (a.Operation == "dispatch")
        {
            Require(ark.Ship is { Total: 0 } && ark.Starcoin is { Ready: true, Reliable: true, Amount: {} balance } && a.Count is >= 1 and <= 6 && a.Index is >= 1 and <= 255 &&
                ark.Agents.TryGetValue((byte)a.Index, out var chosen) && chosen.Planet == 0 && catalog!.Agents.ContainsKey(chosen.Id) && catalog.StarPrices.ContainsKey(1), "搜索艇、空閒情報員、星力或採集時間尚未確認。");
            var agent = ark.Agents[(byte)a.Index]; var skills = catalog!.Agents[agent.Id];
            int discount = 0, extension = 0;
            Require(agent.Skills.Length == skills.Length, "情報員技能欄位不符。");
            for (int i = 0; i < skills.Length; i++)
            {
                var skill = skills[i]; int level = agent.Skills[i]; Require(level > 0 && level <= skill.Maximum && skill.Kind <= 5, "情報員技能資料超出支援範圍。");
                int value = skill.Initial + skill.Add * (level - 1);
                if (skill.Kind == 2) discount += value; else if (skill.Kind == 1) extension += value;
            }
            Require(discount is >= 0 and <= 1000, "折扣超出可核對範圍。");
            int price = checked((int)decimal.Round(catalog.StarPrices[1][a.Count - 1] * (1000 - discount) / 1000m, 0, MidpointRounding.ToEven));
            int duration = checked((int)decimal.Round(a.Count * 3600m * (100 + extension) / 100m, 0, MidpointRounding.ToEven));
            Require(duration is > 0 and <= 65535 && ark.Starcoin.Amount >= price && ark.Reserved + price <= (a.Values?.GetValueOrDefault("budget") ?? 0), "採集時間超出範圍、星力不足，或超過登入額度。");
            var quote = new ArkDispatchQuote(1, (byte)a.Index, (ushort)duration, price);
            var p = new ArkPendingObservation("dispatch", s.Player!.RoleId, token, s.DailyTasks.Generation)
                { Quote = quote, Balance = ark.Starcoin.Amount!.Value, Paid = price == 0, Due = now + 20 };
            return new(new(191, 1, new PacketWriter().U8(1).U8(a.Count).U8(a.Index).U8(0).Build()), "ark", $"派遣情報員（{price} 星力）",
                next => CommandState.With(next, ark: next.Ark with { Pending = p, CatalogToken = token, Reserved = ark.Reserved + price }),
                next => next.Ark.Pending is { Paid: true, ShipAck: true },
                next => CommandState.With(next, ark: next.Ark with { Pending = null, Confirmed = next.Ark.Confirmed + price }));
        }
        Require(ark.EventsReady && a.Index is >= 1 and <= 255 && ark.Events.TryGetValue((byte)a.Index, out var eventRow) && eventRow.Id == a.Target && !eventRow.Main && eventRow.Planet <= Math.Min(ark.Planet, (byte)20), "請選擇尚未完成、已開放的支線事件。");
        var selected = ark.Events[(byte)a.Index];
        if (a.Operation == "question")
        {
            Require(selected.Kind == 3, "此事件不是問答。");
            var p = new ArkPendingObservation("question", s.Player!.RoleId, token, s.DailyTasks.Generation) { Event = selected, Due = now + 20 };
            return new(new(191, 6, new PacketWriter().U8(a.Index).U16(a.Target).Build()), "ark", "開啟方舟問答",
                next => CommandState.With(next, ark: next.Ark with { Pending = p, CatalogToken = token, Question = null }),
                next => next.Ark.Question is not null && next.Ark.Pending is { Kind: "question" });
        }
        Require(a.Operation == "fight" && selected.Kind == 1 && catalog!.Fights.ContainsKey(selected.Id), "此事件不是已核對的戰鬥事件。");
        var fight = catalog!.Fights[selected.Id];
        Require(fight.Agent == 0, "此獎勵會新增情報員，缺少容量資料，不能自動執行。");
        var awards = fight.Awards.Where(award => award.Kind != 0).ToImmutableArray();
        long slots = Lala.Core.Automation.DailyTaskService.SlotsNeeded([..awards.Select(award => new Lala.Core.Automation.TaskAward(award.Kind, award.Id, award.Value))]);
        Require(Context(s).Bag.Problem(slots).Length == 0, "背包空間不足以容納方舟戰鬥獎勵。");
        var expected = awards.Where(award => award.Kind is 10 or 11).GroupBy(award => award.Id).ToDictionary(g => g.Key, g => g.Sum(award => (long)award.Value));
        var before = StateValue.Map(expected.Select(pair => KeyValuePair.Create(pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture),
            StateValue.Scalar(s.Bag.Items.Values.Where(i => i.ItemId == pair.Key).Sum(i => (long)i.Count) + pair.Value))));
        var pendingFight = new ArkPendingObservation("fight", s.Player!.RoleId, token, s.DailyTasks.Generation)
            { Event = selected, Awards = awards, Due = now + 180, OtherFields = StateValue.Map(("lala_owned", StateValue.Scalar(true)), ("expected_bag", before)) };
        return new(new(191, 4, new PacketWriter().U8(a.Index).U16(a.Target).Build()), "ark", "開始方舟戰鬥",
            next => CommandState.With(next, ark: next.Ark with { Pending = pendingFight, CatalogToken = token }), next => false)
            { AwaitAcknowledgement = false };
    }

    internal static ServiceStateSnapshot ReconcileArkFight(ServiceStateSnapshot s, double now)
    {
        var ark = s.Ark;
        if (ark.Pending is not { Kind: "fight" } p || p.OtherFields.Kind != StateValueKind.Map || p.OtherFields["lala_owned"].ScalarValue is not true) return s;
        bool same = p.Role == s.Player?.RoleId && p.DailyGeneration == s.DailyTasks.Generation && p.Token == ark.CatalogToken;
        if (!same || p.Due is {} due && now >= due)
            return CommandState.With(s, ark: ark with { Pending = null, Uncertain = true, Enabled = false, Status = "方舟戰鬥結果未確認，已停止接續；請重新登入同步。" });
        if (!p.Result || !p.Complete || !s.Bag.Reliable) return s;
        foreach (var (idText, value) in p.OtherFields["expected_bag"].MapValue)
            if (!ushort.TryParse(idText, out var id) || value.ScalarValue is not long expected || s.Bag.Items.Values.Where(i => i.ItemId == id).Sum(i => (long)i.Count) < expected) return s;
        return CommandState.With(s, ark: ark with { Pending = null, Status = "已確認方舟戰鬥結果、事件完成與產物入包。" });
    }
}
