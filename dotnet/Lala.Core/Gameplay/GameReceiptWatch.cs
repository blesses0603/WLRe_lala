using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

/// <summary>Folds only an active trusted command's receipt state; stores no packet backlog.
/// Arm at actual write admission. State is synchronized with the command's ACK predicate.</summary>
internal sealed class GameReceiptWatch(GameActionPlan plan)
{
    private readonly object gate=new();
    private long after=long.MaxValue;
    private Exception? failure;
    internal void Arm(long sequence){lock(gate)after=sequence;}
    internal void Observe(GameServerEvent receipt)
    {
        lock(gate)
        {
            if(receipt.Sequence<=after||failure is not null)return;
            after=receipt.Sequence;
            try{plan.ObserveReceipt?.Invoke(receipt);}
            catch(Exception error){failure=error;}
        }
    }
    internal bool Acknowledged(ServiceStateSnapshot state)
    {
        lock(gate)
        {
            if(failure is GameActionRefusedException refused)
            {
                if(plan.RefusalUnchanged?.Invoke(state)==true)throw refused;
                throw new ProtocolException("收到拒絕回覆，但物品或金額也有異動，結果尚未確認。",refused);
            }
            if(failure is not null)throw new ProtocolException("伺服器操作回覆無法核對，停止接續。",failure);
            return plan.Acknowledged(state);
        }
    }
}
