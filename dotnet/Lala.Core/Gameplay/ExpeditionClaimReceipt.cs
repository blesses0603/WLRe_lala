using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;

namespace Lala.Core.Gameplay;

/// <summary>Matches the selected team's result plus actual item admission. A cleared team
/// alone is not proof that its rewards reached the bag.</summary>
internal sealed class ExpeditionClaimReceipt(int index,BagReceiveSnapshot before)
{
    private readonly Dictionary<ushort,BigInteger> original=Totals(before);
    private ImmutableArray<ExpeditionReward>? result;
    private readonly Dictionary<ushort,BigInteger> expected=[];
    internal void Observe(GameServerEvent receipt)
    {
        if(receipt.Type=="expedition_rejected")throw new ProtocolException("伺服器拒絕遠征操作，停止接續。");
        if(receipt.Type!="expedition_result"||receipt.Index!=index)return;
        if(receipt.Rewards.IsDefault)throw new ProtocolException("遠征獎勵回覆不完整。");
        if(result is {} previous)
        {
            if(!previous.SequenceEqual(receipt.Rewards))throw new ProtocolException("遠征獎勵回覆不一致，停止接續。");
            return;
        }
        foreach(var award in receipt.Rewards)
        {
            if(award.Kind is 10 or 11)
            {
                if(award.Value==0)continue;
                if(award.Id is 0 or >ushort.MaxValue)throw new ProtocolException("遠征物品編號未能核對。");
                ushort item=(ushort)award.Id;expected[item]=expected.GetValueOrDefault(item)+award.Value;
            }
            else if(award.Kind is not (0 or 1 or 2 or 6 or 12 or >=21 and <=31))
                throw new ProtocolException("遠征獎勵含未支援類型，停止接續。");
        }
        result=receipt.Rewards;
    }
    internal bool Acknowledged(bool teamCleared,BagReceiveSnapshot bag)
    {
        if(!teamCleared||result is null||!bag.Ready||!bag.Reliable)return false;
        var totals=Totals(bag);
        return expected.All(p=>totals.GetValueOrDefault(p.Key)>=original.GetValueOrDefault(p.Key)+p.Value);
    }
    private static Dictionary<ushort,BigInteger> Totals(BagReceiveSnapshot bag)=>bag.Items.Values.GroupBy(i=>i.ItemId)
        .ToDictionary(g=>g.Key,g=>g.Aggregate(BigInteger.Zero,(sum,i)=>sum+i.Count));
}
