using System.Diagnostics;
using Lala.Core.Battle;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    /// <summary>Resets account-local observations on the receive owner; sends no packet.</summary>
    public Task ResetEfficiencyAsync(CancellationToken token = default)
    {
        Guid attempt;
        lock (gate)
        {
            if (retired || connection.Publication is not { Phase: AccountReceivePhase.Running, State.Player: not null } current)
                throw new ProtocolException("請先登入並取得角色資料。");
            attempt = current.Attempt;
        }
        return connection.ApplyCommandAsync(attempt, state => CommandState.With(state, efficiency: EfficiencyReducer.Apply(EfficiencySnapshot.Empty,
            EfficiencyKnowledgeProjector.Project(state.PlayerKnowledge, state.Companions, state.Player),
            new EfficiencyRefresh { ObservedAt = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency })), token);
    }
}
