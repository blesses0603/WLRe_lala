using System.Collections.Immutable;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.World.Eve;
using Lala.Core.World.Portals;
using Xunit;

namespace Lala.Core.Tests.Automation;

public sealed class TentExitResolverTests
{
    private static EveDoorRow Door(ushort index = 7) => new(index, new("出口", "", true), 20, 30, [], 0, 0, 0, 0, 0, 0, 0, 0, [1], []);
    private static EveDoorProjection Doors(params EveDoorRow[] doors) => new([new(10000, [..doors])], doors.Length);
    private static OfflineEventPortalProjection Links(params EventPortalDestination[] rows) => new(destinations: rows.Select(r => KeyValuePair.Create(new EventPortalKey(r.Scene, r.Index), r)));
    private static EventPortalDestination Exit(ushort index = 7) => new(10000, index, 101, true, 20, 30, MatchedTouchRegion: true);

    [Fact]
    public void Exit_requires_one_source_matched_index_and_rejects_conflicts_or_unmatched_coordinates()
    {
        Assert.Equal(7, TentExitResolver.Resolve(Doors(Door()), Links(Exit()), new Dictionary<uint, string>(), 101));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door()), Links(Exit() with { EventX = 21 }), new Dictionary<uint, string>(), 101));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door(), Door()), Links(Exit()), new Dictionary<uint, string>(), 101));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door(), Door(8)), Links(Exit(), Exit(8)), new Dictionary<uint, string>(), 101));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door()), new(issues: new Dictionary<EventPortalKey, string> { [new(10000, 7)] = "conflict" }, destinations: new Dictionary<EventPortalKey, EventPortalDestination> { [new(10000, 7)] = Exit() }), new Dictionary<uint, string>(), 101));
    }
    [Fact]
    public void Server_decided_marker_requires_a_recorded_outdoor_return_and_verified_label()
    {
        var marker = Exit() with { Destination = null, DestinationVerified = false, StageMarkerOnly = true, DoorBindingVerified = true, StageMarkerKind = 2, StageMarkerNameId = 5 };
        var texts = new Dictionary<uint, string> { [5] = "離開小屋" };
        Assert.Equal(7, TentExitResolver.Resolve(Doors(Door()), Links(marker), texts, 101));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door()), Links(marker), texts, null));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door()), Links(marker), new Dictionary<uint, string>(), 101));
        Assert.Throws<ProtocolException>(() => TentExitResolver.Resolve(Doors(Door()), Links(marker with { StageMarkerKind = 3, StageMarkerEventId = 1 }), texts, 101));
    }
}
