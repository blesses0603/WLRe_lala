using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Automation;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Automation;

public sealed class AutomationParityTests
{
    public static IEnumerable<object[]> WireCases() => Cases("wire");
    public static IEnumerable<object[]> SequenceCases() => Cases("sequences");
    private static IEnumerable<object[]> Cases(string key)
    {
        using var doc = JsonDocument.Parse(PythonAutomationVectors.Json);
        foreach (var value in doc.RootElement.GetProperty(key).EnumerateArray()) yield return [value.GetRawText()];
    }
    private static JsonObject Object(object value) => JsonSerializer.SerializeToNode(value)!.AsObject();
    private static object Awards(ImmutableArray<TaskAward> awards) => awards.Select(a => new { kind = a.Kind, id = a.Id, value = a.Value }).ToArray();
    private static object Flags(ImmutableArray<ChestFlag> flags) => flags.Select(f => new[] { (int)f.Kind, (int)f.Mark }).ToArray();
    private static JsonObject Marks(TaskMarks m) => Object(new
    {
        daily_value = m.DailyValue, weekly_value = m.WeeklyValue, daily_done_mark = m.DailyDone,
        daily_reward_mark = m.DailyReward, daily_event_reward_a = m.DailyEventA, daily_event_reward_b = m.DailyEventB,
        weekly_done_mark = new[] { m.WeeklyDone & 255, m.WeeklyDone >> 8 }, weekly_reward_mark = m.WeeklyReward,
        weekly_event_reward_a = m.WeeklyEventA, weekly_event_reward_b = m.WeeklyEventB
    });
    private static JsonObject? Event(object? value)
    {
        var result = value switch
        {
            null => null,
            CubeInfo c => Object(new { type = "cube_info", kind = c.Kind, count = c.Count, check_minutes = c.CheckMinutes, keep_minutes = c.KeepMinutes }),
            CubeItem c => Object(new { type = "cube_item", item_id = c.ItemId }),
            CubeLegacyResult => Object(new { type = "cube_legacy_result" }),
            TaskSnapshot s => Marks(s.Marks),
            TaskGroups g => Object(new { type = "daily_task_groups", daily_group = g.DailyGroup, weekly_group = g.WeeklyGroup }),
            TaskMarksChanged m => Marks(m.Marks),
            TaskProgress p => Object(new { type = "daily_task_progress", cycle = p.Cycle, task_id = p.TaskId, count = p.Count }),
            TaskUnknownUpdate u => Object(new { type = "daily_task_unknown_update", kind = u.Kind }),
            TaskRewardNotice n => Object(new { type = "daily_task_reward_notice", kind = n.Kind, awards = Awards(n.Awards) }),
            TaskError e => Object(new { type = "daily_task_error", code = e.Code, message = e.Message }),
            _ => throw new InvalidOperationException()
        };
        if (value is TaskSnapshot snapshot)
        {
            result!["type"] = "daily_task_snapshot";
            result["daily_progress"] = JsonSerializer.SerializeToNode(snapshot.DailyProgress.Select(v => (int)v).ToArray());
            result["weekly_progress"] = JsonSerializer.SerializeToNode(snapshot.WeeklyProgress.Select(v => (int)v).ToArray());
            result["daily_event_active"] = snapshot.DailyEventActive; result["weekly_event_active"] = snapshot.WeeklyEventActive;
        }
        if (value is TaskMarksChanged) result!["type"] = "daily_task_marks";
        return result;
    }
    [Theory, MemberData(nameof(WireCases))]
    public void DecodersMatchRetainedPython(string json)
    {
        using var doc = JsonDocument.Parse(json); var v = doc.RootElement;
        var packet = new Packet(v.GetProperty("main").GetInt32(), v.GetProperty("sub").GetInt32(), Convert.FromHexString(v.GetProperty("hex").GetString()!));
        object? Decode() => packet.Main == 122 ? TimeCubeProtocol.Decode(packet) : DailyTaskProtocol.Decode(packet);
        if (v.GetProperty("error").GetBoolean())
        {
            Assert.Throws<ProtocolException>(() => Decode());
            Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet));
        }
        else
        {
            var expected = JsonNode.Parse(v.GetProperty("event").GetRawText());
            Assert.True(JsonNode.DeepEquals(expected, Event(Decode())), json);
            var dispatched = ServerProtocol.Decode(packet);
            if (expected is null) Assert.IsType<UnimplementedServerEvent>(dispatched);
            else
            {
                object inner = packet.Main == 122 ? Assert.IsType<ServerTimeCubeEvent>(dispatched).Event : Assert.IsType<ServerDailyTaskEvent>(dispatched).Event;
                Assert.True(JsonNode.DeepEquals(expected, Event(inner)), json);
                Assert.Equal(expected["type"]!.GetValue<string>(), dispatched.Type);
            }
        }
    }

    internal static AutomationContext SafeContext() => new()
    {
        WorldReady = true, InitialDataComplete = true, RoleId = 1, WorldAcknowledged = true, AutomationEnabled = true, ResourceHeld = false,
        Bag = new() { Ready = true, Reliable = true, Capacity = 10, Revision = 1 }
    };
    internal static DailyTaskCatalog Catalog(string variant = "base")
    {
        ImmutableArray<TaskAward> awards = variant switch
        {
            "items" => [new(10, 100, 2), new(11, 100, 1), new(10, 200, 1)],
            "unknown" => [new(99, 1, 1)], "empty" => [], "zero" => [new(10, 100, 0)], _ => [new(12, 1, 10)]
        };
        return new([new(1, 1, 200, 1, 1, awards), new(2, 2, 900, 9, 1, [new(12, 1, 10)])],
            [new(1, 1, 20, [new(2, 0, 10)]), new(2, 2, 20, [new(2, 0, 10)])]);
    }
    private static JsonObject View(TimeCubeState s) => Object(new
    {
        enabled = s.Enabled, ready = s.Ready, count = s.Count, deadline = s.Deadline, role_id = s.RoleId,
        pending = s.Pending is null ? null : new { count = s.Pending.Count, bag_revision = s.Pending.BagRevision, count_updated = s.Pending.CountUpdated, due = s.Pending.Due },
        uncertain = s.Uncertain, revision = s.Revision, status = s.Status, item_id = s.ItemId, check_minutes = s.CheckMinutes
    });
    private static JsonObject View(DailyTaskState s)
    {
        var result = Marks(s.Marks);
        if (s.DailyValue is null) result["weekly_done_mark"] = new JsonArray();
        var rest = Object(new
        {
            enabled = s.Enabled, pending = Pending(s.Pending), uncertain = s.Uncertain, handled = s.Handled.Count,
            role_id = s.RoleId, generation = s.Generation, revision = s.Revision, catalog_token = s.CatalogToken, catalog_ready = s.CatalogReady,
            rows = s.Rows.Select(r => new { cycle = r.Definition.Cycle, index = r.Definition.Index, id = r.Definition.Id, progress = r.Progress, received = r.Received, eligible = r.Eligible }),
            chests = s.Chests.Select(r => new { cycle = r.Cycle, kind = r.Definition.Kind, mark = r.Definition.Mark, value = r.Definition.Value, received = r.Received, eligible = r.Eligible }),
            groups_ahead = s.GroupsAhead, awaiting_groups = s.AwaitingGroups, status = s.Status, ready = s.Ready, groups_ready = s.GroupsReady,
            daily_group = s.DailyGroup, weekly_group = s.WeeklyGroup, daily_value = s.DailyValue, weekly_value = s.WeeklyValue,
            daily_progress = s.DailyProgress.Select(v => (int)v).ToArray(), weekly_progress = s.WeeklyProgress.Select(v => (int)v).ToArray(),
            daily_event_active = s.DailyEventActive, weekly_event_active = s.WeeklyEventActive, last_notice = s.LastNotice
        });
        foreach (var (key, value) in rest) result[key] = value?.DeepClone();
        return result;
    }
    private static object? Pending(TaskPending? p) => p is null ? null : new
    {
        kind = p.Candidate.Kind == TaskClaimKind.Task ? "task" : "chest", cycle = p.Candidate.Cycle,
        index = p.Candidate.Index, id = p.Candidate.Id, flags = Flags(p.Candidate.Flags), awards = Awards(p.Candidate.Awards),
        token = p.Token, role = p.Role, generation = p.Generation, due = p.Due, notice = p.Notice, slots = p.Slots,
        bag_revision = p.BagRevision, item_rewards = p.ItemRewards, item_before = p.ItemBefore
    };
    [Theory, MemberData(nameof(SequenceCases))]
    public void LifecyclesMatchRetainedPythonAfterEveryStep(string json)
    {
        using var doc = JsonDocument.Parse(json); var scenario = doc.RootElement;
        bool cube = scenario.GetProperty("service").GetString() == "time_cube";
        var context = SafeContext(); var catalog = Catalog(scenario.GetProperty("variant").GetString()!);
        var input = new DailyCatalogInput(catalog, "synthetic-A", "catalog unavailable");
        var cs = TimeCubeService.WorldPlayer(new(), 1); var ds = DailyTaskService.WorldPlayer(new(), 1);
        int step = 0;
        foreach (var row in scenario.GetProperty("steps").EnumerateArray())
        {
            var operation = row.GetProperty("input"); string op = operation.GetProperty("op").GetString()!;
            Packet? candidate = null; bool error = false;
            try
            {
                switch (op)
                {
                    case "packet":
                        var packet = new Packet(operation.GetProperty("main").GetInt32(), operation.GetProperty("sub").GetInt32(), Convert.FromHexString(operation.GetProperty("hex").GetString()!));
                        if (cube && TimeCubeProtocol.Decode(packet) is { } ce) cs = TimeCubeService.Apply(cs, ce, context.RoleId, 0);
                        if (!cube && DailyTaskProtocol.Decode(packet) is { } de) ds = DailyTaskService.Apply(ds, de);
                        break;
                    case "tick":
                        if (cube) { var plan = TimeCubeService.Tick(cs, context, operation.GetProperty("now").GetDouble()); cs = plan.State; candidate = plan.Candidate; }
                        else { var plan = DailyTaskService.Tick(ds, context, input, operation.GetProperty("now").GetDouble()); ds = plan.State; candidate = plan.Candidate; }
                        break;
                    case "request":
                        if (cube) { var plan = TimeCubeService.RequestOpen(cs, context, operation.GetProperty("now").GetDouble()); cs = plan.State; candidate = plan.Candidate; }
                        else
                        {
                            var action = operation.GetProperty("action").GetString() switch { "task" => DailyClaimAction.Task, "chest" => DailyClaimAction.Chest, _ => DailyClaimAction.ClaimReady };
                            var plan = DailyTaskService.Request(ds, context, input, action, operation.GetProperty("now").GetDouble(),
                                operation.TryGetProperty("index", out var ix) ? ix.GetInt32() : null, operation.TryGetProperty("cycle", out var cy) ? cy.GetInt32() : null);
                            ds = plan.State; candidate = plan.Candidate;
                        }
                        break;
                    case "auto":
                        if (cube) cs = TimeCubeService.SetAutomatic(cs, operation.GetProperty("enabled").GetBoolean(), context.ResourceHeld);
                        else ds = DailyTaskService.SetAutomatic(ds, operation.GetProperty("enabled").GetBoolean(), context.ResourceHeld);
                        break;
                    case "bag": context = context with { Bag = Bag(context.Bag, operation) }; break;
                    case "context": context = Context(context, operation); break;
                    case "catalog": input = input with
                        { Token = operation.TryGetProperty("token", out var tok) ? tok.GetString() : input.Token,
                          Catalog = operation.TryGetProperty("available", out var av) ? av.GetBoolean() ? catalog : null : input.Catalog }; break;
                    case "role":
                        uint role = operation.GetProperty("role").GetUInt32(); context = context with { RoleId = role };
                        if (cube) cs = TimeCubeService.WorldPlayer(cs, role); else ds = DailyTaskService.WorldPlayer(ds, role); break;
                    case "role_list": if (cube) cs = TimeCubeService.RoleListAvailable(); else ds = DailyTaskService.RoleListAvailable(); break;
                    case "disconnect": if (cube) cs = TimeCubeService.Disconnect(cs); else ds = DailyTaskService.Disconnect(ds); break;
                    default: throw new InvalidOperationException(op);
                }
            }
            catch (ProtocolException) { error = true; }
            string label = $"{scenario.GetProperty("name").GetString()} step {step++}: {operation}";
            Assert.True(row.GetProperty("error").GetBoolean() == error, label + " error mismatch");
            string[] packets = candidate is null ? [] : [Convert.ToHexString(candidate.Body()).ToLowerInvariant()];
            Assert.Equal(row.GetProperty("packets").EnumerateArray().Select(p => p.GetString()), packets);
            var expected = JsonNode.Parse(row.GetProperty("state").GetRawText()); var actual = cube ? View(cs) : View(ds);
            Assert.True(JsonNode.DeepEquals(expected, actual), label + "\nExpected: " + expected + "\nActual: " + actual);
        }
    }
    private static RewardBag Bag(RewardBag bag, JsonElement op)
    {
        foreach (var p in op.EnumerateObject()) bag = p.Name switch
        {
            "items" => bag with { Items = p.Value.EnumerateArray().Select(i => new BagSlot(i.GetProperty("index").GetInt32(), i.GetProperty("item_id").GetInt32(), i.GetProperty("count").GetInt32())).ToImmutableArray() },
            "revision" => bag with { Revision = p.Value.GetInt64() }, "capacity" => bag with { Capacity = p.Value.GetInt32() },
            "ready" => bag with { Ready = p.Value.GetBoolean() }, "reliable" => bag with { Reliable = p.Value.GetBoolean() },
            "held" => bag with { HasHolds = p.Value.GetBoolean() }, "reserved" => bag with { HasReservedItems = p.Value.GetBoolean() },
            "supply" => bag with { SupplyPending = p.Value.GetBoolean() }, _ => bag
        };
        return bag;
    }
    private static ServiceActivity Service(JsonElement value)
    {
        bool Bool(string key) => value.TryGetProperty(key, out var v) && v.ValueKind is not (JsonValueKind.Null or JsonValueKind.False) && v.GetRawText() != "{}";
        return new(Bool("pending"), Bool("uncertain"), Bool("enabled"), Bool("auto_continue"), Bool("checking"));
    }
    private static AutomationContext Context(AutomationContext context, JsonElement op)
    {
        foreach (var p in op.EnumerateObject()) context = p.Name switch
        {
            "ack" => context with { WorldAcknowledged = p.Value.GetBoolean() }, "held" => context with { ResourceHeld = p.Value.GetBoolean() },
            "world" => context with { WorldReady = p.Value.GetBoolean() }, "initial" => context with { InitialDataComplete = p.Value.GetBoolean() },
            "role" => context with { RoleId = p.Value.GetUInt32() }, "auto" => context with { AutomationEnabled = p.Value.GetBoolean() },
            "battle" => context with { BattleActive = p.Value.GetBoolean() }, "event" => context with { EventBlocked = p.Value.GetBoolean() },
            "post" => context with { PostBattleIncomplete = p.Value.GetBoolean() }, "activities" => context with { HasActivities = p.Value.GetBoolean() },
            "supply" => context with { SupplyActive = p.Value.GetBoolean() }, "instance" => context with { InstanceRewardActive = p.Value.GetBoolean() },
            "star_ark" => context with { StarArk = Service(p.Value) }, "guild_actions" => context with { Guild = Service(p.Value) },
            "time_cube" => context with { TimeCube = Service(p.Value) }, "daily_tasks" => context with { DailyTasks = Service(p.Value) },
            "room_storage" => context with { RoomStorage = Service(p.Value) }, "maintenance" => context with { Maintenance = Service(p.Value) },
            "expedition" => context with { Expedition = Service(p.Value) }, "alchemy" => context with { Alchemy = Service(p.Value) },
            "crafting" => context with { Crafting = Service(p.Value) }, _ => context
        };
        return context;
    }
}
