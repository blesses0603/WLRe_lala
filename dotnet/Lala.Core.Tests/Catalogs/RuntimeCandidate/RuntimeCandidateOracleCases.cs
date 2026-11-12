// Generated from exact retained Python runtime AST blocks. Synthetic inputs only.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;
public static class RuntimeCandidateOracleCases
{
    public const int Count = 157;
    public static IEnumerable<object[]> CaseIds() { for (int i = 0; i < Count; i++) yield return new object[] { i }; }
    public static IEnumerable<object[]> SourceRefs()
    {
        yield return new object[] { "wlre/services/world/bundle_runtime_1275.py", "ab44be1c49d6d6f0c51e5bcde1479ca600d44e4ec343fdeecf2c80377c61564e" };
        yield return new object[] { "wlre/services/world/dynamic_bundle_runtime.py", "152bb58fb652deb32dd3193a4eb44e1a194305c50341b624e052dd5c3cb4a7a1" };
        yield return new object[] { "wlre/services/world/scene_names_1275.py", "5f7e2518cb2d6f14abae38c1fca6da32414d9237ff072fabe4678433b15d872c" };
        yield return new object[] { "wlre/services/world/itemdata_v1.py", "8ee7e6964e53c3f188ddf9ab761d14e58a238fb01397e4b82369779ca1b549d2" };
    }
    private static readonly Lazy<JsonElement> Data = new(() => JsonDocument.Parse(GzipJson.DecodeResource(
        "Lala.Core.Tests.Catalogs.RuntimeCandidate.Fixtures.runtime-candidate.json.gz",
        "d9e7d7c81118b6643ed8dfc49335188fc92b140d5dc70152d60b7afd9ad02348", "b349977f30cf377c92555116c1eab763ce1e8c3806bb53ba687eda7300f0202e" )).RootElement);
    internal static JsonElement Case(int id) => Data.Value[id];
}
