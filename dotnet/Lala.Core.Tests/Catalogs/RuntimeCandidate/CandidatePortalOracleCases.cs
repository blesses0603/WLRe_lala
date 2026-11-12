// Generated actual Python observations for owned ten-table fixtures. No provenance claim.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;
public static class CandidatePortalOracleCases
{
    public const int Count = 14;
    public static IEnumerable<object[]> Cases()
    {
        yield return new object[] { "owned-existing-flow", 0 };
        yield return new object[] { "event-single", 1 };
        yield return new object[] { "event-multiple", 2 };
        yield return new object[] { "unknown-target", 3 };
        yield return new object[] { "missing-convey", 4 };
        yield return new object[] { "zero-ratio", 5 };
        yield return new object[] { "zero-map", 6 };
        yield return new object[] { "line-boundary", 7 };
        yield return new object[] { "anchor-sign", 8 };
        yield return new object[] { "uint-max-position", 9 };
        yield return new object[] { "orphan-source-scene", 10 };
        yield return new object[] { "unrelated-optional-inputs-ignored", 11 };
        yield return new object[] { "same-scene-conditional", 12 };
        yield return new object[] { "duplicate-target-conveys", 13 };
    }
    internal static JsonElement Read(int index) => Fixture.Value[index];
    private static readonly Lazy<JsonElement> Fixture = new(() =>
    {
        using var doc = JsonDocument.Parse(GzipJson.DecodeResource("Lala.Core.Tests.Catalogs.RuntimeCandidate.Fixtures.candidate-portals.json.gz", "804413075112cb8c232b93ccccb18fbe476868f9cfbfa3de38049e0296b32807", "befea66e3371500c3a9d3fdc1e7b2614445ace7979764d08da9e770b7f0a7599"));
        if (doc.RootElement.GetArrayLength() != Count) throw new InvalidDataException("Candidate portal fixture count mismatch");
        return doc.RootElement.Clone();
    });
}
