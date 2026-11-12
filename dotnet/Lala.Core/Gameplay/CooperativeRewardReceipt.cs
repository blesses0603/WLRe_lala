using System.Collections.Immutable;
using Lala.Core.Instances;
using Lala.Core.Inventory;
using Lala.Core.Protocol;

namespace Lala.Core.Gameplay;

internal sealed class CooperativeRewardReceipt(BagReceiveSnapshot before)
{
    private ImmutableArray<InstanceAward>? awards;
    private readonly Dictionary<ushort,long> expected = [];
    private readonly Dictionary<ushort,long> original = before.Items.Values.GroupBy(i=>i.ItemId).ToDictionary(g=>g.Key,g=>g.Sum(i=>(long)i.Count));
    internal void Observe(GameServerEvent e)
    {
        if(e.Type != "instance_reward_receipt")return;
        if(e.InstanceAwards.IsDefaultOrEmpty)throw new ProtocolException("協力獎勵明細尚未確認，請檢查背包或信箱。");
        if(awards is {} previous){if(!previous.SequenceEqual(e.InstanceAwards))throw new ProtocolException("協力獎勵回覆不一致。");return;}
        foreach(var award in e.InstanceAwards)
        {
            if(award.Kind is 10 or 11)
            {
                if(award.Value==0)continue;
                if(award.Id is 0 or >ushort.MaxValue)throw new ProtocolException("協力獎勵物品編號無法核對。");
                ushort id=(ushort)award.Id;expected[id]=expected.GetValueOrDefault(id)+award.Value;
            }
            else if(award.Kind is not (0 or 1 or 2 or 6 or 12 or >=21 and <=31))throw new ProtocolException("協力獎勵含尚未核對的類型。");
        }
        awards=e.InstanceAwards;
    }
    internal bool Acknowledged(BagReceiveSnapshot bag)=>awards is not null&&bag.Ready&&bag.Reliable&&expected.All(p=>
        bag.Items.Values.Where(i=>i.ItemId==p.Key).Sum(i=>(long)i.Count)>=original.GetValueOrDefault(p.Key)+p.Value);
}
