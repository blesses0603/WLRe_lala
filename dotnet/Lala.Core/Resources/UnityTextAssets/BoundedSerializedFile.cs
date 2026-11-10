using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

internal sealed record UnityFileIdentity(string BundleName, string EntryName);
internal sealed record UnityExternalBinding(UnityFileIdentity Source, string ExternalPath, UnityFileIdentity Target);
internal sealed record UnityObject(int ClassId, ReadOnlyMemory<byte> Bytes, UnityShaderLayout? ShaderLayout = null);
internal sealed record UnityContainerPointer(int FileId, long PathId);
internal sealed record UnityContainerEntry(string Path, UnityContainerPointer Pointer);

internal sealed class BoundedSerializedFile
{
    internal required UnityFileIdentity Identity { get; init; }
    internal required Dictionary<long, UnityObject> Objects { get; init; }
    internal required IReadOnlyList<string> Externals { get; init; }
    internal required List<UnityContainerEntry> Container { get; init; }
    internal static BoundedSerializedFile Read(UnityFileIdentity identity, ReadOnlyMemory<byte> bytes, UnityExtractionBudget budget, CancellationToken token, bool allowImages = false, bool allowMaterials = false, bool allowShaders = false, bool allowAtlases = false, UnityImageArchive? imageArchive = null)
        => ReadCore(identity,bytes,budget,token,allowImages,allowMaterials,allowShaders,allowAtlases,imageArchive,false);
    internal static BoundedSerializedFile ReadPortraitShaders(UnityFileIdentity identity, ReadOnlyMemory<byte> bytes,
        UnityExtractionBudget budget, CancellationToken token, UnityImageArchive archive)
    {
        Require(identity==PortraitBatchLayout.ShaderFile && archive.BundleName==identity.BundleName &&
            archive.SourceSha256=="4e756561fa3d8b77f439b0b3e969a01f573b451ac9d14ac662d8c8bedf443a47", "Unreviewed portrait shader archive");
        return ReadCore(identity,bytes,budget,token,true,false,true,false,archive,false,portraitShaders:true);
    }
    // Dedicated local atlas projection: all metadata is checked, but unrelated
    // object bodies never escape. General Read retains complete body validation.
    internal static BoundedSerializedFile ReadEmojiAtlasProjection(UnityFileIdentity identity,ReadOnlyMemory<byte> bytes,
        UnityExtractionBudget budget,CancellationToken token,UnityImageArchive? imageArchive=null)
        => ReadCore(identity,bytes,budget,token,true,false,false,true,imageArchive,true);
    internal static BoundedSerializedFile ReadSmallMapProjection(UnityFileIdentity identity,ReadOnlyMemory<byte> bytes,
        IReadOnlyCollection<string> paths,UnityExtractionBudget budget,CancellationToken token=default)
    {
        Require(paths.Count is >0 and <=2048&&paths.All(p=>p.StartsWith(SmallMapSourcePlan.Prefix,StringComparison.Ordinal))&&paths.Distinct(StringComparer.Ordinal).Count()==paths.Count,"Invalid small map projection paths");
        return ReadCore(identity,bytes,budget,token,true,false,false,false,null,false,paths.ToHashSet(StringComparer.Ordinal));
    }
    private static BoundedSerializedFile ReadCore(UnityFileIdentity identity,ReadOnlyMemory<byte> bytes,UnityExtractionBudget budget,
        CancellationToken token,bool allowImages,bool allowMaterials,bool allowShaders,bool allowAtlases,UnityImageArchive? imageArchive,bool emojiProjection,IReadOnlySet<string>? smallMapPaths=null,bool portraitShaders=false)
    {
        token.ThrowIfCancellationRequested(); var header = new UnityReadCursor(bytes, true);
        Require(header.U32() == 0 && header.U32() == 0 && header.U32() == 22 && header.U32() == 0 && header.U8() == 0,
            "Only little-endian SerializedFile22 supported");
        Require(header.Take(3).Span.IndexOfAnyExcept((byte)0) < 0, "Invalid SerializedFile reserved field");
        uint metadataSize = header.U32(); long fileSize = header.I64(), dataOffset = header.I64(), reserved = header.I64();
        Require(metadataSize is > 0 and <= 4 * 1024 * 1024 && fileSize == bytes.Length && reserved == 0 &&
            dataOffset >= 48L + metadataSize && dataOffset <= bytes.Length && dataOffset % 16 == 0,
            "Invalid SerializedFile header spans");
        budget.MetadataBytes += metadataSize; Require(budget.MetadataBytes <= 16 * 1024 * 1024, "Aggregate Unity metadata limit");
        var r = new UnityReadCursor(bytes.Slice(48, (int)metadataSize));
        Require(r.NullString(127) == "2021.3.45f2", "Unreviewed SerializedFile engine version");
        Require(r.U32() == 19 && r.U8() == 1, "Only standalone Windows64 embedded type trees supported");
        int types = r.Count(16, 31); Require(types > 0, "Missing Unity types"); var classes = new int[types]; var shaders = new UnityShaderLayout?[types];
        for (int i = 0; i < types; i++)
        {
            token.ThrowIfCancellationRequested(); int classId = r.I32(); classes[i] = classId;
            Require((classId is 49 or 142 || allowImages && classId is 28 or 213 || allowMaterials && classId == 21 || allowShaders && classId == 48 || portraitShaders && classId==200 || allowAtlases && classId == 687078895) && r.U8() == 0 && r.U16() == ushort.MaxValue, "Unsupported or stripped Unity class");
            r.Take(16); var shape = ReadTree(r, classId, token);
            if (classId == 48) shaders[i] = UnityShaderLayout.Create(shape);
            Require(r.Count(0) == 0, "Type dependencies unsupported");
        }
        int objectCount = r.Count(16_384, 24); budget.Objects += objectCount;
        Require(budget.Objects <= 16_384, "Aggregate Unity object limit");
        var objects = new Dictionary<long, UnityObject>(objectCount); var spans = new List<(long Start, long End)>(objectCount);
        for (int i = 0; i < objectCount; i++)
        {
            token.ThrowIfCancellationRequested(); r.Align(); long id = r.I64(), offset = r.I64(); uint size = r.U32(); int type = r.I32();
            Require(id != 0 && type >= 0 && type < classes.Length && offset >= 0 && offset % 4 == 0 && size is > 0 and <= 32 * 1024 * 1024 &&
                offset <= bytes.Length - dataOffset && size <= bytes.Length - dataOffset - offset, "Invalid Unity object span or type");
            Require(objects.TryAdd(id, new(classes[type], bytes.Slice((int)(dataOffset + offset), (int)size), shaders[type])), "Duplicate Unity object identity");
            spans.Add((offset, offset + size));
        }
        long end = 0;
        foreach (var span in spans.OrderBy(x => x.Start)) { Require(span.Start >= end, "Overlapping Unity object spans"); end = span.End; }
        Require(r.Count(0) == 0, "Script references unsupported");
        int externalCount = r.Count(128, 22); var external = new List<string>(externalCount); var paths = new HashSet<string>(StringComparer.Ordinal);
        for (int i = 0; i < externalCount; i++)
        {
            token.ThrowIfCancellationRequested(); Require(r.NullString(0, true) == "", "Unexpected external asset name"); r.Take(16);
            Require(r.U32() <= 3, "Unsupported external type"); string path = r.NullString(1024);
            Require(paths.Add(path), "Duplicate Unity external path"); external.Add(path);
        }
        Require(r.Count(0) == 0, "Managed reference types unsupported"); r.NullString(1024, true); r.End();
        var container = new List<UnityContainerEntry>();
        if (emojiProjection)
        {
            foreach(var obj in objects.Values.Where(o=>o.ClassId==142))
            { token.ThrowIfCancellationRequested(); ReadContainer(obj.Bytes,container,budget,token); }
            var roots=container.Where(e=>e.Path==EmojiSourcePlan.AtlasPath).ToArray();
            Require(roots.Length==1,"Emoji atlas container must be unique");
            var selected=new Dictionary<long,UnityObject>();
            UnityObject Select(UnityContainerPointer pointer,int classId)
            {
                token.ThrowIfCancellationRequested();
                Require(pointer.FileId==0&&pointer.PathId!=0,"Emoji projection requires local pointers");
                Require(objects.TryGetValue(pointer.PathId,out var obj)&&obj.ClassId==classId,"Missing or mismatched emoji object");
                selected.TryAdd(pointer.PathId,obj!);return obj!;
            }
            var atlas=UnityAtlasObjects.Read(Select(roots[0].Pointer,687078895).Bytes,token);
            foreach(var pointer in atlas.Sprites)
            {
                var sprite=UnityImageObjects.Sprite(Select(pointer,213).Bytes,token,true);
                Require(sprite.Atlas==roots[0].Pointer&&sprite.RenderKey is not null&&atlas.RenderData.ContainsKey(sprite.RenderKey.Value),"Invalid emoji sprite backlink or render key");
            }
            foreach(var entry in atlas.RenderData.Values)
            {
                Select(entry.Texture,28);
                if(entry.Alpha.PathId!=0)Select(entry.Alpha,28);
            }
            objects=selected;container=[roots[0]];
        }
        if(smallMapPaths is not null)
        {
            foreach(var obj in objects.Values.Where(o=>o.ClassId==142))ReadContainer(obj.Bytes,container,budget,token);
            var roots=container.Where(e=>smallMapPaths.Contains(e.Path)).ToList();
            Require(roots.Count==smallMapPaths.Count&&roots.Select(e=>e.Path).Distinct(StringComparer.Ordinal).Count()==roots.Count,"Small map container coverage mismatch");
            var selected=new Dictionary<long,UnityObject>();
            foreach(var root in roots)
            {
                token.ThrowIfCancellationRequested();Require(root.Pointer.FileId==0&&root.Pointer.PathId!=0&&objects.TryGetValue(root.Pointer.PathId,out var obj)&&obj.ClassId==28,"Small map requires exact local Texture2D pointer");
                selected.TryAdd(root.Pointer.PathId,objects[root.Pointer.PathId]);
            }
            objects=selected;container=roots;
        }
        foreach (var obj in objects.Values)
        {
            token.ThrowIfCancellationRequested();
            if (obj.ClassId == 142) ReadContainer(obj.Bytes, container, budget, token);
            else if (obj.ClassId == 48) UnityShaderObjects.Read(obj.Bytes, obj.ShaderLayout!, token);
            else if (obj.ClassId == 200)
                Require(portraitShaders && obj.Bytes.Length==17392 && SpritePng.Hash(obj.Bytes.Span)=="37c13cd939e43e27834152f87c9ec95d0fa2b7a90b4987a502983198a118bf1d", "Unreviewed portrait shader variants");
            else if (obj.ClassId == 687078895) UnityAtlasObjects.Read(obj.Bytes, token);
            else if (obj.ClassId == 21) UnityMaterialObjects.Read(obj.Bytes, token);
            else if (obj.ClassId == 28) { if(smallMapPaths is not null)UnityImageObjects.DescribeTexture(obj.Bytes,token);else UnityImageObjects.Texture(obj.Bytes, token, imageArchive, identity); }
            else if (obj.ClassId == 213) UnityImageObjects.Sprite(obj.Bytes, token, allowAtlases);
            else ValidateText(obj.Bytes, token); // Also validate unused objects; no unchecked layout escapes.
        }
        return new() { Identity = identity, Objects = objects, Externals = external.AsReadOnly(), Container = container };
    }
    private sealed record RawNode(byte Depth, byte Flags, uint Type, uint Name, int Size, uint Meta);
    private static IReadOnlyList<UnityTreeShape.Node> ReadTree(UnityReadCursor r, int classId, CancellationToken token)
    {
        int count = r.Count(classId == 48 ? 2304 : classId is 28 or 213 ? 256 : 128); int strings = r.Count(16 * 1024);
        Require(count > 0 && (long)count * 32 + strings <= r.Remaining, "Invalid type tree spans");
        var raw = new List<RawNode>(count);
        for (int i = 0; i < count; i++)
        {
            token.ThrowIfCancellationRequested(); ushort version = r.U16(); byte depth = r.U8(), flags = r.U8();
            uint type = r.U32(), name = r.U32(); int size = r.I32(); uint index = r.U32(), meta = r.U32(); long reference = r.I64();
            Require(version > 0 && depth <= (classId == 48 ? 22 : classId is 687078895 or 200 ? 10 : 8) && flags <= 1 && index == i && reference == 0, "Unsupported Unity tree node");
            raw.Add(new(depth, flags, type, name, size, meta));
        }
        var table = r.Take(strings); var nodes = new List<UnityTreeShape.Node>(count);
        foreach (var node in raw)
        {
            token.ThrowIfCancellationRequested(); nodes.Add(new(TableString(table, node.Type), TableString(table, node.Name), node.Size,
                node.Depth, node.Flags == 1, (node.Meta & 0x4000) != 0));
        }
        UnityTreeShape.Validate(classId, nodes); return nodes;
    }
    private static string TableString(ReadOnlyMemory<byte> local, uint offset)
    {
        ReadOnlyMemory<byte> table = (offset & 0x80000000) != 0 ? UnityCommonStrings.Bytes : local; offset &= 0x7fffffff;
        Require(offset < table.Length, "Invalid type tree string offset");
        return new UnityReadCursor(table.Slice((int)offset)).NullString(127);
    }
    internal static (string Name, ReadOnlyMemory<byte> Payload) ValidateText(ReadOnlyMemory<byte> bytes, CancellationToken token)
    {
        token.ThrowIfCancellationRequested(); var r = new UnityReadCursor(bytes); string name = r.String(1024, false);
        int length = r.Count(16 * 1024 * 1024, 1);
        var payload = r.Take(length); r.Align(); r.End(); token.ThrowIfCancellationRequested(); return (name, payload);
    }
    private static UnityContainerPointer Pointer(UnityReadCursor r) => new(r.I32(), r.I64());
    private static UnityContainerPointer Info(UnityReadCursor r, int preloadCount)
    {
        int start = r.I32(), size = r.I32(); Require(start >= 0 && size >= 0 && start <= preloadCount && size <= preloadCount - start, "Invalid AssetInfo preload span");
        return Pointer(r);
    }
    private static string ContainerPath(UnityReadCursor r, UnityExtractionBudget budget)
    {
        int length = r.Count(1024, 1); Require(length > 0, "Empty AssetPath");
        budget.ContainerIdentityBytes += length;
        Require(budget.ContainerIdentityBytes <= 8 * 1024 * 1024, "Aggregate container identity byte limit");
        string path = Decode(r.Take(length).Span); Require(!path.Contains('\0'), "NUL in AssetPath"); r.Align(); return path;
    }
    private static void ReadContainer(ReadOnlyMemory<byte> bytes, List<UnityContainerEntry> entries, UnityExtractionBudget budget, CancellationToken token)
    {
        var r = new UnityReadCursor(bytes); r.String(); int preloads = r.Count(100_000, 12); r.Take(preloads * 12);
        int count = r.Count(100_000, 24); budget.ContainerEntries += count;
        Require(budget.ContainerEntries <= 100_000, "Aggregate AssetBundle container limit");
        for (int i = 0; i < count; i++)
        { token.ThrowIfCancellationRequested(); string path = ContainerPath(r, budget); entries.Add(new(path, Info(r, preloads))); }
        Info(r, preloads); r.U32(); r.String(); int deps = r.Count(128, 4);
        for (int i = 0; i < deps; i++) { token.ThrowIfCancellationRequested(); r.String(); }
        Require(r.U8() <= 1, "Invalid AssetBundle boolean"); r.Align(); r.I32(); r.I32(); int hashes = r.Count(1024, 8);
        for (int i = 0; i < hashes; i++) { token.ThrowIfCancellationRequested(); r.String(); r.String(); }
        r.End();
    }
}
