using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;

namespace Lala.Core.Resources;

internal sealed record PortraitSelection(PortraitMaterialKey Key, ImmutableDictionary<int, int> Palettes);
internal sealed class PortraitMapping
{
    internal const string DataPackageVersion = "1296_2026_11_04_13_34_19_13";
    // Reviewed Define.lua CHARACTER_DATAS, matching Python portrait_mapping.CHARACTERS.
    private static readonly ImmutableDictionary<(byte Sex, byte Head), int> Characters = new Dictionary<(byte,byte),int>
    {
        [(2,0)]=1,[(2,1)]=2,[(1,0)]=3,[(4,2)]=4,[(4,1)]=5,[(3,0)]=6,[(3,1)]=7,
        [(4,4)]=8,[(4,5)]=9,[(4,0)]=10,[(4,6)]=11,[(3,2)]=12,[(3,3)]=13,[(4,7)]=14,[(4,3)]=15
    }.ToImmutableDictionary();
    private readonly ImmutableDictionary<uint, PortraitSelection> npcs;
    private PortraitMapping(ImmutableDictionary<uint, PortraitSelection> npcs) => this.npcs = npcs;
    internal static PortraitMapping Create(ReadOnlySpan<byte> raw, string dataPackage, CancellationToken token = default)
    {
        BoundedSpritePixels.Check(dataPackage == DataPackageVersion, "Portrait NPC version is not reviewed");
        if (raw.Length > NormalAttackCatalogParser.MaxNpcBytes) throw new CatalogDecodeException("Portrait NPC payload exceeds bound");
        byte[] owned = raw.ToArray();
        NormalAttackCatalogParser.ParseNpcs(owned, token); // Fixed SHA and full structural validation.
        return Read(owned, token);
    }
    // Owned synthetic layouts only; never used by production acquisition.
    internal static PortraitMapping ParseLayoutForOfflineTests(ReadOnlySpan<byte> raw, CancellationToken token = default)
    {
        NormalAttackCatalogParser.ParseNpcsLayout(raw, token);
        return Read(raw, token);
    }
    private static PortraitMapping Read(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        var reader = new CatalogReader(raw, token); uint count = reader.UInt32();
        var rows = ImmutableDictionary.CreateBuilder<uint, PortraitSelection>();
        for (int i=0; i<count; i++)
        {
            reader.Utf16(true); reader.Utf16(true); var fields=reader.Take(NormalAttackCatalogParser.NpcFieldBytes);
            ushort id=BinaryPrimitives.ReadUInt16LittleEndian(fields[1..]);
            byte kind=fields[5]; ushort icon=BinaryPrimitives.ReadUInt16LittleEndian(fields[6..]);
            var palettes=ImmutableDictionary.CreateBuilder<int,int>();
            for (int group=1; group<=4; group++)
            {
                uint value=BinaryPrimitives.ReadUInt32LittleEndian(fields[(8+(group-1)*4)..]);
                BoundedSpritePixels.Check(value<=999999999, "Portrait NPC palette exceeds bound");
                palettes.Add(group,(int)value);
            }
            if (icon!=0) rows.Add(id,new(new("companion",kind==0 ? icon.ToString(CultureInfo.InvariantCulture) :
                icon.ToString("D4",CultureInfo.InvariantCulture)+"_"+kind.ToString(CultureInfo.InvariantCulture)),palettes.ToImmutable()));
        }
        BoundedSpritePixels.Check(reader.Remaining==0,"Portrait NPC trailing bytes");
        return new(rows.ToImmutable());
    }
    internal PortraitSelection? Select(WorldPlayer? player, CompanionReceiveSnapshot companions, bool companion)
    {
        if (player is null || player.RoleId==0) return null;
        if (!companion)
        {
            if (!Characters.TryGetValue((player.Sex,player.Head),out int id) || player.Palette1>999999999 || player.Palette5>999999999) return null;
            return new(new("player",id.ToString("D4",CultureInfo.InvariantCulture)),
                ImmutableDictionary<int,int>.Empty.Add(1,(int)player.Palette1).Add(5,(int)player.Palette5));
        }
        if (companions.ActiveNpcId is not { } active || active==0) return null;
        CompanionProfileSnapshot? selected=null;
        foreach (var profile in companions.Companions.Values)
        {
            if (profile.Data.NpcId!=active || !profile.Ready) continue;
            if (selected is not null) return null; selected=profile;
        }
        if (selected is null) return null;
        long modeling=selected.StatOverrides.GetValueOrDefault("modeling",selected.Data.Modeling);
        if (modeling is <0 or >65535) return null;
        return npcs.GetValueOrDefault(modeling==0 ? selected.Data.NpcId : (uint)modeling);
    }
}
