using System.Buffers.Binary;
using System.Collections.Frozen;
using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Social.Ark;

/// <summary>Pure port of star_ark.py decode_ark and its three validation helpers.
/// Recognized packets require exact consumption; unknown keys remain opaque. This does not
/// implement the planner, candidate answers, state mutation, commands or runtime catalogs.</summary>
public static class ArkDecoder
{
    public static ArkEvent? Decode(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        var r = new PacketReader(packet.Payload.Span);
        ArkEvent? result;
        if (packet.Main == 75 && packet.Sub == 24)
            result = new ArkStarcoinEvent(r.U32(), r.U32(), ReadBool(r), ReadBool(r));
        else if (packet.Main != 191) return null;
        else result = packet.Sub switch
        {
            0 => new ArkErrorEvent(r.U8()),
            1 => ReadSnapshot(r),
            2 => new ArkEventsEvent(ReadEvents(r, false), ReadBool(r)),
            3 => ReadDispatch(r),
            4 => ReadCollectReward(r),
            5 => ReadCollectEnd(r),
            6 => ReadSkill(r),
            7 => ReadNewAgent(r),
            10 => ReadComplete(r),
            11 => ReadQuestion(r),
            12 => ReadAnswerResult(r),
            15 => ReadFightResult(r),
            16 => new ArkMainEventsEvent(ReadEvents(r, true)),
            17 => ReadExplore(r),
            18 => ReadMainAdded(r),
            19 => ReadCollectCount(r),
            _ => null
        };
        if (result is not null) r.End();
        return result;
    }

    private static bool ReadBool(PacketReader r)
    {
        var value = r.U8();
        if (value > 1) throw new ProtocolException("方舟布林旗標無效");
        return value != 0;
    }

    private static byte Planet(byte value, bool zero = false)
    {
        if (value < (zero ? 0 : 1) || value > 20) throw new ProtocolException("方舟星球索引無效");
        return value;
    }

    private static void ValidateExplore(byte planet, ushort explore)
    {
        if (planet is < 1 or > 21 || explore > 10000) throw new ProtocolException("方舟探索進度無效");
    }

    private static short ReadShort(PacketReader r) => BinaryPrimitives.ReadInt16LittleEndian(r.Take(2));
    private static ArkAward ReadAward(PacketReader r) => new(r.U8(), r.U32(), r.U32());

    private static ArkSnapshotEvent ReadSnapshot(PacketReader r)
    {
        var planet = r.U8(); var explore = r.U16();
        ValidateExplore(planet, explore);
        var agents = new Dictionary<byte, ArkAgent>();
        var count = r.U8();
        for (var i = 0; i < count; i++)
        {
            var index = r.U8();
            var agent = new ArkAgent(index, r.U8(), [r.U8(), r.U8()], Planet(r.U8(), true));
            if (index == 0 || agents.ContainsKey(index) || agent.Id == 0 || agent.Skills.Any(v => v < 1))
                throw new ProtocolException("情報員資料無效／重複");
            agents.Add(index, agent);
        }
        var total = r.U16(); var awarded = ReadShort(r); var remaining = r.U16();
        if (awarded < 0 || awarded > (total + 299) / 300 || remaining > total)
            throw new ProtocolException("搜索艇時間／領獎次數無效");
        var assigned = new HashSet<byte>();
        var shipCount = 0;
        byte shipPlanet = 0;
        ImmutableArray<byte> shipAgents = [0, 0];
        for (byte p = 1; p <= 20; p++)
        {
            ImmutableArray<byte> ids = [r.U8(), r.U8()]; var boat = r.U8();
            if (boat > 1 || (ids.Any(v => v != 0) && boat == 0))
                throw new ProtocolException("星球搜索艇資料不一致");
            if (boat != 0) { shipCount++; shipPlanet = p; shipAgents = ids; }
            foreach (var index in ids)
            {
                if (index != 0 && (assigned.Contains(index) || !agents.TryGetValue(index, out var agent) || agent.Planet != p))
                    throw new ProtocolException("情報員星球指派不一致");
                if (index != 0) assigned.Add(index);
            }
        }
        if (shipCount != (total != 0 ? 1 : 0) || (total != 0) != (assigned.Count != 0)
            || agents.Any(a => a.Value.Planet != 0 && !assigned.Contains(a.Key)))
            throw new ProtocolException("搜索艇與情報員配置不一致");
        return new(planet, explore, agents.ToFrozenDictionary(), new(total, awarded, remaining, shipPlanet, shipAgents));
    }

    private static FrozenDictionary<byte, ArkEventRow> ReadEvents(PacketReader r, bool main)
    {
        var rows = new Dictionary<byte, ArkEventRow>();
        for (byte index = 1; index <= (main ? 20 : 12); index++)
        {
            var id = r.U16(); var kind = r.U8(); var planet = main ? index : r.U8();
            if (main)
            {
                if (id != 0 && (id < 10000 || kind is < 1 or > 4)) throw new ProtocolException("方舟主線事件無效");
                if (id == 0 && kind != 0) throw new ProtocolException("方舟空主線事件無效");
            }
            else if (id != 0)
            {
                Planet(planet);
                if (id >= 10000 || kind is < 1 or > 4) throw new ProtocolException("方舟一般事件無效");
            }
            else if (kind != 0 || planet != 0) throw new ProtocolException("方舟空事件資料不一致");
            rows.Add(index, new(index, id, kind, planet, main));
        }
        return rows.ToFrozenDictionary();
    }

    private static ArkDispatchEvent ReadDispatch(PacketReader r)
    {
        var result = new ArkDispatchEvent(Planet(r.U8()), r.U8(), [r.U8(), r.U8()], r.U16());
        if (result.Ship != 1 || !result.Agents.Any(v => v != 0) || result.Total == 0
            || result.Agents[0] != 0 && result.Agents[0] == result.Agents[1])
            throw new ProtocolException("方舟派遣回覆無效");
        return result;
    }

    private static ArkCollectRewardEvent ReadCollectReward(PacketReader r)
    {
        var total = r.U16(); var count = r.U8();
        var items = ImmutableArray.CreateBuilder<ArkCollectedItem>(count);
        for (var i = 0; i < count; i++) items.Add(new(r.U16(), r.U16()));
        return new(total, items.MoveToImmutable());
    }

    private static ArkCollectEndEvent ReadCollectEnd(PacketReader r)
    {
        var result = new ArkCollectEndEvent(Planet(r.U8()), r.U8());
        if (result.Ship != 1) throw new ProtocolException("方舟搜索艇索引無效");
        return result;
    }

    private static ArkSkillEvent ReadSkill(PacketReader r)
    {
        var result = new ArkSkillEvent(r.U8(), r.U8(), r.U8());
        if (result.Index == 0 || result.Skill is not (1 or 2) || result.Level == 0)
            throw new ProtocolException("情報員技能更新無效");
        return result;
    }

    private static ArkNewAgentEvent ReadNewAgent(PacketReader r)
    {
        var result = new ArkNewAgentEvent(r.U8(), r.U8());
        if (result.Index == 0 || result.Id == 0) throw new ProtocolException("新增情報員無效");
        return result;
    }

    private static ArkCompleteEvent ReadComplete(PacketReader r)
    {
        var result = new ArkCompleteEvent(r.U8(), r.U16());
        if (result.Id == 0 || result.Index < 1 || result.Index > (result.Id >= 10000 ? 20 : 12))
            throw new ProtocolException("方舟完成事件索引無效");
        return result;
    }

    private static ArkQuestionEvent ReadQuestion(PacketReader r)
    {
        var result = new ArkQuestionEvent(r.U32(), ReadAward(r), [r.U32(), r.U32(), r.U32(), r.U32()]);
        if (result.Question == 0 || result.Options.Any(v => v == 0) || result.Options.Distinct().Count() != 4)
            throw new ProtocolException("方舟問答題目／選項無效");
        return result;
    }

    private static ArkAnswerResultEvent ReadAnswerResult(PacketReader r)
    {
        var result = new ArkAnswerResultEvent(ReadBool(r), r.U8());
        if (result.Answer is < 1 or > 4) throw new ProtocolException("方舟答案索引無效");
        return result;
    }

    private static ArkFightResultEvent ReadFightResult(PacketReader r)
    {
        if (!ReadBool(r)) return new(false);
        var id = r.U16(); var count = r.U8();
        if (count > 32) throw new ProtocolException("方舟獎勵數量超出可驗證範圍");
        var awards = ImmutableArray.CreateBuilder<ArkAward>(count);
        for (var i = 0; i < count; i++) awards.Add(ReadAward(r));
        return new(true, id, awards.MoveToImmutable());
    }

    private static ArkExploreEvent ReadExplore(PacketReader r)
    {
        var result = new ArkExploreEvent(r.U8(), r.U16());
        ValidateExplore(result.Planet, result.Explore);
        return result;
    }

    private static ArkMainAddedEvent ReadMainAdded(PacketReader r)
    {
        var result = new ArkMainAddedEvent(Planet(r.U8()), r.U16(), r.U8());
        if (result.Id < 10000 || result.Kind is < 1 or > 4) throw new ProtocolException("方舟新增主線無效");
        return result;
    }

    private static ArkCollectCountEvent ReadCollectCount(PacketReader r)
    {
        var result = new ArkCollectCountEvent(r.U8(), ReadShort(r));
        if (result.Ship != 1 || result.Count < 0) throw new ProtocolException("方舟採集領取次數無效");
        return result;
    }
}
