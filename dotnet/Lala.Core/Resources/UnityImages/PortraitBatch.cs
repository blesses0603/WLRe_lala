using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed record PortraitLinkedRow(PortraitMaterialKey Key,string Asset,long MaterialId,PortraitMaterialCandidate Material,
    long TextureId,string TextureAsset,long? MaskId);
// Structural observations only; this layout does NOT verify source pins or Shader contents.
internal static class PortraitBatchLayout
{
    internal static readonly UnityFileIdentity MaterialFile=new("mainpackage_material.bundle","CAB-66a0cb5c73552f6e34c71e0339b38329");
    internal static readonly UnityFileIdentity TextureFile=new("mainpackage_texture_a.bundle","CAB-62cd938e63ebf8b532f3064be45777c9");
    internal static readonly UnityFileIdentity ShaderFile=new("mainpackage_unityshaders.bundle","CAB-f0d25a36a0de0a1720bc340c0640a4e1");
    internal const long ShaderId=-1215708881511709531;
    internal static readonly IReadOnlyList<UnityFileIdentity> ExpectedFiles=Array.AsReadOnly(new[]{MaterialFile,TextureFile,ShaderFile});
    private static readonly Regex TextureName=new(@"\AAvatar2D(?:NPC)?_[0-9]{4}(?:_[0-9]+)?\z",RegexOptions.CultureInvariant|RegexOptions.NonBacktracking);
    internal static UnityFileIdentity Target(BoundedSerializedFile owner,UnityContainerPointer pointer,IReadOnlyDictionary<UnityFileIdentity,BoundedSerializedFile> files)
    {
        Require(pointer.FileId>=0&&pointer.FileId<=owner.Externals.Count&&pointer.PathId!=0,"Invalid portrait pointer");
        if(pointer.FileId==0)return owner.Identity;
        string path=owner.Externals[pointer.FileId-1];
        // UnityPy FileIdentifier.name uses basename. Match ONLY the three reviewed CAB
        // identities already in memory; never search/open that basename on disk.
        string name=path[(path.LastIndexOf('/')+1)..];
        var matches=files.Keys.Where(id=>StringComparer.Ordinal.Equals(id.EntryName,name)).ToArray();
        Require(matches.Length==1,"Portrait external is missing or ambiguous in selected projection");return matches[0];
    }
    internal static IReadOnlyList<PortraitLinkedRow> Build(IReadOnlyDictionary<PortraitMaterialKey,string> wanted,
        IReadOnlyDictionary<UnityFileIdentity,BoundedSerializedFile> files,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        Require(files.Count==3&&ExpectedFiles.All(files.ContainsKey)&&wanted.Count==778,"Incomplete portrait projection");
        var materialFile=files[MaterialFile];var textureFile=files[TextureFile];var rows=new List<PortraitLinkedRow>(wanted.Count);
        var containers=files.Values.SelectMany(file=>file.Container.Select(e=>(file.Identity,e))).GroupBy(p=>p.e.Path,StringComparer.Ordinal)
            .ToDictionary(g=>g.Key,g=>g.ToArray(),StringComparer.Ordinal);
        foreach(var (key,path) in wanted.OrderBy(p=>p.Key.Kind,StringComparer.Ordinal).ThenBy(p=>p.Key.Icon,StringComparer.Ordinal))
        {
            token.ThrowIfCancellationRequested();
            Require(containers.TryGetValue(path,out var entries)&&entries.Length==1&&entries[0].Identity==MaterialFile,"Missing or ambiguous exact portrait material");
            var pointer=entries![0].e.Pointer;
            Require(pointer.FileId==0&&materialFile.Objects.TryGetValue(pointer.PathId,out var obj)&&obj.ClassId==21,"Portrait container must point to local Material");
            var material=UnityMaterialObjects.Project(UnityMaterialObjects.Read(materialFile.Objects[pointer.PathId].Bytes,token));
            Require(Target(materialFile,material.Shader,files)==ShaderFile&&material.Shader.PathId==ShaderId&&
                files[ShaderFile].Objects.TryGetValue(ShaderId,out var shader)&&shader.ClassId==48,"Portrait Shader pointer mismatch");
            Require(Target(materialFile,material.Texture,files)==TextureFile&&textureFile.Objects.TryGetValue(material.Texture.PathId,out var tex)&&tex.ClassId==28,
                "Portrait base texture pointer mismatch");
            var texture=UnityImageObjects.Texture(textureFile.Objects[material.Texture.PathId].Bytes,token);
            Require(TextureName.IsMatch(texture.Name),"Unreviewed portrait texture name");
            string directory=texture.Name.StartsWith("Avatar2DNPC_",StringComparison.Ordinal)?"Avatar2DNPC":"Avatar2D";
            string texturePath=$"Assets/ResourcesBuild/Texture/{directory}/{texture.Name}.png";
            Require(containers.TryGetValue(texturePath,out var declared)&&declared.Length==1&&declared[0].Identity==TextureFile&&
                declared[0].e.Pointer==new UnityContainerPointer(0,material.Texture.PathId),"Portrait texture exact container mismatch");
            long? mask=null;
            if(material.Mask.PathId==0)Require(material.Mask.FileId==0,"External null portrait mask");
            else
            {
                Require(Target(materialFile,material.Mask,files)==MaterialFile&&materialFile.Objects.TryGetValue(material.Mask.PathId,out var maskObject)&&maskObject.ClassId==28,
                    "Portrait mask pointer mismatch");mask=material.Mask.PathId;
            }
            rows.Add(new(key,path,pointer.PathId,material,material.Texture.PathId,texturePath,mask));
        }
        return rows.AsReadOnly();
    }
}
internal sealed class PortraitImageCandidate
{
    private readonly byte[] basis,mask;
    private readonly PortraitRenderSettings settings;
    internal PortraitMaterialKey Key { get; }
    internal string SourceFingerprint { get; }
    internal string Fingerprint { get; }
    internal bool UsesShaderDefaultMask { get; }
    internal bool HasVerifiedProvenance=>false; // No current publication/admission authority.
    internal byte[] CopyBase()=>basis.ToArray();
    internal byte[] CopyMask()=>mask.ToArray();
    internal byte[] Render(IReadOnlyDictionary<int,int> palettes,CancellationToken token=default)=>PortraitRenderer.Render(basis,mask,palettes,settings,token);
    internal PortraitImageCandidate(PortraitLinkedRow row,string sourceFingerprint,byte[] basePixels,byte[] maskPixels)
    {
        Require(basePixels.Length==256*256*4&&maskPixels.Length==basePixels.Length,"Portrait pixel geometry mismatch");
        Key=row.Key;SourceFingerprint=sourceFingerprint;UsesShaderDefaultMask=row.MaskId is null;basis=basePixels.ToArray();mask=maskPixels.ToArray();
        settings=new(PortraitRenderer.ColorProfile,"UI_ProfilePhotoWithMask",false,0,row.Material.MaskClip,0,
            row.Material.Colors.ToDictionary(p=>p.Key,p=>new[]{(double)p.Value.R,p.Value.G,p.Value.B},StringComparer.Ordinal));
        Fingerprint=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new {sourceFingerprint,row.Key,row.Asset,row.MaterialId,row.TextureId,row.TextureAsset,row.MaskId,
            row.Material.MaskClip,Colors=row.Material.Colors.OrderBy(p=>p.Key,StringComparer.Ordinal),Base=SpritePng.Hash(basis),Mask=SpritePng.Hash(mask),Profile=PortraitRenderer.ColorProfile,
            Shader=UnityShaderObjects.PortraitBlobSha256}));
    }
}
internal sealed record PortraitBatchReceipt(string SourceFingerprint,string Fingerprint,int Count);
internal static class PortraitBatch
{
    // Deliberately uninstalled: callers must stage writes and publish only after this
    // returns AND source/currentness/readback checks. A callback is not completion.
    internal static PortraitBatchReceipt Process(PortraitSourcePlan.VerifiedPortraitSources sources,Action<PortraitImageCandidate> consume,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(sources);ArgumentNullException.ThrowIfNull(consume);token.ThrowIfCancellationRequested();
        var files=new Dictionary<UnityFileIdentity,BoundedSerializedFile>();var budget=new UnityExtractionBudget();
        foreach(var expected in PortraitBatchLayout.ExpectedFiles)
        {
            token.ThrowIfCancellationRequested();var source=sources.Sources[expected.BundleName];
            using var stream=source.OpenRead();byte[] bytes=new byte[checked((int)source.Spec.Size)];
            for(int offset=0;offset<bytes.Length;)
            {token.ThrowIfCancellationRequested();int read=stream.Read(bytes,offset,Math.Min(65536,bytes.Length-offset));Require(read>0,"Truncated portrait source");offset+=read;}
            Require(stream.ReadByte()==-1,"Portrait source size changed");
            var entries=BoundedUnityBundle.Read(bytes,budget,token);
            Require(entries.Count==1&&entries[0].Name==expected.EntryName,"Unexpected portrait serialized file set");
            files.Add(expected,BoundedSerializedFile.Read(expected,entries[0].Bytes,budget,token,allowImages:true,
                allowMaterials:expected==PortraitBatchLayout.MaterialFile,allowShaders:expected==PortraitBatchLayout.ShaderFile));
        }
        var shaderFile=files[PortraitBatchLayout.ShaderFile];
        Require(shaderFile.Objects.TryGetValue(PortraitBatchLayout.ShaderId,out var shader)&&shader.ClassId==48&&shader.ShaderLayout is not null,"Missing reviewed portrait Shader");
        UnityShaderObjects.VerifyPortrait(shader!.Bytes,shader.ShaderLayout!,token);
        var rows=PortraitBatchLayout.Build(sources.Plan.Materials,files,token);
        using var digest=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);int count=0;
        foreach(var row in rows)
        {
            token.ThrowIfCancellationRequested();
            byte[] Decode(UnityFileIdentity file,long id,string asset)
            {
                var texture=UnityImageObjects.Texture(files[file].Objects[id].Bytes,token);
                Require(texture.Layout.Width==256&&texture.Layout.Height==256,"Unreviewed portrait texture dimensions");
                return BoundedTexturePixels.Decode(new(sources.Plan.Fingerprint,sources.Sources[file.BundleName].Sha256,file.EntryName,asset,id),texture,token).CopyPixels();
            }
            byte[] basis=Decode(PortraitBatchLayout.TextureFile,row.TextureId,row.TextureAsset),mask;
            if(row.MaskId is long maskId)mask=Decode(PortraitBatchLayout.MaterialFile,maskId,row.Asset);
            else {mask=new byte[256*256*4];Array.Fill(mask,(byte)255);} // Only after hard Shader verification above.
            var candidate=new PortraitImageCandidate(row,sources.Plan.Fingerprint,basis,mask);
            consume(candidate);token.ThrowIfCancellationRequested();
            digest.AppendData(Convert.FromHexString(candidate.Fingerprint));count++;
        }
        Require(count==778,"Portrait batch incomplete");token.ThrowIfCancellationRequested();
        return new(sources.Plan.Fingerprint,Convert.ToHexStringLower(digest.GetHashAndReset()),count);
    }
}
