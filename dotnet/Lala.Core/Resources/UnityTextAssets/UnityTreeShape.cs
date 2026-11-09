using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

internal static class UnityTreeShape
{
    internal sealed record Node(string Type, string Name, int Size, int Depth, bool Array, bool Align);
    private sealed record Field(string Type, string Name, int Size = -1, bool Array = false, bool Align = false, params Field[] Children);
    private static Field Scalar(string type, string name, int size, bool align = false) => new(type, name, size, Align: align);
    private static Field S(string name) => new("string", name, Children: [new("Array", "Array", Array: true, Align: true,
        Children: [Scalar("int", "size", 4), Scalar("char", "data", 1)])]);
    private static Field P(string name) => new("PPtr<Object>", name, 12, Children: [Scalar("int", "m_FileID", 4), Scalar("SInt64", "m_PathID", 8)]);
    private static Field I(string name) => new("AssetInfo", name, 20, Children: [Scalar("int", "preloadIndex", 4), Scalar("int", "preloadSize", 4), P("asset")]);
    private static Field A(string type, string name, Field child, bool align = false) => new(type, name, Children: [new("Array", "Array", Array: true, Align: align,
        Children: [Scalar("int", "size", 4), child])]);
    private static readonly Node[] Text = Flatten(new("TextAsset", "Base", Children: [S("m_Name"), S("m_Script")]));
    private static readonly Node[] Bundle = Flatten(new("AssetBundle", "Base", Children:
    [
        S("m_Name"), A("vector", "m_PreloadTable", P("data"), true),
        A("map", "m_Container", new("pair", "data", Children: [S("first"), I("second")])), I("m_MainAsset"),
        Scalar("unsigned int", "m_RuntimeCompatibility", 4), S("m_AssetBundleName"), A("vector", "m_Dependencies", S("data"), true),
        Scalar("bool", "m_IsStreamedSceneAssetBundle", 1, true), Scalar("int", "m_ExplicitDataLayout", 4), Scalar("int", "m_PathFlags", 4),
        A("map", "m_SceneHashes", new("pair", "data", Children: [S("first"), S("second")]))
    ]));
    private static Node[] Flatten(Field root)
    {
        var result = new List<Node>();
        void Add(Field f, int depth) { result.Add(new(f.Type, f.Name, f.Size, depth, f.Array, f.Align)); foreach (var child in f.Children) Add(child, depth + 1); }
        Add(root, 0); return result.ToArray();
    }
    // Version and non-alignment metadata bits do not control these supported layouts.
    // Normalize only those inert bits; type/name/depth/size/array/alignment must all match.
    internal static void Validate(int classId, IReadOnlyList<Node> nodes)
    {
        if (classId is 21 or 28 or 213) { UnityImageShapes.Validate(classId, nodes); return; }
        var expected = classId == 49 ? Text : Bundle;
        Require(nodes.SequenceEqual(expected), "Unsupported embedded Unity type tree layout");
    }
}
