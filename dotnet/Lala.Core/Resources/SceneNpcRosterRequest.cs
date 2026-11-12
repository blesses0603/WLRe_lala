using System.Collections.Immutable;
using System.Text;
using Lala.Core.Inventory;
using Lala.Core.World.Eve;
namespace Lala.Core.Resources;

/// <summary>Declared EventData.NewNpc reference, not a live entity or interaction permit.</summary>
public sealed record SceneNpcEntry(ushort NpcIndex,uint NpcId,string Name,uint X,uint Y,ImmutableArray<byte> EventIds)
{
    public ushort? LiveX {get;init;}
    public ushort? LiveY {get;init;}
    public ushort? TargetX {get;init;}
    public ushort? TargetY {get;init;}
    public bool? LiveVisible {get;init;}
    public int EventCount=>EventIds.Length;
    public string Source=>"EventData.NewNpc";
    public bool CanInteract=>false;
}
/// <summary>Revocable current-scene roster. Returned rows remain historical observations.</summary>
public sealed class SceneNpcRosterRequest
{
    private readonly ImmutableArray<SceneNpcEntry> rows;private readonly Func<bool> current;
    public ushort Scene {get;}
    public string Identity {get;}
    public bool IsCurrent=>current();
    public bool CanSendPackets=>false;
    internal SceneNpcRosterRequest(ushort scene,string identity,ImmutableArray<SceneNpcEntry> rows,Func<bool> current)
    {(Scene,Identity,this.rows,this.current)=(scene,identity,rows,current);}
    public bool TryReadRows(out ImmutableArray<SceneNpcEntry> result)
    {result=[];if(!IsCurrent)return false;var captured=rows;if(!IsCurrent)return false;result=captured;return true;}

    internal static ImmutableArray<SceneNpcEntry> Build(ImmutableArray<EveNpcRow> source,IReadOnlyDictionary<uint,CombatResourceNpc>? names)
    {
        if(source.IsDefault||source.Length>4096)throw new ResourceValidationException("Invalid scene NPC roster size");
        var indices=new HashSet<ushort>();var result=ImmutableArray.CreateBuilder<SceneNpcEntry>(source.Length);
        foreach(var row in source)
        {
            if(row.NpcId==0||!indices.Add(row.Index)||row.EventIds.IsDefault||row.EventIds.Length>255)
                throw new ResourceValidationException("Invalid scene NPC reference");
            string? name=names?.GetValueOrDefault(row.NpcId)?.Name;
            if(string.IsNullOrEmpty(name))name="NPC #"+row.NpcId.ToString(System.Globalization.CultureInfo.InvariantCulture);
            // Python display_name uses [:100] code points, not UTF-16 code units.
            var text=new StringBuilder();foreach(var rune in name.EnumerateRunes().Take(100))text.Append(rune.ToString());
            result.Add(new(row.Index,row.NpcId,text.ToString(),row.X,row.Y,row.EventIds));
        }
        return result.MoveToImmutable();
    }
}
