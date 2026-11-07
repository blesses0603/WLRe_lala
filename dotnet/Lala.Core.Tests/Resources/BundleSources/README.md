# Synthetic connected-source parity vectors

Regenerate from the repository root:

```sh
python dotnet/Lala.Core.Tests/Resources/BundleSources/generate_bundle_sources.py
python dotnet/Lala.Core.Tests/Resources/BundleSources/generate_bundle_sources.py --check
```

The retained generator imports and executes the repository's real Python
`parse_manifest`, `fetch_official_manifest`, `build_update_plan`,
`spec_from_manifest`, `fetch_bundle`, and fingerprint functions. It reads the
actual ten required runtime table names. Every HTTP opener is an in-memory
allowlist; no network, account, credentials, or game files are used. Cache writes
are synthetic and confined to automatically removed temporary directories.

`source_sha256` pins the six source files establishing this contract. Source
normalization replaces CRLF with LF **only**. `--check` verifies both outputs and
source pins against the committed JSON, without updating it. JSON is sorted,
compact, UTF-8, deterministic, and has a final LF.

## Schema (version 1)

- `required_tables`, `asset_root`: exact Python runtime requirements.
- `cases`: use bounded `id` strings as test parameters and lazily look up the
  corresponding fixture. Do not serialize whole case objects as test IDs.
- Each case has `package`, `data_ver`, `package_version`, `manifest_size`,
  `manifest_sha256`, `manifest_crc32_le`, and ordinarily `manifest_base64`.
- `parse_ok` indicates actual parser success. Successful cases contain complete
  `expected_index` header, asset and bundle fields, including resolved names.
  Failure cases provide `error_type`, not unstable exception text.
- `manifest_verification.ok` records the actual offline authenticated manifest
  retrieval outcome.
- `plan` contains selectors, `success`, and either `error_type` or complete
  `ordered_names`, `download_bytes`, and `entries` (name, dependencies, change).
- `payloads` contain the synthetic bytes and exact size, MD5, little-endian CRC32,
  and SHA256. `downloads` record actual downloader results for valid bytes,
  same-length corruption, truncation, and excess bytes. Length mismatches fail
  at the response Content-Length guard; same-length corruption reaches checksum
  verification. These vectors are not an exhaustive transport fault suite.
- `fingerprint_deltas` hold actual before/after fingerprint tuples, a changed
  boolean, and mutation field/value for both asset and bundle fingerprints.

`note-utf8-max` is a compact boundary recipe: decode `data-valid`, replace its
package-note UTF-8 field with `value` repeated `repeat` times, and re-encode the
manifest. The expected index's note is `null` as a sentinel for that recipe; it
must be substituted with the generated note for comparison. The manifest's
size, SHA256, and CRC remain exact. Do not interpret null as a parsed null string.

Both packages have successful manifests with non-default header flags, Unicode
(including a supplementary code point), all actual parsed fields, and rejection
vectors for duplicate paths/names, invalid references, negative size, trailing
bytes, malformed boolean, invalid UTF-8, and truncation. DataPackage has all ten
required paths and ten separate missing-path vectors. All bundles contain small
synthetic payloads and exact hashes, not actual Unity bundles.

DependIDs are complete sets, not graph edges. Valid vectors deliberately contain
cycles, a self-reference, and repeated IDs. The selected root's dependency lists
are unioned once, dependencies precede roots, and each group is sorted. The
`dep-a.bundle` record lists `unrelated.bundle`, but that bundle is excluded from
the plan unless directly selected or directly listed by a root. Neither package
is rejected merely because its manifest contains cycles.

This fixture does not claim native Unity parsing, runtime table decoding,
production CDN compatibility, manifest authenticity beyond the existing CRC
contract, or real package parity. C# streaming and cancellation limits require
separate contract tests.

## Connected C# slice and hard boundaries

`YooAssetManifest` reads the actual binary 2.2.5 layout, validates every ID and
exact duplicate path/name, and owns what it parses. `BundleSourcePlan` chooses
all ten exact paths from DataPackage. MainPackage is still independently parsed
and identity-checked before any required bundle can be acquired. Dependency
order and complete-set semantics above are preserved. Whole-index deltas compare
resolved dependency names, tags, encryption, Unity CRC and file identity.

`BundleSourcePreparation` connects an **internal scripted** version/response seam
to both manifests, the required plan, bounded streamed acquisition, length/MD5/
little-endian CRC32 checks, and immutable owned-byte source handles. A handle
opens only the already-verified private byte snapshot, never a cache filename.
All response streams are disposed on success, failure, cancellation and stale
attempts. Exact response location/status is checked before Content-Length or
body reads. Final version and complete-manifest rereads reject changed versions
and same-version manifest replacements. Content identity matches the canonical
ManifestIdentity structure; observation-only CatalogKey is never substituted.
The existing ManifestIdentity API is unchanged.

The source-only status is exactly `required bundle sources verified; no runtime
candidate built`. All source-preparation types remain internal. The separately
tested `OfflineBundleRuntimePreparation` now consumes these owned handles with the
bounded native extractor and all ten structural decoders, then reobserves sources.
See `../RuntimeFlow/README.md`. There is still no production source implementation,
freshness credential, official provenance assertion, AssetsReady value, runtime
activation, resource confirmation, packet permission or login admission. Synthetic
data and matching hashes cannot mint any of those capabilities.

Runtime download quotas retain the Python ceilings of **24 files / 32 MiB** and
are checked before any bundle acquisition. A separate conservative **32 MiB total
owned source-byte cap**, including cache hits, prevents a large cached closure
from exhausting memory. Individual bundle metadata keeps Python's 256 MiB cap;
a selected closure above the total owned-byte cap is rejected. Binary manifests
retain the 8 MiB and 1,000,000 item bounds, with remaining-byte/minimum-row checks
before declared lists are allocated. Chunked reads use at most 64 KiB each and a
one-byte overflow probe. Cancellation propagates; synchronous bounded hashing
and parser operations check it between fields/steps.

### Precisely deferred cache integration

Only the **injected cache-stream seam** is implemented. Cache candidates are
fully checked during planning and checked again during acquisition. Initial
corruption is a miss; a previously planned hit that changes is a hard failure,
not an implicit extra download. Final handles remain unchanged if the original
cache file is later changed. Tests create and remove their own temporary files.

There is intentionally **no production filesystem cache adapter, persisted
receipt writer, previous-version content reuse or atomic cache publication**.
Portable path-check-then-open/rename is not an atomic no-follow boundary, and an
untrusted Unix FIFO can block a synchronous file open before cancellation. A
future platform adapter needs safe, cancellable regular-file opening and anchored
no-follow writes before this is enabled. This slice accepts no filesystem root,
performs no writes and creates no partial files, so malformed names, symlink
races or interrupted downloads cannot cause external cache writes or leave
corrupted partial files. Invalid bundle names are additionally rejected before
constructing source URLs. Do not describe the scripted seam as completed cache
or official CDN orchestration.

Focused C# verification:

```sh
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~BundleSource
```

Independent static review identified and resolved the final-observation and
unsafe portable filesystem-adapter issues. Focused Release verification passed **350 Resources tests**, including **81 new
BundleSource tests** (37 retained parser/plan cases and 44 contract tests). The
integrating task owns the full combined Core regression.
