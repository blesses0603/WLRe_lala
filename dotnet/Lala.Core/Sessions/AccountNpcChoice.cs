using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private sealed class NpcContinuationRevoked : Exception;
    private async Task ContinueNpcChoiceAsync(Guid attempt, GameAction action, ServiceStateSnapshot basis, OfflineRuntimeCandidate catalogs, CancellationToken token)
    {
        bool needed = false;
        bool Matches(ServiceStateSnapshot state)
        {
            var dialogue = state.Local.Session.NpcDialogue;
            return state.Player?.RoleId == basis.Player!.RoleId && state.Player.Scene == action.Scene && state.Local.Battle.Active != true && dialogue.Active &&
                dialogue.Scene == action.Scene && dialogue.OptionIndex == action.Count && dialogue.SelectedChoice == action.Index &&
                dialogue.EffectPacket == basis.Local.Session.NpcDialogue.EffectPacket;
        }
        await connection.ApplyCommandAsync(attempt, state =>
        {
            var dialogue = state.Local.Session.NpcDialogue;
            if (!Matches(state) || !dialogue.ChoiceContinuationPending || dialogue.Phase is not ("awaiting_choice" or "continue")) return state;
            needed = true;
            return CommandState.With(state, local: new(state.Local.Session with { NpcDialogue = dialogue with { ChoiceContinuationPending = false, Phase = "awaiting_reply" } }, state.Local.World, state.Local.Battle));
        }, token).ConfigureAwait(false);
        if (!needed) return;
        try
        {
            await connection.SendGameAsync(attempt, () =>
            {
                var current = connection.ReadPublication().Publication;
                lock (gate)
                {
                    if (!CurrentCatalogsLocked(out var c) || !ReferenceEquals(c, catalogs) || current is not { Phase: AccountReceivePhase.Running } || current.Attempt != attempt)
                        throw new ProtocolException("NPC 接續前連線或資源已失效。");
                    if (!Matches(current.State) || current.State.Local.Session.NpcDialogue.Phase != "awaiting_reply") throw new NpcContinuationRevoked();
                }
                return new Packet(20, 6, [0]);
            }, token).ConfigureAwait(false);
        }
        catch (NpcContinuationRevoked) { /* A newer server effect consumed the grant; never skip that new prompt. */ }
    }
}
