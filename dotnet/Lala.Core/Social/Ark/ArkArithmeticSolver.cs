using System.Globalization;
using System.Text.RegularExpressions;

namespace Lala.Core.Social.Ark;

/// <summary>
/// Pure, conservative port of services/ark_first_answer.py. The returned text ID is
/// an arithmetic match, not a server-confirmed answer or permission to send it.
/// The caller still owns question provenance. No state, persistence or dispatch.
/// </summary>
public static partial class ArkArithmeticSolver
{
    public const int MaximumQuestionCodePoints = 256;
    // Deliberate resource bound: Python permits unlimited whitespace around labels.
    public const int MaximumLabelCodePoints = 256;

    private const string Number = "(?:0|[1-9][0-9]{0,8})";
    private const RegexOptions PatternOptions = RegexOptions.CultureInvariant | RegexOptions.NonBacktracking;

    /// <summary>Returns the unique matching positive uint text ID, otherwise null.</summary>
    public static uint? Solve(ArkQuestionSnapshot? question)
    {
        if (question is null || !WithinCodePointLimit(question.Text, MaximumQuestionCodePoints)
            || question.Options.IsDefault || question.Options.Length != 4
            || question.Labels.IsDefault || question.Labels.Length != 4)
            return null;
        for (var i = 0; i < 4; i++)
        {
            if (question.Options[i] == 0) return null;
            for (var j = 0; j < i; j++)
                if (question.Options[i] == question.Options[j]) return null;
        }

        var questionMatch = QuestionPattern().Match(question.Text);
        if (!questionMatch.Success) return null;
        var expression = questionMatch.Groups["expression"].Value;
        long numerator;
        long denominator = 1;
        if (SumPattern().IsMatch(expression))
        {
            numerator = 0;
            foreach (Match term in TermPattern().Matches(expression))
                numerator += long.Parse(term.Value, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture);
        }
        else if (AddPattern().Match(expression) is { Success: true } addition)
            numerator = ParseNumber(addition.Groups[1]) + ParseNumber(addition.Groups[2]);
        else if (ProductPattern().Match(expression) is { Success: true } product)
        {
            var a = ParseNumber(product.Groups[1]);
            var operation = product.Groups[2].Value;
            var b = ParseNumber(product.Groups[3]);
            if (operation is "除以" or "÷")
            {
                if (b == 0) return null;
                numerator = a;
                denominator = b;
            }
            else numerator = a * b;
            if (product.Groups[4].Success)
            {
                var divisor = ParseNumber(product.Groups[4]);
                if (divisor == 0) return null;
                denominator *= divisor;
            }
        }
        else return null;

        // Operand and term limits prove both values fit signed Int64. Keeping the
        // denominator until here preserves Python Fraction's exactness, no rounding.
        if (numerator % denominator != 0) return null;
        var result = numerator / denominator;
        uint? answer = null;
        for (var i = 0; i < 4; i++)
        {
            if (!TryParseLabel(question.Labels[i], out var value)) return null;
            if (value != result) continue;
            if (answer is not null) return null;
            answer = question.Options[i];
        }
        return answer;
    }

    private static long ParseNumber(Group group) => long.Parse(group.Value, CultureInfo.InvariantCulture);

    private static bool TryParseLabel(string? label, out long value)
    {
        value = 0;
        if (!WithinCodePointLimit(label, MaximumLabelCodePoints)) return false;
        var first = 0;
        var last = label!.Length;
        while (first < last && IsPythonWhitespace(label[first])) first++;
        while (last > first && IsPythonWhitespace(label[last - 1])) last--;
        var text = label.AsSpan(first, last - first);
        if (text.IsEmpty) return false;
        var negative = text[0] == '-';
        var digits = negative ? text[1..] : text;
        if (digits.Length is < 1 or > 13 || (digits.Length > 1 && digits[0] == '0')) return false;
        foreach (var digit in digits)
        {
            if (digit is < '0' or > '9') return false;
            value = value * 10 + digit - '0';
        }
        if (negative) value = -value;
        return true;
    }

    // Python str.strip includes U+001C..U+001F, unlike .NET string.Trim.
    private static bool IsPythonWhitespace(char value) => value is >= '\u0009' and <= '\u000D'
        or >= '\u001C' and <= '\u0020' or '\u0085' or '\u00A0' or '\u1680'
        or >= '\u2000' and <= '\u200A' or '\u2028' or '\u2029' or '\u202F' or '\u205F' or '\u3000';

    private static bool WithinCodePointLimit(string? text, int limit)
    {
        // Every Python character needs at most two UTF-16 code units. The fast
        // bound also prevents scanning arbitrary caller-supplied megabyte strings.
        if (text is null || text.Length > limit * 2) return false;
        var count = 0;
        for (var i = 0; i < text.Length; i++)
        {
            if (++count > limit) return false;
            if (char.IsHighSurrogate(text[i]) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1])) i++;
        }
        return true;
    }

    [GeneratedRegex(@"\A(?:請問)?(?<expression>.+?)(?:等於多少|是等於多少|等於|=)[？?]\z", PatternOptions)]
    private static partial Regex QuestionPattern();
    [GeneratedRegex(@"\A" + Number + "(?:[+-]" + Number + @"){1,15}\z", PatternOptions)]
    private static partial Regex SumPattern();
    [GeneratedRegex(@"[+-]?[0-9]+", PatternOptions)]
    private static partial Regex TermPattern();
    [GeneratedRegex(@"\A(" + Number + ")(?:加上|加)(" + Number + @")(?:的話)?\z", PatternOptions)]
    private static partial Regex AddPattern();
    [GeneratedRegex(@"\A(" + Number + @")(乘上|乘以|×|\*|除以|÷)(" + Number + ")(?:再除以(" + Number + @"))?\z", PatternOptions)]
    private static partial Regex ProductPattern();
}
