using Lala.Core.Gameplay;
using Xunit;

namespace Lala.Core.Tests.Automation;

public class ExpeditionAutomationPolicyTests
{
    [Fact]
    public void Candidates_rank_by_points_then_duration_then_id_like_python()
    {
        ExpeditionAutomationCandidate[] candidates=[new(1,[1],700,90000,90),new(4,[2],800,3600,70),new(3,[2],800,7200,70),new(2,[2],800,7200,70)];
        Assert.Equal((ushort)2,ExpeditionAutomationPolicy.Choose(candidates)!.Task);
        Assert.Null(ExpeditionAutomationPolicy.Choose([]));
    }
    [Fact]
    public void Recovery_never_targets_an_idle_member_outside_the_chosen_team()
    {
        var chosen=new ExpeditionAutomationCandidate(1,[2,3],900,7200,80);
        Assert.Null(ExpeditionAutomationPolicy.FirstDeficit(chosen,new Dictionary<int,int>{{1,0},{2,100},{3,100}}));
        Assert.Equal(3,ExpeditionAutomationPolicy.FirstDeficit(chosen,new Dictionary<int,int>{{1,0},{2,100},{3,79}}));
    }
}
