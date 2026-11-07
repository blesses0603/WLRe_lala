using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Social.Ark;
using Xunit;

namespace Lala.Core.Tests.Social.Ark.Arithmetic;

public sealed class ArkArithmeticContractTests
{
    internal static ArkQuestionSnapshot Question(string text = "3*4=？", ImmutableArray<string> labels = default) =>
        new(1, new ArkAward(0, 0, 0), [11, 12, 13, 14], text, labels.IsDefault ? ["12", "0", "-1", "9"] : labels);

    [Fact]
    public void MissingAndDefaultInputsFailClosed()
    {
        Assert.Null(ArkArithmeticSolver.Solve(null));
        Assert.Null(ArkArithmeticSolver.Solve(Question() with { Text = null! }));
        Assert.Null(ArkArithmeticSolver.Solve(Question() with { Options = default }));
        Assert.Null(ArkArithmeticSolver.Solve(Question() with { Labels = default }));
        Assert.Null(ArkArithmeticSolver.Solve(Question() with { Labels = ["12", null!, "0", "9"] }));
    }

    [Fact]
    public void EveryPythonWhitespaceCharacterIsTrimmedOnlyAtLabelEdges()
    {
        var values = ArkArithmeticParityTests.Read()["python_whitespace"]!.AsArray();
        Assert.Equal(29, values.Count);
        foreach (var value in values)
        {
            var c = char.ConvertFromUtf32(value!.GetValue<int>());
            Assert.Equal(11u, ArkArithmeticSolver.Solve(Question(labels: [c + "12" + c, "0", "-1", "9"])));
            Assert.Null(ArkArithmeticSolver.Solve(Question(labels: ["1" + c + "2", "0", "-1", "9"])));
            Assert.Null(ArkArithmeticSolver.Solve(Question(c + "3*4=？")));
            Assert.Null(ArkArithmeticSolver.Solve(Question("3*4=？" + c)));
        }
    }

    [Theory]
    [InlineData("3*4=？\n")]
    [InlineData("3*4=？\r\n")]
    [InlineData("3*4=？\u2028")]
    [InlineData("3*4=？\0")]
    [InlineData("3*4=？more")]
    public void FullmatchNeverUsesDollarAnchorSemantics(string text) => Assert.Null(ArkArithmeticSolver.Solve(Question(text)));

    [Theory]
    [InlineData("999999999*999999998再除以999999999=？", "999999998")]
    [InlineData("999999999*10000=？", "9999999990000")]
    [InlineData("36除以3再除以2=？", "6")]
    [InlineData("0除以999999999再除以999999999=？", "0")]
    [InlineData("3-8=？", "-5")]
    public void ArithmeticIsExactWithBoundedLargeIntermediates(string text, string answer) =>
        Assert.Equal(11u, ArkArithmeticSolver.Solve(Question(text, [answer, "-10", "-11", "-12"])));

    [Theory]
    [InlineData("1除以3=？")]
    [InlineData("3除以2再除以2=？")]
    [InlineData("999999999除以999999998=？")]
    [InlineData("999999999*999999999再除以999999998=？")]
    public void FractionalResultsNeverTruncateOrRound(string text) =>
        Assert.Null(ArkArithmeticSolver.Solve(Question(text, ["0", "1", "999999999", "1000000000"])));

    [Theory]
    [InlineData("1除以0=？")]
    [InlineData("0除以0=？")]
    [InlineData("1乘以0再除以0=？")]
    [InlineData("0乘以1再除以0=？")]
    public void ZeroDivisorsNeverProduceAnAnswer(string text) => Assert.Null(ArkArithmeticSolver.Solve(Question(text)));

    [Fact]
    public void MaximumTermCountIsSixteen()
    {
        var sixteen = string.Join("+", Enumerable.Repeat("999999999", 16));
        Assert.Equal(11u, ArkArithmeticSolver.Solve(Question(sixteen + "=？", ["15999999984", "0", "-1", "9"])));
        Assert.Null(ArkArithmeticSolver.Solve(Question(sixteen + "+0=？", ["15999999984", "0", "-1", "9"])));
    }

    [Fact]
    public void DuplicateNumericMatchesRejectIncludingNegativeZero()
    {
        Assert.Null(ArkArithmeticSolver.Solve(Question("0+0=？", ["0", "-0", "1", "2"])));
        Assert.Null(ArkArithmeticSolver.Solve(Question(labels: ["12", "\u001c12\u001f", "1", "2"])));
        // Duplicate values unrelated to the answer remain valid, as in Python.
        Assert.Equal(11u, ArkArithmeticSolver.Solve(Question(labels: ["12", "0", "0", "0"])));
    }

    [Fact]
    public void BoundedInputDoesNotScanOrEvaluateArbitraryContent()
    {
        Assert.Equal(256, ArkArithmeticSolver.MaximumQuestionCodePoints);
        Assert.Equal(256, ArkArithmeticSolver.MaximumLabelCodePoints);
        Assert.Equal(11u, ArkArithmeticSolver.Solve(Question(labels: [new string(' ', 254) + "12", "0", "1", "2"])));
        Assert.Null(ArkArithmeticSolver.Solve(Question(labels: [new string(' ', 255) + "12", "0", "1", "2"])));
        Assert.Null(ArkArithmeticSolver.Solve(Question(new string('x', 1_000_000))));
        Assert.Null(ArkArithmeticSolver.Solve(Question(labels: ["12", new string(' ', 1_000_000), "1", "2"])));
    }

    [Theory]
    [InlineData("ar-SA")]
    [InlineData("tr-TR")]
    [InlineData("fr-FR")]
    public void ArithmeticAndLabelGrammarAreCultureIndependent(string culture)
    {
        var before = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture);
            Assert.Equal(11u, ArkArithmeticSolver.Solve(Question()));
            Assert.Null(ArkArithmeticSolver.Solve(Question(labels: ["١٢", "0", "1", "2"])));
            Assert.Null(ArkArithmeticSolver.Solve(Question(labels: ["12,0", "0", "1", "2"])));
        }
        finally { CultureInfo.CurrentCulture = before; }
    }

    [Fact]
    public void CallerObservationsAreNeitherConsultedNorModified()
    {
        var question = Question() with { Selected = 0, KnownAnswer = 14, AnswerSource = "known",
            AnswerKind = "confirmed", CandidateReason = "unrelated", CandidateRevision = "r1",
            CandidateSource = "unrelated", SelectedCandidate = false };
        var state = ArkReceiveSnapshot.Empty with { Question = question, QuestionsEnabled = false };
        Assert.Equal(11u, ArkArithmeticSolver.Solve(state.Question));
        Assert.Same(question, state.Question);
        Assert.Equal(14u, state.Question.KnownAnswer);
        Assert.Equal("known", state.Question.AnswerSource);
        Assert.False(state.QuestionsEnabled);
    }
}
