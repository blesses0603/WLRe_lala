using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Lala.Core.Social.Ark;
using Xunit;

namespace Lala.Core.Tests.Social.Ark.Candidates;

public sealed class ArkCandidateParityTests
{
    private static readonly Lazy<JsonNode> Fixture = new(() => JsonNode.Parse(ArkCandidatePythonVectors.Json)!);
    private static readonly Lazy<Dictionary<string, JsonNode>> ResolveRows = new(() =>
        Read()["cases"]!.AsArray().ToDictionary(row => row!["name"]!.GetValue<string>(), row => row!));
    private static readonly Lazy<Dictionary<string, JsonNode>> IndexRows = new(() =>
        Read()["index_cases"]!.AsArray().ToDictionary(row => row!["name"]!.GetValue<string>(), row => row!));
    private static readonly Lazy<Dictionary<string, ArkCandidateIndex>> Indices = new(() =>
        Read()["indices"]!.AsObject().ToDictionary(pair => pair.Key, pair => new ArkCandidateIndex(Data(pair.Value!))));

    public static IEnumerable<object[]> ResolutionCases() => ResolveRows.Value.Keys.Select(name => new object[] { name });
    public static IEnumerable<object[]> IndexCases() => IndexRows.Value.Keys.Select(name => new object[] { name });

    [Theory]
    [MemberData(nameof(ResolutionCases))]
    public void ResolutionMatchesRetainedPython(string name)
    {
        var row = ResolveRows.Value[name];
        var index = Indices.Value[row["index"]!.GetValue<string>()];
        var question = Question(row["question"]!);
        var before = question with { };
        var version = Version(row["identity"]);
        if (row["error"] is not null)
            Assert.ThrowsAny<ArgumentException>(() => index.Resolve(question, version));
        else
        {
            var expected = row["expected"]!;
            var actual = index.Resolve(question, version);
            Assert.Equal(expected["answer"]?.GetValue<uint>(), actual.Answer);
            Assert.Equal(expected["status"]!.GetValue<string>(), actual.Status);
            Assert.Equal(expected["reason"]!.GetValue<string>(), actual.Reason);
            Assert.Equal(expected["source"]!.GetValue<string>(), actual.Source);
            Assert.Equal(expected["revision"]!.GetValue<string>(), actual.Revision);
            Assert.NotEqual("server_confirmed", actual.Source);
            Assert.NotEqual("confirmed", actual.Status);
        }
        Assert.Equal(before, question);
    }

    [Theory]
    [MemberData(nameof(IndexCases))]
    public void WholeIndexValidationMatchesRetainedPython(string name)
    {
        var row = IndexRows.Value[name];
        var data = Data(row["data"]!);
        if (row["error"] is { } error)
            Assert.Equal(error.GetValue<string>(), Assert.Throws<InvalidDataException>(() => new ArkCandidateIndex(data)).Message);
        else
        {
            var index = new ArkCandidateIndex(data);
            Assert.Equal(row["expected_count"]!.GetValue<int>(), index.Entries.Count);
            Assert.Equal(data.IndexSha256, ArkCandidateIndex.ComputeDigest(data));
        }
    }

    [Fact]
    public void BuiltInDataExactlyRetainsAllReviewedIdsDigestsAndSourceDecisions()
    {
        var expected = Data(Read()["indices"]!["reviewed"]!);
        var actual = ArkCandidateData.BuiltIn;
        Assert.Equal(expected.DataVersion, actual.DataVersion);
        Assert.Equal(expected.PackageVersion, actual.PackageVersion);
        Assert.Equal(expected.ManifestSha256, actual.ManifestSha256);
        Assert.Equal(expected.TextSha256, actual.TextSha256);
        Assert.Equal(expected.SourceSha256, actual.SourceSha256);
        Assert.Equal(expected.ReviewRevision, actual.ReviewRevision);
        Assert.Equal(expected.IndexSha256, actual.IndexSha256);
        Assert.Equal(expected.IndexSha256, ArkCandidateIndex.ComputeDigest(actual));
        Assert.Equal(200, ArkReviewedCandidates.Index.Count);
        Assert.Empty(actual.Quarantined);
        Assert.Equal(16, actual.UserReviewed.Count);
        Assert.Equal(expected.UserReviewed.OrderBy(p => p.Key), actual.UserReviewed.OrderBy(p => p.Key));
        for (var i = 0; i < expected.Questions.Length; i++)
        {
            Assert.Equal(expected.Questions[i].Question, actual.Questions[i].Question);
            Assert.Equal(expected.Questions[i].Answer, actual.Questions[i].Answer);
            Assert.Equal(expected.Questions[i].Options.ToArray(), actual.Questions[i].Options.ToArray());
            Assert.Equal(expected.Questions[i].Fingerprint, actual.Questions[i].Fingerprint);
        }
    }

    [Fact]
    public void FixturesExecuteEveryReviewedIdInAllTwentyFourOptionOrders()
    {
        Assert.Equal(4865, ResolveRows.Value.Count);
        Assert.Equal(42, IndexRows.Value.Count);
        foreach (var id in ArkReviewedCandidates.Index.Keys)
            Assert.Equal(24, ResolveRows.Value.Keys.Count(name => name.StartsWith(id + "-", StringComparison.Ordinal)));
    }

    [Fact]
    public void SourceFingerprintsIncludeRetainedPythonDataTestsAndGenerator()
    {
        foreach (var (path, expected) in Read()["source_sha256"]!.AsObject())
            Assert.Equal(expected!.GetValue<string>(), Convert.ToHexStringLower(SHA256.HashData(
                NormalizeCrLf(File.ReadAllBytes(Path.Combine(RepositoryRoot().FullName, path))))));
    }

    [Fact]
    public void SourceNormalizationOnlyRemovesCrImmediatelyBeforeLf() =>
        Assert.Equal(new byte[] { 255, 10, 254, 13, 0, 10, 13 }, NormalizeCrLf([255, 13, 10, 254, 13, 0, 10, 13]));

    [Fact]
    public void IncrementFilesRemainBelowPhysicalSizeLimitWithLfOrCrLf()
    {
        var root = RepositoryRoot().FullName;
        var files = Directory.GetFiles(Path.Combine(root, "dotnet/Lala.Core.Tests/Social/Ark/Candidates"), "*", SearchOption.AllDirectories)
            .Where(path => !path.Contains("__pycache__", StringComparison.Ordinal))
            .Concat(new[] { "ArkReviewedCandidates.cs", "ArkCandidateData.cs" }.Select(name => Path.Combine(root, "dotnet/Lala.Core/Social/Ark", name)));
        foreach (var path in files)
        {
            var bytes = File.ReadAllBytes(path);
            Assert.True(bytes.Length < 500_000, path);
            if (path.EndsWith(".gz", StringComparison.Ordinal)) continue;
            var normalized = NormalizeCrLf(bytes);
            Assert.True(normalized.Length + normalized.Count(value => value == 10) < 500_000, path);
        }
    }

    internal static JsonNode Read() => Fixture.Value;
    internal static ArkCandidateData Data(JsonNode value) => new(
        value["DATA_VER"]!.GetValue<string>(), value["PACKAGE_VERSION"]!.GetValue<string>(),
        value["MANIFEST_SHA256"]!.GetValue<string>(), value["TEXT_SHA256"]!.GetValue<string>(),
        value["SOURCE_SHA256"]!.GetValue<string>(), value["REVIEW_REVISION"]!.GetValue<string>(), value["INDEX_SHA256"]!.GetValue<string>(),
        [.. value["QUESTIONS"]!.AsArray().Select(row => new ArkReviewedCandidate(row![0]!.GetValue<uint>(), row[1]!.GetValue<uint>(),
            [.. row[2]!.AsArray().Select(id => id!.GetValue<uint>())], row[3]!.GetValue<string>()))],
        Annotations(value["QUARANTINED"]!), Annotations(value["USER_REVIEWED"]!));
    private static ImmutableDictionary<uint, string> Annotations(JsonNode value) => value.AsObject()
        .ToImmutableDictionary(pair => uint.Parse(pair.Key, System.Globalization.CultureInfo.InvariantCulture), pair => pair.Value?.GetValue<string>()!);
    internal static ArkQuestionSnapshot Question(JsonNode value) => new(value["question"]!.GetValue<uint>(), new(1, 2, 3),
        value["options"] is { } options ? [.. options.AsArray().Select(id => id!.GetValue<uint>())] : default,
        value["text"]?.GetValue<string>()!,
        value["labels"] is { } labels ? [.. labels.AsArray().Select(label => label?.GetValue<string>()!)] : default)
    {
        KnownAnswer = value["known_answer"]?.GetValue<uint>(), AnswerSource = value["answer_source"]?.GetValue<string>(),
        Selected = value["selected"]?.GetValue<byte>(), SelectedCandidate = value["selected_candidate"]?.GetValue<bool>()
    };
    internal static ArkCandidateVersionObservation? Version(JsonNode? value) => value is null ? null : new(
        value["data_ver"]?.GetValue<string>(), value["packages"] is { } packages ? [.. packages.AsArray().Select(package =>
            package is null ? null! : new ArkCandidatePackageObservation(package["name"]?.GetValue<string>(),
                package["full_version"]?.GetValue<string>(), package["manifest_sha256"]?.GetValue<string>()))] : default);
    private static DirectoryInfo RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/services/ark_candidates.py"))) directory = directory.Parent;
        return directory ?? throw new InvalidOperationException("Retained Python checkout is required for source verification.");
    }
    private static byte[] NormalizeCrLf(byte[] bytes)
    {
        using var result = new MemoryStream(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
        {
            if (bytes[i] == 13 && i + 1 < bytes.Length && bytes[i + 1] == 10) continue;
            result.WriteByte(bytes[i]);
        }
        return result.ToArray();
    }
}
