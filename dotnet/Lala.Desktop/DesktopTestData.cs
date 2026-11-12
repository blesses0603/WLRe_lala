using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World;

namespace Lala.Desktop;

/// <summary>Synthetic input used only by explicitly requested self-tests. No live source or credentials.</summary>
internal static class DesktopTestData
{
    public const uint PlayerId = 987654;
    public const ushort SceneId = 54321;
    public const string Identity = "介面測試-離線帳號";

    public static (ServiceStateSnapshot State, DesktopLabels Labels) Create(int itemCount = 30)
    {
        if (itemCount is < 0 or > 200) throw new ArgumentOutOfRangeException(nameof(itemCount));
        var items = ImmutableDictionary.CreateBuilder<byte, BagItemSnapshot>();
        var itemNames = ImmutableDictionary.CreateBuilder<ushort, string>();
        for (int i = 1; i <= itemCount; i++)
        {
            var index = checked((byte)i);
            var id = checked((ushort)(1000 + i));
            var item = Item(index, id, checked((byte)(20 + i)));
            if (i == 2) item = item with { Locked = true };
            items.Add(index, new(item, index, item.Count, item.Damage));
            itemNames.Add(id, $"介面測試道具 {i:00}");
        }
        var player = new WorldPlayer(PlayerId, 0, SceneId, 120, 240, 0, 0, 0, 0, 0, 0, false, [], "介面測試角色", 0);
        var role = new RoleSnapshot(1, "介面測試角色", 20, 3, 1000, 720, 300, 180,
            12345, 4321, 0, 0, 0, 0, 0, 0, SceneId, 0, false, new(0, 0, 0, 0, 0, 0, 0, 0, 0));
        var session = new SessionEventSnapshot
        {
            Phase = "world_ready", PacketCount = 42, InitialDataComplete = true, Roles = [role],
            Gold = new() { Ready = true, Reliable = true, Amount = 4321, Source = "介面測試" }
        };
        var world = new WorldEventSnapshot
        {
            Phase = session.Phase, PacketCount = session.PacketCount, Player = player,
            Location = new() { ConfirmedIsCurrent = true, Confirmed = new(SceneId, 120, 240, "介面測試") },
            Navigation = new() { Scene = SceneId, Reasons = ["介面測試不提供正式地圖"] }
        };
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(1, 1,
        [
            Unit(1, 1, PlayerId, 0, 0, 720, "介面測試角色"),
            Unit(2, 1, 9001, 1, PlayerId, 460, "介面測試夥伴"),
            Unit(3, 2, 8801, 0, 0, 300, "介面測試目標"),
            Unit(4, 4, 8802, 0, 0, 0, "介面測試陣亡單位")
        ]));
        battle = BattleEventReducer.Apply(battle, new RoundStartEvent(2));
        var companion = new CompanionSnapshot(1, 9001, 500, 18, 460, 120, 20, 30, 40, 25, 15,
            0, 90, 1, 8, "介面測試夥伴", [], [], 0, 0, 0, 0, 0, null, 0);
        var companions = new CompanionReceiveSnapshot
        {
            Ready = true, ActiveNpcId = 9001, CompanionOrder = [1],
            Companions = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty.Add(1,
                new(companion, ImmutableDictionary<uint, CompanionLearnedSkill>.Empty
                    .Add(2101, new(3, 10, "介面測試觀測")).Add(2104, new(1, 0, "介面測試觀測")),
                    ImmutableDictionary<string, long>.Empty))
        };
        var knowledge = new PlayerKnowledgeSnapshot
        {
            Ready = true,
            Skills = ImmutableDictionary<uint, PlayerSkillEvidence>.Empty
                .Add(2101, new(4, 20, "介面測試觀測")).Add(2102, new(2, 0, "介面測試觀測"))
                .Add(2103, new(0, 0, "介面測試零級")).Add(2199, new(5, 0, "介面測試已移除")),
            SkillOrder = [2101, 2102, 2103, 2199], RemovedSkillIds = [2199],
            Stats = ImmutableDictionary<string, long>.Empty.Add("hp", 720).Add("max_hp", 1000)
                .Add("sp", 180).Add("max_sp", 300).Add("level", 20).Add("exp", 12345)
                .Add("element", 3).Add("str", 30).Add("con", 40).Add("int", 25).Add("wis", 20).Add("agi", 18)
        };
        var storage = new StorageReceiveSnapshot
        {
            Storage = new()
            {
                Status = "介面測試儲藏資料", ParametersReady = true,
                Garage = new()
                {
                    Ready = true, Reliable = true, Capacity = 300, ItemOrder = [257],
                    Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(257, new(257, 1001, 300))
                },
                Materials = new()
                {
                    Ready = true, Reliable = true, Capacity = ushort.MaxValue, ItemOrder = [65535],
                    Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(65535, new(65535, 1002, 90000))
                }
            }
        };
        var expedition = new ExpeditionReceiveSnapshot
        {
            Ready = true, OutpostReady = true, Level = 1, Status = "介面測試遠征觀測", Claimed = 2,
            Quests = ImmutableDictionary<byte, ushort>.Empty.Add(1, 410).Add(2, 411).Add(3, 499),
            Roles = ImmutableDictionary<byte, ExpeditionOutpostState>.Empty
                .Add(1, new(1, 9001, 0, new(20, 30, 40, 25, 15, 18, 0, 0), 90, 500, 0, 0, 0))
                .Add(2, new(2, 9002, 1, new(15, 20, 25, 15, 20, 16, 0, 0), 75, 400, 0, 0, 0)),
            Teams = ImmutableDictionary<byte, ExpeditionTeamState>.Empty.Add(1, new(1, 90, [9002], null, 411, null))
        };
        var bag = new BagReceiveSnapshot
        {
            Ready = true, Reliable = true, Capacity = 36, Items = items.ToImmutable(),
            ItemOrder = items.Keys.Order().ToImmutableArray(),
            Reserved = itemCount == 0 ? ImmutableDictionary<ushort, BigInteger>.Empty
                : ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 3)
        };
        var state = new ServiceStateSnapshot(new(session, world, battle), storage: storage,
            bag: bag, companions: companions, playerKnowledge: knowledge, expedition: expedition);
        var labels = new DesktopLabels
        {
            Items = itemNames.ToImmutable(),
            Skills = ImmutableDictionary<uint, string>.Empty.Add(2101, "介面測試共同特技")
                .Add(2102, "介面測試角色特技").Add(2104, "介面測試夥伴特技"),
            Scenes = ImmutableDictionary<ushort, string>.Empty.Add(SceneId, "介面測試地圖"),
            Npcs = ImmutableDictionary<ushort, string>.Empty.Add(9001, "介面測試夥伴")
                .Add(9002, "介面測試遠征夥伴"),
            ExpeditionTasks = ImmutableDictionary<ushort, string>.Empty.Add(410, "介面測試採集任務")
                .Add(411, "介面測試探索任務")
        };
        return (state, labels);
    }

    public static BattleUnit Unit(byte col, byte row, uint pid, ushort npcIndex, uint master, uint hp, string name) =>
        new(0, 0, pid, npcIndex, master, col, row, 1000, 300, hp, 100, 20, 3, 0, 0, 0, 0, 0, 0, 0, 0, name, []);

    private static ItemSave Item(byte index, ushort id, byte count) => new(
        Index: index, ItemId: id, Count: count, Damage: 0, SerialVersion: 0, Serial: index,
        Durable: 250, Firing: 0, MagicSpar: 0, AvailableTime: 0, LimitedTime: 0,
        BeatLevel: 0, Differ: 0, Modeling: 0, GetItemId: null, SaddleBeatLevel: 0,
        EnhanceLevel: 0, DesignId: 0, Plugins: [], Locked: false, StarSoulKind: 0,
        StarSoulLevel: 0, ShowMessage: null);
}
