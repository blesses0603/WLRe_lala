using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Social.Ark;
using Xunit;

namespace Lala.Core.Tests.Social.Ark.Candidates;

public sealed class ArkCandidateContractTests
{
    private static ArkQuestionSnapshot Question() => new(63901, new(1, 2, 3),
        [63902, 63903, 63904, 63905], "離線測試題63901", ["測試甲", "測試乙", "測試丙", "測試丁"]);
    private static ArkCandidateVersionObservation Version() => new(ArkCandidateData.BuiltIn.DataVersion,
        [new("DataPackage", ArkCandidateData.BuiltIn.PackageVersion, ArkCandidateData.BuiltIn.ManifestSha256)]);

    [Fact]
    public void PublicResolverCannotReplaceOfficialContentWithSyntheticCandidateOrKnownAnswer()
    {
        var question = Question() with { KnownAnswer = 63902, AnswerSource = "server_confirmed", SelectedCandidate = true };
        var decision = ArkReviewedCandidates.Resolve(question, Version());
        Assert.Equal("changed", decision.Status);
        Assert.Null(decision.Answer);
        Assert.Equal("reviewed_import", decision.Source);
        Assert.Equal("ArkCandidateDecision (changed)", decision.ToString());
        Assert.Equal(63902u, question.KnownAnswer);
    }

    [Fact]
    public void CoverageAndVersionChecksPrecedeExactQuestionValidation()
    {
        var malformed = Question() with { Options = default, Labels = default, Text = null! };
        Assert.Equal("not_covered", ArkReviewedCandidates.Resolve(malformed with { Question = 123 }, null).Status);
        Assert.Equal("version_mismatch", ArkReviewedCandidates.Resolve(malformed, null).Status);
        Assert.Equal("version_mismatch", ArkReviewedCandidates.Resolve(malformed, new(Version().DataVersion, default)).Status);
        Assert.Throws<ArgumentException>(() => ArkReviewedCandidates.Resolve(malformed, Version()));
        Assert.Throws<ArgumentNullException>(() => ArkReviewedCandidates.Resolve(null!, Version()));
    }

    [Fact]
    public void DefaultCollectionsAndNullInternalRecordsNeverProducePartialIndex()
    {
        var valid = ArkCandidateData.BuiltIn;
        Assert.Throws<InvalidDataException>(() => new ArkCandidateIndex(valid with { Questions = default }));
        Assert.Throws<InvalidDataException>(() => new ArkCandidateIndex(valid with { UserReviewed = null! }));
        Assert.Throws<InvalidDataException>(() => new ArkCandidateIndex(valid with { Quarantined = null! }));
        Assert.Throws<InvalidDataException>(() => new ArkCandidateIndex(valid with { Questions = [null!] }));
        Assert.Throws<InvalidDataException>(() => new ArkCandidateIndex(valid with { Questions = [valid.Questions[0] with { Options = default }] }));
        Assert.Equal(200, ArkReviewedCandidates.Index.Count);
    }

    [Fact]
    public void IndexAndOptionCollectionsCannotMutateBuiltInEvidence()
    {
        var index = ArkReviewedCandidates.Index;
        var entry = index[63901];
        var replacement = index.SetItem(63901, entry with { Answer = 63903, Options = entry.Options.SetItem(0, 1) });
        Assert.Equal(63903u, replacement[63901].Answer);
        Assert.Equal(63902u, ArkReviewedCandidates.Index[63901].Answer);
        Assert.Equal(63902u, ArkReviewedCandidates.Index[63901].Options[0]);
        Assert.Equal(200, index.Count);
    }

    [Theory]
    [InlineData("ar-SA")]
    [InlineData("tr-TR")]
    [InlineData("zh-TW")]
    public void DigestsAndDecisionsUseOrdinalInvariantRules(string culture)
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture);
            Assert.Equal(ArkCandidateData.BuiltIn.IndexSha256, ArkCandidateIndex.ComputeDigest(ArkCandidateData.BuiltIn));
            Assert.Equal("changed", ArkReviewedCandidates.Resolve(Question(), Version()).Status);
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }

    [Fact]
    public void UnpairedSurrogatesAreNotSilentlyReplacedBeforeFingerprinting()
    {
        foreach (var character in new[] { '\ud800', '\udfff' })
            Assert.Throws<ArgumentException>(() => ArkReviewedCandidates.Resolve(
                Question() with { Text = new string(character, 1) }, Version()));
    }

    [Fact]
    public void VersionMatchingDoesNotRequireOrInventCatalogTokenRoleOrOtherPackages()
    {
        var data = ArkCandidateParityTests.Data(ArkCandidateParityTests.Read()["indices"]!["synthetic"]!);
        var result = new ArkCandidateIndex(data).Resolve(Question(), Version());
        Assert.Equal("candidate", result.Status);
        Assert.Equal(63902u, result.Answer);
        Assert.Equal("reviewed_import", result.Source);
        Assert.Contains("尚未經伺服器確認", result.Reason);
        Assert.DoesNotContain("confirmed", result.Status, StringComparison.Ordinal);
    }
}
