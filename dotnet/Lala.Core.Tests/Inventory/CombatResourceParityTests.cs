using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatResourceParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    [Theory]
    [MemberData(nameof(CombatResourcePythonVectors.Cases), MemberType = typeof(CombatResourcePythonVectors))]
    public void PureHelpersMatchRealPython(string kind, string json)
    {
        var input = JsonNode.Parse(json)!.AsObject(); var catalog = Catalog(input["catalog"]!);
        var state = input["state"]; var player = Player(state?["knowledge"]?["player"]);
        var companions = Companions(state?["knowledge"]?["companions"], state?["knowledge"]?["active_npc_id"]);
        var local = state?["player"]; var role = U(local, "role_id");
        var actor = Actor(input["actor"]);
        var beforePlayer = JsonSerializer.Serialize(player, Options); var beforeCompanions = JsonSerializer.Serialize(companions, Options);
        JsonNode? result = kind switch
        {
            "learned" => new JsonArray([.. CombatResourceKnowledge.Learned(player, companions, role, actor, catalog).Select(Learned)]),
            "weapon" => JsonSerializer.SerializeToNode(CombatResourceKnowledge.WeaponGroup(actor, catalog)),
            "target" => JsonValue.Create(CombatResourceKnowledge.TargetValid(actor, Actor(input["target"]), Skill(input["skill"]!))),
            "heal" => JsonSerializer.SerializeToNode(CombatResourceKnowledge.HealEffects((ushort)input["item_id"]!.GetValue<int>(), catalog)),
            "history" => History(input["events"]!.AsArray(), catalog),
            "field" => Field(CombatResourceKnowledge.FieldContext(player, companions,
                role is { } id ? new WorldPlayer(id, (byte)(L(local,"sex") ?? 0),0,0,0,0,(byte)(L(local,"head") ?? 0),0,0,0,0,false,[],S(local,"name") ?? "角色",0) : null, catalog)),
            _ => throw new InvalidOperationException(kind)
        };
        Assert.True(JsonNode.DeepEquals(input["expected"], result), $"{kind}\nExpected: {input["expected"]}\nActual: {result}");
        Assert.Equal(beforePlayer, JsonSerializer.Serialize(player, Options));
        Assert.Equal(beforeCompanions, JsonSerializer.Serialize(companions, Options));
    }

    [Fact]
    public void PythonOracleSourceHashesNormalizeOnlyCrLfBytes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/services/items/combat_resources.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, hash) in JsonNode.Parse(CombatResourcePythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName,path))));
    }

    private static JsonArray History(JsonArray events, CombatResourceCatalog catalog)
    {
        var state = CompanionReceiveSnapshot.Empty;
        var history = new List<(CompanionReceiveSnapshot State, JsonObject Projection)>();
        var mapping = catalog.Npcs.ToImmutableDictionary(p => p.Key,p => p.Value.Skills);
        foreach (var input in events)
        {
            ServerEvent value = S(input,"type") == "companion_snapshot" ?
                new ServerLiveDataEvent(new CompanionSnapshotEvent([.. input!["companions"]!.AsArray().Select(v => JsonSerializer.Deserialize<CompanionSnapshot>(v,Options)!)])) :
                new AttributeSetEvent((byte)L(input,"sub")!, S(input,"entity")!,4,(ushort)L(input,"index")!,110,"skill",1,L(input,"value")!.Value,U(input,"parameter")!.Value);
            state = CompanionReceiveReducer.Apply(state,value,7,mapping);
            history.Add((state, Project(state)));
        }
        foreach (var (old,expected) in history) Assert.True(JsonNode.DeepEquals(expected,Project(old)), "Immutable companion skill history changed.");
        return new JsonArray([.. history.Select(p => (JsonNode)p.Projection)]);
        JsonObject Project(CompanionReceiveSnapshot snapshot)
        {
            var profile = snapshot.Companions.GetValueOrDefault((ushort)1);
            var skills = profile?.Skills ?? ImmutableDictionary<uint,CompanionLearnedSkill>.Empty;
            return new JsonObject
            {
                ["order"] = new JsonArray([.. (profile?.SkillOrder ?? []).Select(id => (JsonNode)JsonValue.Create(id.ToString())!)]),
                ["skills"] = JsonSerializer.SerializeToNode(skills,Options),
                ["removed"] = profile?.RemovedSkillIds is { } removed ? new JsonArray([.. removed.Select(id => (JsonNode)JsonValue.Create(id.ToString())!)]) : null,
                ["learned"] = new JsonArray([.. CombatResourceKnowledge.Learned(PlayerKnowledgeSnapshot.Empty,snapshot,7,
                    new() { Pid = 80, MasterId = 7, NpcIndex = 1, Sex = 1, Head = 2 },catalog).Select(Learned)])
            };
        }
    }

    internal static CombatResourceCatalog Catalog(JsonNode data) => new()
    {
        SkillKeys = data["keys"]!.AsObject().ToImmutableDictionary(p => ushort.Parse(p.Key), p => p.Value!.GetValue<uint>()),
        Items = data["items"]!.AsObject().ToImmutableDictionary(p => ushort.Parse(p.Key), p => new CombatResourceItem((int?)L(p.Value,"kind"), (int)(L(p.Value,"fit_type") ?? 0), U(p.Value,"skill_link") ?? 0)
        { Attributes = [.. (p.Value?["attributes"]?.AsArray() ?? []).Select(a => new CombatResourceAttribute((int)L(a,"kind")!, L(a,"value")!.Value))] }),
        Skills = data["skills"]!.AsObject().ToImmutableDictionary(p => uint.Parse(p.Key), p => Skill(p.Value!)),
        Npcs = data["npcs"]!.AsObject().ToImmutableDictionary(p => uint.Parse(p.Key), p => new CombatResourceNpc
        { Name = S(p.Value,"name"), Skills = [.. (p.Value?["skills"]?.AsArray() ?? []).Select(v => v!.GetValue<uint>())] }),
        Characters = [.. data["characters"]!.AsArray().Select(v => new CombatResourceCharacter((int)L(v,"sex")!, (int)L(v,"head")!, U(v,"skill")!.Value, (ushort)L(v,"body")!))]
    };
    private static CombatResourceSkill Skill(JsonNode data) => new() { Name = S(data,"name"), Fields = Stats(data) };
    private static JsonObject Learned(LearnedSkillKnowledge value)
    {
        var result = new JsonObject { ["id"] = value.Id, ["level"] = value.Level, ["source"] = value.Source };
        if (value.Exp is { } exp) result["exp"] = exp;
        if (value.Key is { } key) result["key"] = key;
        return result;
    }
    private static CombatResourceActor Actor(JsonNode? data) => new()
    {
        Pid = U(data,"pid"), MasterId = U(data,"master_id"), NpcIndex = (ushort?)L(data,"npc_index"),
        Col = (int)(L(data,"col") ?? 0), Row = (int)(L(data,"row") ?? 0), Sex = (int?)L(data,"sex"), Head = (int?)L(data,"head"),
        Name = S(data,"name"), Exited = data?["exited"]?.GetValue<bool>() ?? false, IsFly = data?["is_fly"]?.GetValue<bool>() ?? false,
        Equips = [.. (data?["equips"]?.AsArray() ?? []).Select(Equip)],
        Stats = Stats(data).Where(p => p.Key is "hp" or "sp" or "max_hp" or "max_sp").ToImmutableDictionary()
    };
    private static PlayerKnowledgeSnapshot Player(JsonNode? p) => new()
    {
        Skills = (p?["skills"]?.AsObject() ?? []).ToImmutableDictionary(v => uint.Parse(v.Key), v => new PlayerSkillEvidence(L(v.Value,"level") ?? 0, U(v.Value,"exp") ?? 0, S(v.Value,"source")!, (ushort?)L(v.Value,"key"))),
        SkillOrder = [.. (p?["skills"]?.AsObject() ?? []).Select(v => uint.Parse(v.Key))],
        ServerSkillRecords = p?["server_skill_records"] is { } records ? [.. records.AsArray().Select(v => new LearnedSkill((ushort)L(v,"key")!,(byte)L(v,"level")!,U(v,"exp")!.Value))] : null,
        RemovedSkillIds = p?["removed_skill_ids"] is { } removed ? [.. removed.AsArray().Select(v => uint.Parse(v!.GetValue<string>()))] : null,
        Stats = Stats(p?["stats"]), Equipment = new()
        {
            Equips = p?["equips"] is { } equips ? [.. equips.AsArray().Select(Equip)] : null,
            UnresolvedEquips = p?["unresolved_equips"] is { } pending ? [.. pending.AsArray().Select(Item)] : null,
            DeferredEquipUpdates = p?["deferred_equip_updates"] is { } deferred ? [.. deferred.AsArray().Select(Event)] : null
        }
    };
    private static CompanionReceiveSnapshot Companions(JsonNode? profiles, JsonNode? active)
    {
        var result = ImmutableDictionary.CreateBuilder<ushort, CompanionProfileSnapshot>();
        foreach (var (key,p) in profiles?.AsObject() ?? [])
        {
            var data = p!["stats"]!.DeepClone();
            data["skill_slots"] = p["server_skill_slots"]!.DeepClone(); data["equips"] = new JsonArray();
            var original = JsonSerializer.Deserialize<CompanionSnapshot>(data, Options)!;
            var values = p["skills"]!.AsObject();
            result.Add(ushort.Parse(key),new(original,
                values.ToImmutableDictionary(v => uint.Parse(v.Key), v => new CompanionLearnedSkill(L(v.Value,"level") ?? 0,U(v.Value,"exp") ?? 0,S(v.Value,"source")!)),
                Stats(p["stats"]), p["removed_skill_ids"] is { } removed ? [.. removed.AsArray().Select(v => uint.Parse(v!.GetValue<string>()))] : null)
                { SkillOrder = [.. values.Select(v => uint.Parse(v.Key))], EquipmentOverrides = [.. p["equips"]!.AsArray().Select(Equip)] });
        }
        return new() { ActiveNpcId = active?.GetValue<uint>(), Companions = result.ToImmutable(), CompanionOrder = [.. (profiles?.AsObject() ?? []).Select(p => ushort.Parse(p.Key))] };
    }
    private static JsonObject Field(FieldCombatContext context)
    {
        var units = new JsonArray();
        for (var i = 0; i < context.Units.Length; i++)
        {
            var value = context.Units[i];
            var node = new JsonObject { ["col"] = value.Col,["row"] = value.Row,["pid"] = value.Pid,["master_id"] = value.MasterId,["npc_index"] = value.NpcIndex,["name"] = value.Name,["equips"] = Equips(value.Equips) };
            if (i == 0) { node["sex"] = value.Sex; node["head"] = value.Head; }
            foreach (var (key,number) in value.Stats) node[key] = number;
            units.Add(node);
        }
        var equipment = context.Player.Equipment;
        return new JsonObject { ["units"] = units, ["equips"] = equipment.Equips is { } current ? Equips(current) : null,
            ["unresolved"] = equipment.UnresolvedEquips is { } pending ? Equips([.. pending.Select(KnowledgeEquipment.FromItem)]) : null,
            ["deferred"] = equipment.DeferredEquipUpdates is { } deferred ? new JsonArray([.. deferred.Select(EventJson)]) : null };
    }
    private static JsonArray Equips(ImmutableArray<KnowledgeEquipment> values) => new([.. values.Select(v =>
    {
        var node = new JsonObject { ["item_id"] = v.ItemId };
        if (v.DesignId is { } design) node["design_id"] = design;
        if (v.Damage is { } damage) node["damage"] = damage;
        return (JsonNode)node;
    })]);
    private static JsonNode EventJson(LiveDataEvent value) => value switch
    {
        EquipDamageEvent v => new JsonObject { ["type"] = v.Type,["index"] = v.Index,["damage"] = v.Damage },
        EquipBrokenEvent v => new JsonObject { ["type"] = v.Type,["item_id"] = v.ItemId },
        BattleEquipEvent v => new JsonObject { ["type"] = v.Type,["equip_index"] = v.EquipIndex,["item_id"] = v.ItemId,["design_id"] = v.DesignId },
        _ => throw new InvalidOperationException()
    };
    private static LiveDataEvent Event(JsonNode? data) => S(data,"type") switch
    {
        "equip_damage" => new EquipDamageEvent(27,0,(byte)L(data,"index")!,U(data,"damage")!.Value),
        "equip_broken" => new EquipBrokenEvent(35,0,(ushort)L(data,"item_id")!),
        "battle_equip" => new BattleEquipEvent(7,0,(byte)L(data,"equip_index")!,(ushort)L(data,"item_id")!,U(data,"design_id")!.Value),
        _ => throw new InvalidOperationException()
    };
    private static KnowledgeEquipment Equip(JsonNode? data) => new((ushort)L(data,"item_id")!, U(data,"design_id"), U(data,"damage"));
    private static ItemSave Item(JsonNode? data) => new(null,(ushort)L(data,"item_id")!,1,(byte)(L(data,"damage") ?? 0),0,0,null,null,0,0,0,0,0,0,null,0,0,U(data,"design_id") ?? 0,[],false,0,0,null);
    private static long? L(JsonNode? data,string key) => data?[key]?.GetValue<long>();
    private static uint? U(JsonNode? data,string key) => data?[key]?.GetValue<uint>();
    private static string? S(JsonNode? data,string key) => data?[key]?.GetValue<string>();
    private static ImmutableDictionary<string,long> Stats(JsonNode? data) => (data?.AsObject() ?? []).Where(p => p.Value is JsonValue value && value.TryGetValue<long>(out _)).ToImmutableDictionary(p => p.Key,p => p.Value!.GetValue<long>());
}
