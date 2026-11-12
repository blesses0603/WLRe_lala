using System.Collections.Immutable;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

/// <summary>Compact display only. Receive receipts and command acknowledgement
/// evidence remain intact in the account runtime.</summary>
internal static class CharacterEventSummary
{
    internal static ImmutableArray<string> Lines(ImmutableArray<GameServerEvent> events)
    {
        var lines=ImmutableArray.CreateBuilder<string>();
        int permissions=0, effects=0;
        void Flush(bool ended=false)
        {
            if(permissions+effects==0)return;
            lines.Add($"[接收] 伺服器事件同步：{permissions} 次接續通知" +
                (effects>0?$"、{effects} 次事件更新":"") + (ended?"（已結束）":"（進行中）"));
            permissions=effects=0;
        }
        foreach(var e in events)
        {
            if(e.Type=="event_continue_permission") { permissions++; continue; }
            if(e.Type=="event_active") { effects++; continue; }
            if(e.Type=="event_end" && permissions+effects>0) { Flush(ended:true); continue; }
            Flush();
            lines.Add($"[接收 {e.Main}-{e.Sub}] {e.Description}");
        }
        Flush();
        return lines.ToImmutable();
    }
}
