# Bounded UnityFS / TextAsset milestone

Internal, offline extraction consumes `VerifiedBundleSource` handles. It neither grants
resource readiness nor supplies official provenance, a network source, cache writes,
AccountSession integration, or an Android call site.

## Deliberate supported subset

- UnityFS format6/7/8, uncompressed or raw LZ4/LZ4HC blocks and block info. Front/end
  block-info layouts are supported. Canonical LZ4 final literal/minimum trailing-distance
  constraints are enforced; match-terminated encodings reject. LZMA, encrypted and unknown flags reject. The
  ambiguous0x200 padding flag is accepted only for reviewed Unity2021.3.45f2.
- SerializedFile22, little-endian, Windows64 target19, engine2021.3.45f2, embedded trees.
  Only class142 AssetBundle and class49 TextAsset are accepted. No class database.
- Tree **parsing semantics** match the reviewed58-node AssetBundle and9-node TextAsset
  layouts: exact types, names, hierarchy, sizes, array flags, and alignment. Inert node
  versions/non-alignment metadata bits are normalized. Unknown shapes fail closed.
- Full ordinal AssetPath matching and duplicates within/across every container reject,
  including repeated mappings to the same object. Only class49 resolves, with name
  exactly the filename or its final-extension-free stem. Script bytes are copied as
  bytes, including NUL/invalid UTF-8, never converted through text.
- Per-file identities are `(verified bundle name, exact directory entry name)` within
  one data/package/version context. CAB collisions never alias. External PPtrs require
  an explicit source-file/exact-external-path/target-file allowlist. There is no basename
  fallback, filesystem probing, automatic dependency load, HTTP, or external open.

## Bounds and ownership

Input:1–24 distinct bundles,1–64MiB each,128MiB aggregate. Expansion:64MiB per bundle,
128MiB aggregate. Block info4MiB;4096 blocks per bundle. Serialized files128 aggregate,
metadata4MiB per file/16MiB aggregate,16 types per file,128 nodes/16KiB strings per type,
object32MiB and16,384 objects aggregate. Containers100,000 entries aggregate with1024-byte
paths and8MiB aggregate encoded paths, checked **before** decoding strings. Script max16MiB;
only the requested script must be nonempty. Preloads100,000 per object,128 dependencies,
1024 scene hashes,128 externals per file/allowlist entries.

These are allocation/expansion ceilings, not a peak RSS guarantee. Owned verified bytes,
transient compressed input, decompressed buffers, dictionaries and string values can
coexist. Returned payload owns its own byte array and does not retain backing files.
Streams are always scoped with `using`. Cancellation checkpoints run on input chunks,
block sequences, LZ4 matches every4096 bytes, metadata/object/container loops and return.
There is no Task.Run cancellation illusion or unbounded upstream decompressor.

## Evidence and reproduction

`generate_fixtures.py` constructs small original type trees and SerializedFile objects,
round-trips them through the actual UnityPy1.25.4 writer, checks writer stability, then
independently loads real UnityFS bundles and checks exact raw payload. LZ4/LZ4HC fixtures
use the independent Python lz4 4.4.5 raw-block compressor. `Fixtures/evidence.json` records
hashes, payload and scalar versions. There are no copied game object payloads or class
databases. `layout.json` is a compact offset recipe for malformed tests.

Run with installed UnityPy1.25.4 and lz4 4.4.5 on PYTHONPATH:

    python dotnet/Lala.Core.Tests/Resources/UnityTextAssets/generate_fixtures.py

Tests additionally use official AssetsTools.NET **[3.0.5]** to independently decode only
trusted, retained writer fixtures, reading `m_Script.Value.AsByteArray`. Runtime Core has
no AssetsTools.NET dependency. Unsafe package APIs are never called for mutated inputs.
Official NuGet package SHA256:
`e3b79ad8271aa8d84df541ddecba2402448408fd648b33b6a3c2e2a9a1c1d384`.
The nuspec has the official repository URL but no source commit.
The format walker was source-reviewed against upstream commit
2d66992b60d583d6d82dd6e278d3946cf5827286 and UnityPy1.25.4. Package binary/source
reproducibility is not assumed. Third-party notice accompanies the common string table.

A read-only local audit observed22 DataPackage bundles with UnityFS8, engine2021.3.45f2,
SerializedFile22, embedded trees, only classes49/142, header0x243 and244 LZ4HC data blocks.
That is **metadata compatibility evidence**, not actual-game extraction acceptance.
No game bytes are retained here. Desktop execution and Android runtime/AOT, end-to-end
resource preparation/catalog/session integration remain unverified and unenabled.
