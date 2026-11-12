using System.Text.Json;
using Lala.Core.Expedition;
using Xunit;
namespace Lala.Core.Tests.Expedition;
public class ExpeditionTeamsTests
{
    public static IEnumerable<object[]> Cases()
    {
        using var json = JsonDocument.Parse(PythonExpeditionVectors.Json);
        return json.RootElement.EnumerateArray().Select((v, i) => new object[] { i, v.Clone() }).ToArray();
    }
    private static ExpeditionCondition Condition(JsonElement c) => new(c[0].GetInt32(), c[1].GetInt64(), c[2].GetInt64());
    [Theory, MemberData(nameof(Cases))]
    public void MatchesPythonConditionsSuccessAndExactSelection(int index, JsonElement c)
    {
        _ = index;
        var roles = c.GetProperty("roles").EnumerateArray().Select(r =>
        {
            var s = r.GetProperty("stats");
            return new ExpeditionRole(r.GetProperty("index").GetInt32(), r.GetProperty("npc_id").GetInt32(), r.GetProperty("faith").GetInt64(),
                s.GetProperty("level").GetInt64(),s.GetProperty("degree").GetInt64(),s.GetProperty("potential").GetInt64(),
                s.GetProperty("str").GetInt64(),s.GetProperty("con").GetInt64(),s.GetProperty("int").GetInt64(),s.GetProperty("wis").GetInt64(),s.GetProperty("agi").GetInt64());
        }).ToArray();
        long? Optional(JsonElement e, string key) => e.GetProperty(key).ValueKind == JsonValueKind.Null ? null : e.GetProperty(key).GetInt64();
        bool? OptionalBool(JsonElement e) => e.ValueKind == JsonValueKind.Null ? null : e.GetBoolean();
        var npcs = c.GetProperty("npcs").EnumerateObject().ToDictionary(p => int.Parse(p.Name), p => new ExpeditionNpc(Optional(p.Value,"element"),Optional(p.Value,"kind"),Optional(p.Value,"original")));
        var q = c.GetProperty("quest"); var joining = Condition(q.GetProperty("condition"));
        var recs = q.GetProperty("recommendations").EnumerateArray().Select(r => new ExpeditionRecommendation(Condition(r.GetProperty("condition")),r.GetProperty("bonus").GetInt64())).ToArray();
        Assert.Equal(OptionalBool(c.GetProperty("met")), ExpeditionTeams.ConditionMet(joining,roles,npcs));
        var result = ExpeditionTeams.SuccessDetails(q.GetProperty("success_rate").GetInt64(),recs,roles,npcs); var expected = c.GetProperty("success");
        Assert.Equal(expected.GetProperty("points").GetInt64(), result.Points);
        Assert.Equal(expected.GetProperty("percent").GetDecimal(), result.Percent);
        Assert.Equal(expected.GetProperty("complete").GetBoolean(), result.Complete);
        Assert.Equal(expected.GetProperty("recommendations").EnumerateArray().Select(r=>OptionalBool(r.GetProperty("met"))),result.Recommendations.Select(r=>r.Met));
        Assert.Equal(expected.GetProperty("recommendations").EnumerateArray().Select(r=>r.GetProperty("awarded").GetInt64()),result.Recommendations.Select(r=>r.Awarded));
        Assert.Equal(c.GetProperty("selected").EnumerateArray().Select(v=>v.GetInt32()), ExpeditionTeams.ChooseMembers(joining,recs,q.GetProperty("success_rate").GetInt64(),q.GetProperty("faith_cost").GetInt64(),roles,c.GetProperty("threshold").GetInt64(),npcs));
    }
    [Fact] public void CancellationNeverReturnsPartialSelection()
    {
        using var cts = new CancellationTokenSource(); cts.Cancel();
        Assert.Throws<OperationCanceledException>(()=>ExpeditionTeams.ChooseMembers(new(0,0),[],0,0,[],0,cancellationToken:cts.Token));
    }
    [Fact] public void DuplicateSlotsAreRejected()
    {
        Assert.Throws<ArgumentException>(()=>ExpeditionTeams.ChooseMembers(new(0,0),[],0,0,[new(1,1,100),new(1,2,100)],0));
    }
    [Fact] public void UnknownElementDoesNotGrantJoiningEligibility()
    {
        Assert.Null(ExpeditionTeams.ConditionMet(new(2,1,1),[new(1,1,100)]));
        Assert.Empty(ExpeditionTeams.ChooseMembers(new(2,1,1),[],1000,0,[new(1,1,100)],0));
    }
    [Fact] public void FourSlotsAreTheHardLimit()
    {
        var roles = Enumerable.Range(1, 8).Select(i => new ExpeditionRole(i,i,100)).ToArray();
        Assert.Equal(new[] {1,2,3,4}, ExpeditionTeams.ChooseMembers(new(1,4),[],1000,0,roles,0));
        Assert.Empty(ExpeditionTeams.ChooseMembers(new(1,5),[],1000,0,roles,0));
    }
    [Fact] public void FaithCostOverridesLowerRequestedThreshold()
    {
        ExpeditionRole[] roles = [new(1,1,0),new(2,2,100)];
        Assert.Equal(new[] {2}, ExpeditionTeams.ChooseMembers(new(1,1),[],1000,50,roles,0));
    }
    [Fact] public void CappedSuccessIsCompleteEvenWithUnknownRecommendation()
    {
        var success = ExpeditionTeams.SuccessDetails(1000,[new(new(2,1,1),100)],[new(1,1,100)]);
        Assert.True(success.Complete); Assert.Equal(100m,success.Percent);
        Assert.Null(success.Recommendations.Single().Met);
        Assert.Equal(0,success.Recommendations.Single().Awarded);
    }
    [Fact] public void OverflowFailsRatherThanWrappingGameValues()
    {
        Assert.Throws<OverflowException>(() => ExpeditionTeams.ConditionMet(new(5,1),[new(1,1,0,long.MaxValue,1)]));
    }
    [Fact] public void InvalidNegativeValuesCannotCorruptBranchBounds()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => ExpeditionTeams.ChooseMembers(new(0,0),[new(new(5,6),-500)],0,0,[new(1,1,100)],0));
        Assert.Throws<ArgumentOutOfRangeException>(() => ExpeditionTeams.ChooseMembers(new(0,0),[],0,0,[new(1,1,100,Strength:-1)],0));
    }
}
