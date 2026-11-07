using System.Collections.Immutable;

namespace Lala.Core.Protocol;

public sealed record TeamSnapshot(uint LeaderId, ImmutableArray<uint> Members);
public sealed record NearbyPlayer(uint RoleId, byte Sex, byte Element, byte Level, ushort Scene,
    ushort X, ushort Y, byte Degree, byte Job, string Name);
public enum TeamAnswerTarget { Application, Invite }

public abstract record SocialEvent(byte Main, byte Sub)
{
    public abstract string Type { get; }
}
public sealed record TeamApplicationEvent(uint RoleId) : SocialEvent(13, 1)
{
    public override string Type => "team_application";
}
public sealed record TeamLeaveEvent(uint RoleId) : SocialEvent(13, 4)
{
    public override string Type => "team_leave";
}
public sealed record TeamInviteEvent(uint RoleId) : SocialEvent(13, 9)
{
    public override string Type => "team_invite";
}
public sealed record TeamAnswerEvent(byte Answer, uint RoleId, TeamAnswerTarget AnswerTo)
    : SocialEvent(13, AnswerTo == TeamAnswerTarget.Application ? (byte)3 : (byte)10)
{
    public override string Type => "team_answer";
}
public sealed record TeamJoinEvent(uint LeaderId, uint RoleId) : SocialEvent(13, 5)
{
    public override string Type => "team_join";
}
public sealed record TeamListEvent(ImmutableArray<TeamSnapshot> Teams) : SocialEvent(13, 6)
{
    public override string Type => "team_list";
}
public sealed record TeamLeaderOfferEvent(uint RoleId) : SocialEvent(13, 15)
{
    public override string Type => "team_leader_offer";
}
public sealed record TeamLeaderAnswerEvent(byte Answer, uint? RoleId) : SocialEvent(13, 15)
{
    public override string Type => "team_leader_answer";
}
public sealed record TeamNewLeaderEvent(uint LeaderId, uint OldLeaderId) : SocialEvent(13, 15)
{
    public override string Type => "team_new_leader";
}
public sealed record TeamNoticeEvent(byte Code) : SocialEvent(13, 16)
{
    public override string Type => "team_notice";
}
public sealed record NearbyPlayerEvent(NearbyPlayer Player) : SocialEvent(4, 1)
{
    public override string Type => "nearby_player";
}
public sealed record NearbyLeaveEvent(uint RoleId) : SocialEvent(1, 1)
{
    public override string Type => "nearby_leave";
}
public sealed record TeamFlagEvent(bool Enabled) : SocialEvent(33, 2)
{
    public override string Type => "team_flag";
}
public sealed record SocialRejectedEvent(byte Code) : SocialEvent(33, 1)
{
    public override string Type => "social_rejected";
}
public sealed record AlchemyResultEvent(ushort ItemId, byte Count) : SocialEvent(23, 13)
{
    public override string Type => "alchemy_result";
}
public sealed record AlchemySpaceErrorEvent(byte Code, byte? Needed) : SocialEvent(23, 120)
{
    public override string Type => "alchemy_space_error";
}

/// <summary>Offline packet decoder for wlre/network/social_protocol.py, including its caller's
/// reader.end() check. Returns null for unknown packets or leader-transfer kinds. Recognized
/// malformed packets throw. Only team_flag and alchemy_space_error deliberately discard tails.</summary>
public static class SocialProtocol
{
    public static SocialEvent? Decode(Packet packet)
    {
        var reader = new PacketReader(packet.Payload.Span);
        SocialEvent? result = (packet.Main, packet.Sub) switch
        {
            (13, 1) => new TeamApplicationEvent(reader.U32()),
            (13, 4) => new TeamLeaveEvent(reader.U32()),
            (13, 9) => new TeamInviteEvent(reader.U32()),
            (13, 3) => new TeamAnswerEvent(reader.U8(), reader.U32(), TeamAnswerTarget.Application),
            (13, 10) => new TeamAnswerEvent(reader.U8(), reader.U32(), TeamAnswerTarget.Invite),
            (13, 5) => new TeamJoinEvent(reader.U32(), reader.U32()),
            (13, 6) => ReadTeams(reader),
            (13, 15) => ReadLeaderTransfer(reader),
            (13, 16) => new TeamNoticeEvent(reader.U8()),
            (4, 1) => new NearbyPlayerEvent(ReadNearbyPlayer(reader)),
            (1, 1) => new NearbyLeaveEvent(reader.U32()),
            (33, 2) => ReadTeamFlag(reader),
            (33, 1) => new SocialRejectedEvent(reader.U8()),
            (23, 13) => new AlchemyResultEvent(reader.U16(), reader.U8()),
            (23, 120) => ReadAlchemySpaceError(reader),
            _ => null
        };
        if (result is not null) reader.End();
        return result;
    }

    private static TeamListEvent ReadTeams(PacketReader reader)
    {
        var teams = ImmutableArray.CreateBuilder<TeamSnapshot>();
        while (reader.Remaining != 0)
        {
            var leader = reader.U32(); var count = reader.U8();
            if (leader == 0 || count > 3) throw new ProtocolException("invalid team size");
            var members = ImmutableArray.CreateBuilder<uint>(count + 1);
            members.Add(leader);
            for (var i = 0; i < count; i++) members.Add(reader.U32());
            if (members.Contains(0u) || members.Distinct().Count() != members.Count)
                throw new ProtocolException("invalid team members");
            teams.Add(new(leader, members.MoveToImmutable()));
        }
        return new(teams.ToImmutable());
    }

    private static SocialEvent? ReadLeaderTransfer(PacketReader reader) => reader.U8() switch
    {
        1 => new TeamLeaderOfferEvent(reader.U32()),
        2 => ReadLeaderAnswer(reader),
        3 => new TeamNewLeaderEvent(reader.U32(), reader.U32()),
        _ => null
    };

    private static TeamLeaderAnswerEvent ReadLeaderAnswer(PacketReader reader)
    {
        var answer = reader.U8();
        return new(answer, answer == 2 ? reader.U32() : null);
    }

    private static NearbyPlayer ReadNearbyPlayer(PacketReader reader)
    {
        var roleId = reader.U32(); var sex = reader.U8(); var element = reader.U8(); var level = reader.U8();
        var scene = reader.U16(); var x = reader.U16(); var y = reader.U16();
        reader.Take(3 + 8 + 2);
        var equipmentCount = reader.U8();
        for (var i = 0; i < equipmentCount; i++) reader.Take(6);
        var degree = reader.U8(); var job = reader.U8(); var name = reader.Unicode8();
        ProtocolLayouts.DiscardNamecard(reader);
        reader.U16(); // Nearby events intentionally omit the namecard title as in Python.
        return new(roleId, sex, element, level, scene, x, y, degree, job, name);
    }

    private static TeamFlagEvent ReadTeamFlag(PacketReader reader)
    {
        reader.U8(); reader.U8(); var value = reader.U8(); reader.U8();
        reader.Take(reader.Remaining);
        return new(value == 1);
    }

    private static AlchemySpaceErrorEvent ReadAlchemySpaceError(PacketReader reader)
    {
        var code = reader.U8(); byte? needed = code == 1 ? reader.U8() : null;
        reader.Take(reader.Remaining);
        return new(code, needed);
    }
}
