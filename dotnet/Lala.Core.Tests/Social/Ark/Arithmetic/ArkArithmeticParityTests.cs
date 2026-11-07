using System.Collections.Immutable;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Lala.Core.Social.Ark;
using Xunit;

namespace Lala.Core.Tests.Social.Ark.Arithmetic;

public sealed class ArkArithmeticParityTests
{
    public static IEnumerable<object[]> Cases() => Read()["cases"]!.AsArray().Select(row =>
        new object[] { row!["name"]!.GetValue<string>(), row.ToJsonString() });

    [Theory]
    [MemberData(nameof(Cases))]
    public void ExactMatchesAgreeWithRetainedPython(string name, string json)
    {
        var row = JsonNode.Parse(json)!;
        var source = row["question"]!;
        var question = new ArkQuestionSnapshot(919, new ArkAward(1, 2, 3),
            source["options"] is { } options ? [.. options.AsArray().Select(value => value!.GetValue<uint>())] : default,
            source["text"]?.GetValue<string>()!,
            source["labels"] is { } labels ? [.. labels.AsArray().Select(value => value?.GetValue<string>()!)] : default)
        {
            Selected = 3, KnownAnswer = 123, AnswerSource = "Unrelated caller observation",
            AnswerKind = "Not authority", CandidateReason = "Not used by solver", SelectedCandidate = true
        };
        var before = question with { };
        var result = ArkArithmeticSolver.Solve(question);
        Assert.True(result == row["expected"]?.GetValue<uint>(), $"Retained Python disagreement: {name}, actual {result}, input {json}");
        Assert.Equal(before, question);
    }

    [Fact]
    public void LabelBoundDeltasAreRecordedAgainstRealPython()
    {
        foreach (var row in Read()["explicit_deltas"]!.AsArray().Where(row => row!["label_length"] is not null))
        {
            Assert.Equal(11, row!["expected_python"]!.GetValue<int>());
            Assert.Null(row["expected_core"]);
            var length = row["label_length"]!.GetValue<int>();
            Assert.Null(ArkArithmeticSolver.Solve(ArkArithmeticContractTests.Question("3*4=？",
                [new string(' ', length - 2) + "12", "0", "-1", "9"])));
        }
    }

    [Fact]
    public void PythonUnboundedOptionIdsAreExplicitlyOutsideTypedDomain()
    {
        var row = Read()["explicit_deltas"]!.AsArray().Single(row => row!["option_id"] is not null)!;
        Assert.Equal(row["option_id"]!.GetValue<string>(), row["expected_python"]!.GetValue<string>());
        Assert.True(BigInteger.Parse(row["option_id"]!.GetValue<string>()) > uint.MaxValue);
        Assert.Equal("outside uint option-ID domain", row["typed_boundary"]!.GetValue<string>());
    }

    [Fact]
    public void OracleFingerprintsCoverRetainedSourceTestsAndGenerator()
    {
        var root = RepositoryRoot();
        foreach (var (path, hash) in Read()["source_sha256"]!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), Convert.ToHexStringLower(SHA256.HashData(
                NormalizeCrLf(File.ReadAllBytes(Path.Combine(root.FullName, path))))));
    }

    [Fact]
    public void FingerprintsOnlyNormalizeCrLfBytes()
    {
        Assert.Equal(new byte[] { 255, 10, 254, 13, 0, 10, 13 }, NormalizeCrLf([255, 13, 10, 254, 13, 0, 10, 13]));
    }

    [Fact]
    public void EveryIncrementFileStaysBelowPhysicalSizeLimitWithLfAndCrLf()
    {
        var root = RepositoryRoot().FullName;
        var files = Directory.GetFiles(Path.Combine(root, "dotnet/Lala.Core.Tests/Social/Ark/Arithmetic"))
            .Append(Path.Combine(root, "dotnet/Lala.Core/Social/Ark/ArkArithmeticSolver.cs"));
        foreach (var path in files)
        {
            var bytes = File.ReadAllBytes(path);
            var lf = NormalizeCrLf(bytes);
            Assert.True(bytes.Length <= 500_000, path);
            Assert.True(lf.Length + lf.Count(value => value == 10) <= 500_000, path);
        }
    }

    internal static JsonNode Read() => JsonNode.Parse(ArkArithmeticPythonVectors.Json)!;

    private static DirectoryInfo RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/services/ark_first_answer.py")))
            directory = directory.Parent;
        return directory ?? throw new InvalidOperationException("The retained Python checkout is required for source verification.");
    }

    private static byte[] NormalizeCrLf(byte[] bytes)
    {
        using var stream = new MemoryStream(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
        {
            if (bytes[i] == 13 && i + 1 < bytes.Length && bytes[i + 1] == 10) continue;
            stream.WriteByte(bytes[i]);
        }
        return stream.ToArray();
    }
}
