using System.Collections.Immutable;
using Lala.Core.Activities;
using Lala.Core.Social;
using Lala.Core.Instances;
using Lala.Core.Automation;
using Lala.Core.Inventory;
using Lala.Core.Social.Ark;
using Lala.Core.World.Tent;

namespace Lala.Core.Protocol;

/// <summary>Typed offline dispatcher for wlre/network/protocol.py. Decoder precedence is retained.
/// Unported service families return explicit metadata-only unsupported results, never a guessed
/// direct fallback. No transport, state mutation, credential retention or command authorization.</summary>
public static class ServerProtocol
{
    public static ServerEvent Decode(Packet packet) => Decode(packet, null);

    public static ServerEvent Decode(Packet packet, uint? localRoleId) => Decode(packet, localRoleId, null);

    public static ServerEvent Decode(Packet packet, uint? localRoleId, CraftingScheduleContext? craftingSchedules)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if (ChatDecoder.Decode(packet, localRoleId) is { } chat) return new ServerSocialEvent(chat);
        if (GuildActionsDecoder.Decode(packet) is { } actions) return new ServerSocialEvent(actions);
        if (GuildDecoder.Decode(packet) is { } guild) return new ServerSocialEvent(guild);
        if (UnsupportedDecoder(packet, craftingSchedules) is { } decoder)
            return new UnsupportedServerDecoderEvent(packet.Main, packet.Sub, decoder, packet.Payload.Length);
        if (ArkDecoder.Decode(packet) is { } ark) return ark;
        if (DailyTaskProtocol.Decode(packet) is { } daily) return new ServerDailyTaskEvent(packet.Sub, daily);
        if (TimeCubeProtocol.Decode(packet) is { } cube) return new ServerTimeCubeEvent(packet.Sub, cube);
        if (InstanceDecoder.Decode(packet) is { } instance) return new ServerInstanceEvent(packet.Main, packet.Sub, instance);
        if (StorageDecoder.Decode(packet) is { } storage) return new ServerInventoryEvent(storage);
        if (ExpeditionDecoder.Decode(packet) is { } expedition) return new ServerExpeditionEvent(packet.Sub, expedition);
        if (RecoveryDecoder.Decode(packet) is { } recovery) return new ServerInventoryEvent(recovery);
        if (ActivityDecoder.Decode(packet) is { } activity) return new ServerActivityEvent(packet.Main, packet.Sub, activity);

        if (CraftingDecoder.Decode(packet, craftingSchedules) is { } crafting) return new ServerInventoryEvent(crafting);

        if (TentDecoder.Decode(packet) is { } tent) return tent;
        var r = new PacketReader(packet.Payload.Span);
        if (Geometry(packet, r) is { } geometry) return geometry;
        if (SocialProtocol.Decode(packet) is { } social) return new ServerSocialEvent(social);
        if (LiveDataProtocol.Decode(packet) is { } live) return new ServerLiveDataEvent(live);
        if (LayoutProtocol.Decode(packet) is { } layout) return new ServerLayoutEvent(layout);
        ServerEvent result;
        switch (packet.Main, packet.Sub)
        {
            case (22, 2): result = new SceneNpcMoveEvent(r.U16(), r.U16(), r.U16(), r.U8()); break;
            case (22, 3 or 10 or 11): result = new SceneNpcVisibilityEvent(packet.Sub, r.U16(), r.U16()); break;
            case (22,4):
                if(r.Remaining%14!=0)throw new ProtocolException("invalid scene NPC status length");
                var npcs=ImmutableArray.CreateBuilder<SceneNpcStatus>(r.Remaining/14);
                while(r.Remaining>0)npcs.Add(new(r.U16(),r.U8(),r.U8(),r.U16(),r.U16(),r.U8(),r.U32(),r.U8()));
                result=new SceneNpcStatusEvent(npcs.MoveToImmutable());break;
            case (22,5): result=new SceneNpcTeleportEvent(r.U16(),r.U16(),r.U16());break;
            case (22,6): result=new SceneNpcShowEvent(r.U16(),r.U8());break;
            case (26, 1): case (26, 2):
                var amount = r.U32(); var flag = r.U8();
                if (flag > 1) throw new ProtocolException("S26 金幣通知旗標無效");
                result = new GoldDeltaEvent(packet.Sub, packet.Sub == 1 ? amount : -(long)amount, flag == 1); break;
            case (26, 4): result = new GoldSnapshotEvent(r.U32()); break;
            case (26, 3): r.Take(r.Remaining); result = new GoldLimitEvent(); break;
            case (20, 8): r.Take(r.Remaining); result = new EventEndEvent(); break;
            case (20, 7 or 10 or 11 or 13 or 14 or 15 or 16 or 17):
                result = new EventContinuePermissionEvent(packet.Sub, r.Remaining); r.Take(r.Remaining); break;
            case (20, >= 1 and <= 6):
                return new NpcEffectEvent(packet.Sub, DecodeNpcEffect(packet.Payload.Span), packet.Payload.Length);
            case (20, 9 or 12 or 46 or 58 or 67 or 70):
                r.Take(r.Remaining); result = new EventActiveEvent(packet.Sub); break;
            case (20, 74):
                var reason = r.U8(); r.Take(r.Remaining);
                result = new EventRejectedEvent(reason, reason switch
                {
                    1 => "超出事件互動範圍，請靠近後再嘗試；伺服器未接受直接換圖",
                    2 => "伺服器找不到場景", 3 => "伺服器找不到場景 NPC", 4 => "伺服器找不到場景 NPC 索引",
                    _ => $"伺服器拒絕事件，原因代碼 {reason}"
                }); break;
            case (1, 23): result = new HeartbeatRequestEvent(); break;
            case (1, 11): result = new InitialDataCompleteEvent(); break;
            case (1, 4):
                var accountId = r.U32();
                for (var i = 0; i < 3; i++) r.Take(r.U8()); // Consume echo bytes, never decode or retain credentials.
                result = new AccountIdentityEvent(accountId); break;
            case (63, 7): result = new LoginResultEvent(r.U8(), r.U8()); break;
            case (6, 2): result = new MovementStopEvent(r.U8()); break;
            case (7, 1): case (12, 1):
                var roleId = r.U32(); var scene = r.U16(); var x = r.U16(); var y = r.U16();
                var length = r.Remaining; var floor = DecodeHouseFloorExtension(r.Take(length));
                result = new PositionSnapshotEvent(packet.Main, roleId, scene, x, y, length, floor); break;
            case (51, 1):
                if (r.Remaining % 7 != 0)
                    return new BattleAttributeInvalidEvent(r.Remaining, r.Remaining / 7, r.Remaining % 7);
                var values = ImmutableArray.CreateBuilder<BattleAttributeValue>(r.Remaining / 7);
                while (r.Remaining != 0) values.Add(new(r.U8(), r.U8(), r.U8(), r.U32()));
                result = new BattleAttributeSetEvent(values.MoveToImmutable()); break;
            case (52, 1): result = new RoundStartEvent(r.U16()); break;
            case (11, 1):
                var col = r.U8(); var row = r.U8();
                result = new BattleUnitExitEvent(col, row, r.Remaining == 1 ? r.U8() : null); break;
            case (8, 4): result = new AttributeAllocationSuccessEvent(); break;
            case (8, 1 or 2 or 3): result = ReadAttribute(packet.Sub, r); break;
            case (6, 1): result = new WalkEvent(r.I32(), r.U16(), r.U16()); break;
            case (11, 10): result = new WarStyleEvent(r.U8()); break;
            case (11, 12): result = new WinnerEvent(r.U8()); break;
            case (11, 0): result = new FightExitEvent(r.U32(), r.U16()); break;
            case (50, 1): result = ReadAttack(r); break;
            default: return new UnimplementedServerEvent(packet.Main, packet.Sub, packet.Payload.Length);
        }
        r.End(); return result;
    }

    /// <summary>Only public C6-1 coordinates; all other outbound packets are ignored without parsing.</summary>
    public static MovementRequestEvent? DecodeOutboundMovement(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if ((packet.Main, packet.Sub) != (6, 1)) return null;
        var r = new PacketReader(packet.Payload.Span);
        var result = new MovementRequestEvent(r.U16(), r.U16()); r.End(); return result;
    }

    /// <summary>Pure 18-byte S20 effect header. A short effect is still blocking, with no decoded details.</summary>
    public static NpcEffect? DecodeNpcEffect(ReadOnlySpan<byte> payload)
    {
        if (payload.Length < 18) return null;
        var r = new PacketReader(payload);
        return new(r.U8(), r.U16(), r.U8(), r.U8(), r.U8(), r.U16(), r.U8(), r.U32(), r.U16(), r.U8(), r.U16(), r.Remaining);
    }

    /// <summary>Exact pure decode_floor_extension port. Unverified extensions grant no house model mapping.</summary>
    public static HouseFloorExtension DecodeHouseFloorExtension(ReadOnlySpan<byte> extension)
    {
        if (extension.Length is not (1 or 3 or 5)) return new(false);
        var payload = extension.Length > 2 ? extension[2..] : extension;
        if (payload[0] > 3) return new(false);
        var floor = (byte)(payload[0] + 1);
        if (payload.Length != 3) return new(true, floor);
        if (payload[1] is < 1 or > 3 || payload[2] > 3) return new(false);
        return new(true, floor, payload[1], (byte)(payload[2] + 1));
    }

    private static NavigationGeometryChangeEvent? Geometry(Packet packet, PacketReader r)
    {
        var (reason, minimum) = (packet.Main, packet.Sub) switch
        {
            // S62-1/2/4 are shadowed by crafting; do not fall back to the old shallow branches.
            (62, 3) => ("furniture_moved", 15), (62, 64) => ("house_floor_changed", 0),
            (65, 13) => ("pillar_changed", 2), (23, 74) => ("bath_exit_obstacle_toggle", 5),
            (23, 76) => ("seat_exit_obstacle_toggle", 4), (62, 70) => ("bed_exit_obstacle_toggle", 4),
            _ => (null, 0)
        };
        if (reason is null) return null;
        r.Take(minimum); r.Take(r.Remaining);
        uint? clear = (packet.Main, packet.Sub) == (23, 76)
            ? System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(packet.Payload.Span) : null;
        return new(packet.Main, packet.Sub, reason, true, packet.Payload.Length, clear);
    }

    private static AttributeSetEvent ReadAttribute(byte sub, PacketReader r)
    {
        byte? humanKind = null; ushort? index = null;
        var entity = "self";
        if (sub == 2) { humanKind = r.U8(); index = r.U16(); entity = $"follow:{index}"; }
        else if (sub == 3) entity = $"player:{r.U32()}";
        var kind = r.U8(); var sign = r.U8(); var value = r.U32(); var parameter = r.U32();
        return new(sub, entity, humanKind, index, kind, ServerProtocolNames.Attribute(kind), sign,
            sign == 2 ? -(long)value : value, parameter);
    }

    private static AttackResultEvent ReadAttack(PacketReader r)
    {
        var count = r.U8(); var actions = ImmutableArray.CreateBuilder<AttackAction>(count);
        for (var i = 0; i < count; i++)
        {
            var col = r.U8(); var row = r.U8(); var skill = r.U16(); var level = r.U8(); var area = r.U8();
            var targetCount = r.U8(); var targets = ImmutableArray.CreateBuilder<AttackTarget>(targetCount);
            for (var j = 0; j < targetCount; j++)
            {
                var targetCol = r.U8(); var targetRow = r.U8(); var attackResult = r.U8(); var hitAction = r.U8();
                var attributeCount = r.U8(); var attributes = ImmutableArray.CreateBuilder<AttackAttribute>(attributeCount);
                for (var k = 0; k < attributeCount; k++)
                {
                    var kind = r.U8(); var value = r.U32(); var sign = r.U8();
                    attributes.Add(new(kind, ServerProtocolNames.Attribute(kind), value, sign));
                }
                targets.Add(new(targetCol, targetRow, attackResult, hitAction, attributes.MoveToImmutable()));
            }
            actions.Add(new(col, row, skill, level, area, ServerProtocolNames.Skill(skill), targets.MoveToImmutable()));
        }
        return new(actions.MoveToImmutable());
    }

    // Classify only by published packet keys. Contents remain unparsed and are not returned.
    // These guards precede every migrated fallback exactly where the Python service chain does.
    private static string? UnsupportedDecoder(Packet p, CraftingScheduleContext? craftingSchedules) => (p.Main, p.Sub) switch
    {
        (64, 1 or 16) when craftingSchedules is null => "crafting",
        _ => null
    };
}
