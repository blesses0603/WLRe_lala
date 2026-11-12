# Reviewed Ark candidate index: offline and unconfirmed

This increment ports `wlre/services/ark_candidates.py` and the complete text-free
`ark_candidate_data.py` into Core. It does not execute the Python audit tool or
retrieve its private report/official text inputs.

## Preserved data and decisions

- Exactly 200 reviewed rows: 63901 through 63996, step 5, and 103505 through
  104400, step 5. Every answer ID, option tuple, and exact text fingerprint is
  copied from retained Python, without recreating official question text.
- Data version `1.3.23`, package `1296_2026_11_04_13_34_19_13`, manifest/text/source
  SHA-256 values, review revision, and index digest remain unchanged. The index
  digest is `dd7ef46db2e8abc1b542f7b28802351ceda1c9168fcb3abf0bb0d532892ca6ac`.
- Zero current static quarantines and all 16 user-reviewed annotations remain
  distinct. Synthetic fixtures exercise quarantine as well as user review.
- `not_covered`, `version_mismatch`, `changed`, `quarantined`, and `candidate`
  retain the Python reason, source, and revision. No result is server-confirmed.

`ArkReviewedCandidates.Index` validates the entire immutable built-in index
before returning any entry. Validation checks the digest, unique expected IDs,
answer membership, four distinct positive options, lowercase 64-character
fingerprints, complete expected coverage, annotation coverage and disjointness.
The digest is Python-compatible compact sorted-key JSON with exact Unicode,
including numeric sorting of annotation keys before JSON string conversion.

`Resolve` requires precisely one observed `DataPackage` with the exact version,
manifest SHA-256 and data version. Other package observations are ignored, as in
Python. `ArkCandidateVersionObservation` represents caller-supplied observations,
not authenticated or activated resources. `ArkCatalogToken` alone cannot carry
these fields and is not manufactured. No role or catalog token is invented.

Question fingerprinting reuses `ArkQuestionIdentity.Payload` from Core storage,
without changing its API. Reordering paired option IDs/texts is harmless;
changing question text, any label, option IDs, or their text binding is not.
Coverage is checked before version, and version before question validation.
Even an unsorted otherwise-valid index tuple does not silently get normalized.

## Differential evidence

Run from the repository root:

```sh
python -m unittest tests.test_ark_candidates tests.test_ark_first_answer -q
python dotnet/Lala.Core.Tests/Social/Ark/Candidates/generate_ark_candidate_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~ArkCandidate
```

The generator invokes the actual retained Python index, resolver and fingerprint
functions. Positive candidate/quarantine resolution uses temporary synthetic
indexes whose fingerprints are recomputed from synthetic question text. This
does not prove a production official-text match. The real text-free built-in
index is separately checked against every original row, metadata field,
annotation and aggregate digest; synthetic text against that real index is
rejected as `changed`. The fixture contains 4,865 resolution cases, including all 200 IDs in
all 24 paired option orders, and 42 whole-index validation cases. Additional
contracts check immutable data, malformed typed inputs, culture independence,
UTF-16 surrogate rejection, exact data copy, source hashes and file limits.

Boundary cases include duplicate/missing/wrong-version packages, mismatched
manifest, changed IDs/text/label binding, malformed questions, changed data with
stale or recomputed digests, missing/duplicate/out-of-range records, invalid
options/digests, overlapping annotations, Unicode/control characters and the
32,768 Unicode-scalar text boundary. Maximum-size text is synthetic only.

Fixture generation uses the shared deterministic gzip helper. Compressed and
expanded SHA-256 hashes are verified when loading the embedded resource. No
base64 C# strings or official text are bundled. Source fingerprints normalize
only CRLF byte pairs; lone CR, Unicode separators and all other bytes remain
significant. All increment files are below 500,000 bytes with LF or CRLF.

## Boundaries and gaps

- IDs/options use the existing `uint` question domain. Arbitrary Python object
  types, boolean-as-integer values and out-of-domain integers are not exposed
  through a dynamic import API. Synthetic typed corruptions are tested; this
  does not claim parity for arbitrary malformed Python objects.
- The internal synthetic-data injection seam exists only for tests. Public
  callers can neither replace the reviewed index nor supply review provenance.
- Pure resolution does not write storage, execute receive intents, claim an
  attempt, select or send an answer, authorize actions, or establish server
  confirmation. It does not wire the resolver into receive/service orchestration.
- Production official text was not downloaded or inspected. Exact production
  text matches and live-server correctness remain unverified. User review is
  still an unconfirmed candidate, never permission or a server answer key.
- No desktop, Android, transport, lifecycle, or shared storage API is changed.
