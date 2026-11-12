using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public void A_cleared_team_does_not_confirm_rewards_until_matching_result_and_items_arrive()
    {
        var before=RecoveryState(count:3).Bag;var claim=new ExpeditionClaimReceipt(1,before);
        var after=RecoveryState(count:5).Bag;
        Assert.False(claim.Acknowledged(true,after));
        claim.Observe(new(1,31,16,"expedition_result","",Index:2){Rewards=[new(10,20,2)]});
        Assert.False(claim.Acknowledged(true,after));
        var result=new GameServerEvent(2,31,16,"expedition_result","",Index:1){Rewards=[new(10,20,2)]};
        claim.Observe(result);claim.Observe(result);
        Assert.False(claim.Acknowledged(true,before));Assert.False(claim.Acknowledged(false,after));
        Assert.True(claim.Acknowledged(true,after));
        Assert.False(claim.Acknowledged(true,after with{Reliable=false}));
        Assert.Throws<ProtocolException>(()=>claim.Observe(result with{Rewards=[new(10,20,3)]}));
    }
    [Fact]
    public void Unknown_rewards_or_rejections_never_confirm_a_claim()
    {
        var claim=new ExpeditionClaimReceipt(1,RecoveryState().Bag);
        Assert.Throws<ProtocolException>(()=>claim.Observe(new(1,31,16,"expedition_result","",Index:1){Rewards=[new(200,20,2)]}));
        Assert.Throws<ProtocolException>(()=>claim.Observe(new(2,31,10,"expedition_rejected","")));
    }
}
