using System.Collections.Frozen;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed record UnityResolvedObject(UnityFileIdentity File, long PathId, UnityObject Object);
// Resolves only a supplied, already parsed projection. No file access, basename search,
// dependency loading or assertion of official provenance/current publication.
internal sealed class UnitySelectedObjects
{
    private sealed record File(IReadOnlyList<string> Externals, FrozenDictionary<long,UnityObject> Objects);
    private readonly FrozenDictionary<UnityFileIdentity,File> files;
    private readonly FrozenDictionary<(UnityFileIdentity,string),UnityFileIdentity> bindings;
    internal UnitySelectedObjects(IReadOnlyList<BoundedSerializedFile> selected, IReadOnlyList<UnityExternalBinding> externalBindings, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        Require(selected.Count is > 0 and <= 4 && externalBindings.Count <= 128, "Selected pointer scope exceeds bound");
        var captured = new Dictionary<UnityFileIdentity,File>(); long bytes = 0; int objects = 0;
        foreach (var file in selected)
        {
            token.ThrowIfCancellationRequested();
            Require(file.Externals.Count <= 128, "Selected external table exceeds bound");
            var owned = new Dictionary<long,UnityObject>();
            foreach (var (id,obj) in file.Objects)
            {
                token.ThrowIfCancellationRequested();
                bytes += obj.Bytes.Length; Require(++objects <= 16384 && bytes <= 32 * 1024 * 1024, "Selected object snapshot exceeds bound");
                // Snapshot bytes as well as indexes; later caller edits cannot retarget a captured PPtr.
                Require(id != 0, "Null selected object identity"); owned.Add(id,obj with { Bytes = obj.Bytes.ToArray() });
            }
            Require(captured.TryAdd(file.Identity,new(Array.AsReadOnly(file.Externals.ToArray()),owned.ToFrozenDictionary())), "Duplicate selected file identity");
        }
        var map = new Dictionary<(UnityFileIdentity,string),UnityFileIdentity>();
        foreach (var binding in externalBindings)
            Require(captured.TryGetValue(binding.Source,out var owner) && captured.ContainsKey(binding.Target) &&
                owner.Externals.Contains(binding.ExternalPath,StringComparer.Ordinal) && map.TryAdd((binding.Source,binding.ExternalPath),binding.Target),
                "Missing or ambiguous selected external binding");
        files = captured.ToFrozenDictionary(); bindings = map.ToFrozenDictionary();
    }
    internal UnityResolvedObject? Resolve(UnityFileIdentity owner, UnityContainerPointer pointer, int expectedClass, bool allowNull = false)
    {
        Require(files.TryGetValue(owner,out var file), "Pointer owner is outside selected scope");
        Require(pointer.FileId >= 0 && pointer.FileId <= file!.Externals.Count, "External pointer index out of bounds");
        if (pointer.PathId == 0)
        { Require(allowNull && pointer.FileId == 0, "Missing required pointer"); return null; }
        var target = owner;
        if (pointer.FileId != 0)
        {
            Require(bindings.TryGetValue((owner,file!.Externals[pointer.FileId-1]),out target), "External pointer is not explicitly bound");
            file = files[target!];
        }
        Require(file!.Objects.TryGetValue(pointer.PathId,out var obj) && obj.ClassId == expectedClass, "Missing pointer object or wrong class");
        return new(target!,pointer.PathId,obj!);
    }
}
