using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

/// <summary>Folds only an active trusted command's receipt state; stores no packet backlog.
/// Arm at actual write admission. State is synchronized with the command's ACK predicate.</summary>
internal sealed class GameReceiptWatch(GameActionPlan plan)
{
    private readonly object gate=new();
    private long after=long.MaxValue;
    private bool failed;
    internal void Arm(long sequence){lock(gate)after=sequence;}
    internal void Observe(GameServerEvent receipt)
    {
        lock(gate)
        {
            if(receipt.Sequence<=after||failed)return;
            after=receipt.Sequence;
            try{plan.ObserveReceipt?.Invoke(receipt);}
            catch(Exception){failed=true;}
        }
    }
    internal bool Acknowledged(ServiceStateSnapshot state)
    {
        lock(gate)
        {
            if(failed)throw new ProtocolException("伺服器操作回覆無法核對，停止接續。");
            return plan.Acknowledged(state);
        }
    }
}
