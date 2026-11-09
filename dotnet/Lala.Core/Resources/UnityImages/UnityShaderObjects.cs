using System.Security.Cryptography;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

// A compiled layout is constructible only from the exact reviewed Shader type tree.
// It never interprets a caller-defined shape or executes/decompresses shader programs.
internal sealed class UnityShaderLayout
{
    internal sealed record Field(UnityTreeShape.Node Node, string Path, IReadOnlyList<int> Children);
    private readonly Field[] fields;
    private UnityShaderLayout(Field[] fields) { this.fields = fields; }
    internal Field At(int index) => fields[index];
    internal static UnityShaderLayout Create(IReadOnlyList<UnityTreeShape.Node> nodes)
    {
        var owned = nodes.ToArray(); UnityImageShapes.Validate(48, owned);
        var children = owned.Select(_ => new List<int>()).ToArray(); var paths = new string[owned.Length];
        var stack = new Stack<int>();
        for (int i = 0; i < owned.Length; i++)
        {
            while (stack.Count > owned[i].Depth) stack.Pop();
            Require(stack.Count == owned[i].Depth, "Invalid Shader tree hierarchy");
            if (stack.Count > 0) { int parent = stack.Peek(); children[parent].Add(i); paths[i] = paths[parent] + "/" + owned[i].Name; }
            else paths[i] = owned[i].Name;
            stack.Push(i);
        }
        return new(owned.Select((n,i) => new Field(n,paths[i],Array.AsReadOnly(children[i].ToArray()))).ToArray());
    }
}
internal sealed record UnityShaderObservation(string Name, string MaskDefault, string BlobSha256);
internal static class UnityShaderObjects
{
    internal const string PortraitBlobSha256 = "95efa07a84d2cda0758e7d30893efec5c94899807cb3ec20bb8263b7a293d814";
    private const string Properties = "Base/m_ParsedForm/m_PropInfo/m_Props/Array/data";
    private sealed class Property { internal string? Name, Default; }
    internal static UnityShaderObservation Read(ReadOnlyMemory<byte> bytes, UnityShaderLayout layout, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested(); Require(bytes.Length <= 8 * 1024 * 1024, "Shader object byte limit");
        var r = new UnityReadCursor(bytes); int visits = 0; string? name = null, hash = null;
        var properties = new Dictionary<string,string>(StringComparer.Ordinal);
        void Walk(int index, Property? property = null)
        {
            token.ThrowIfCancellationRequested(); Require(++visits <= 2_000_000, "Shader traversal work limit");
            var f = layout.At(index); var n = f.Node;
            bool ownsProperty = f.Path == Properties;
            if (ownsProperty) property = new();
            if (n.Type == "string")
            {
                string value = r.String(4096);
                if (f.Path == "Base/m_ParsedForm/m_Name") name = value;
                if (f.Path == Properties + "/m_Name") property!.Name = value;
                if (f.Path == Properties + "/m_DefTexture/m_DefaultName") property!.Default = value;
            }
            else if (n.Array)
            {
                Require(f.Children.Count == 2, "Invalid Shader array shape");
                int count = r.Count(f.Path == "Base/compressedBlob/Array" ? 8 * 1024 * 1024 : 16384);
                if (f.Path == "Base/compressedBlob/Array")
                    hash = Convert.ToHexStringLower(SHA256.HashData(r.Take(count).Span));
                else for (int i = 0; i < count; i++) Walk(f.Children[1], property);
            }
            else if (f.Children.Count != 0)
                foreach (int child in f.Children) Walk(child, property);
            else switch (n.Type)
            {
                case "bool": Require(r.U8() <= 1, "Invalid Shader boolean"); break;
                case "float": Require(float.IsFinite(BitConverter.Int32BitsToSingle(r.I32())), "Nonfinite Shader field"); break;
                case "int": case "unsigned int": r.I32(); break;
                case "SInt64": r.I64(); break;
                case "UInt16": r.U16(); break;
                case "SInt8": case "UInt8": case "char": r.U8(); break;
                default: throw new UnityTextAssetException("Unsupported Shader scalar");
            }
            if (n.Align) r.Align();
            if (ownsProperty)
                Require(property!.Name is { Length: > 0 } && property.Default is not null && properties.TryAdd(property.Name, property.Default), "Invalid or duplicate Shader property");
        }
        Walk(0); r.End(); token.ThrowIfCancellationRequested();
        Require(name is not null && hash is not null, "Missing Shader projection fields");
        return new(name!, properties.GetValueOrDefault("_ColorMask1", ""), hash!);
    }
    // Reparse the bytes; callers cannot substitute an observation's hash or default value.
    internal static void VerifyPortrait(ReadOnlyMemory<byte> bytes, UnityShaderLayout layout, CancellationToken token = default)
    {
        var observed = Read(bytes, layout, token);
        Require(observed.Name == "UI_ProfilePhotoWithMask" && observed.MaskDefault == "white" && observed.BlobSha256 == PortraitBlobSha256,
            "Portrait Shader name, blob or default mask is not reviewed");
    }
}
