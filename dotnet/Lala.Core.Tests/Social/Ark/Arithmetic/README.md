# Strict Ark first-answer arithmetic

`ArkArithmeticSolver.Solve(ArkQuestionSnapshot?)` is a standalone, pure port of
`wlre/services/ark_first_answer.py:solve`. It returns a unique matching option's
text ID or null. It reuses the immutable receive question shape without changing
receive/storage behavior or installing a callback. Other snapshot fields,
including known answers, candidates, selected options and readiness, are ignored.
The result is not a server answer key, provenance verification or authorization.
No execution, network, persistence, command generation, sending, knowledge lookup,
or language-model guessing is implemented.

## Preserved source behavior

- The complete question must match the original optional `請問`, expression,
  `等於多少` / `是等於多少` / `等於` / `=`, and `？` / `?` grammar. Anchors use
  `\A` and `\z`, not a dollar anchor that accepts a final newline. Nothing trims
  question text or normalizes punctuation, digits, spaces or operators.
- Python's 256-character question limit counts Unicode code points, not UTF-16
  units. Scanning is bounded before examining content; lone surrogate units are
  counted singly and fail the arithmetic grammar.
- Decimal operands are `0` or one through nine ASCII digits without leading zero.
  Sum/difference chains have 2–16 operands. Chinese addition optionally ends in
  `的話`. Products/divisions accept exactly the retained six operation spellings,
  with at most one `再除以` suffix. Mixed operators, signs on operands, parentheses,
  decimal/exponent/alternate-base numbers and general text do not match.
- Rational intermediates stay exact. Nine-digit operand bounds put the largest
  product/denominator below 10^18, and sums of 16 terms below 16 billion, so signed
  Int64 arithmetic is sufficient. Division is deferred until numerator modulo
  denominator is zero. Zero denominators and non-integer results return null.
- Four distinct positive option IDs and four labels are required. Every label must
  match `-?(0|[1-9][0-9]{0,12})` after Python-compatible Unicode stripping. This
  includes U+001C–U+001F, which .NET's default Trim does not remove. ASCII digits,
  minus sign, negative zero and the original 13-digit limit are preserved.
- Exactly one label must equal the answer numerically. `0` and `-0` are duplicate
  answers; duplicates unrelated to the result remain allowed. One invalid label
  rejects the question even when another valid label matches.

## Explicit typed deltas

The existing immutable snapshot uses uint option IDs instead of arbitrary Python
positive integers. Booleans, negative integers, floats, mutable/custom collection
objects and arbitrary object types are not accepted as typed imports. Zero IDs,
duplicate IDs, wrong counts, null text/labels and default arrays return null.
Missing/null questions return null rather than Python's non-dictionary exception.
No generic Python-object coercion layer is introduced.

Raw labels have an additional 256-code-point resource limit. Python allows
unbounded edge whitespace; this port intentionally returns null when even an
otherwise-valid whitespace-padded label exceeds the limit. The oracle includes
real Python answers at raw lengths 257, 512, 513 and 4096 and separately records
this Core rejection. It also records Python accepting an option ID of 2^80, which
is outside the typed uint domain. These are documented deltas, not parity claims.

## Retained-Python differential checks

`generate_ark_arithmetic_vectors.py` imports and calls the actual retained source,
never a reimplemented solver, and verifies inputs remain unchanged. Its 304 small
synthetic cases cover every wrapper and operation spelling, exact large rational
intermediates, fractional/zero-divisor rejection, the 16-term edge, malformed and
injection-like text, all 29 Python whitespace characters, non-whitespace Unicode,
label grammar, duplicate answers, reordered/max-uint IDs, null/default boundaries
and fixed-seed arithmetic. Expected results are produced only by Python `solve`.

The 49,561-byte JSON corpus stays a small readable raw C# string, below the
100,000-byte generator guard; no base64 is used and no shared project file is
changed. Physical fixture sizes are 49,772 bytes with LF and 49,781 with CRLF.
Source fingerprints cover the retained solver, its original tests and the
generator. Hash normalization changes only CRLF byte pairs to LF, preserving lone
CR and all other bytes. The generator's `--check` mode verifies reproducibility.
A contract test checks every increment file against 500,000 physical bytes for
both LF and CRLF checkouts.

```sh
python dotnet/Lala.Core.Tests/Social/Ark/Arithmetic/generate_ark_arithmetic_vectors.py --check
python -m unittest tests.test_ark_first_answer -v
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~ArkArithmetic
```

Verified on this worktree:

- Focused Release suite: **336/336 passed**, comprising 304 retained-Python cases
  and 32 source/boundary/contract checks. No skipped or failing tests.
- Original Python unittest module: **5/5 passed**.
- Generator `--check` passes, and two independent generations are byte-identical.
- Every increment file passes both LF/CRLF physical-size checks; `git diff --check`
  passes. Shared project/build-policy files remain unchanged.
- Two initial invocations stopped before compilation because default NuGet cache
  directories were read-only. Standard writable XDG cache/runtime locations fixed
  the environment without disabling audits or changing build policy. The first
  actual compilation caught a C# string-escape typo in the product regex; making
  that literal verbatim fixed syntax without changing the regex. The final
  focused command compiled both projects and passed all tests.
- Full Core regression is deferred to the coordinating integration run so .NET
  compilation stays serialized. No full-suite claim is made for this increment.

Tests are offline, not official-resource, live-game, platform/device or complete
Ark acceptance. Receive/storage/runtime orchestration remains unchanged.
