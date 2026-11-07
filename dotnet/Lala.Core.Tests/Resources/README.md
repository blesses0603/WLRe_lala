# Offline resource identity and validation

This slice ports pure resource policy/identity checks into `Lala.Core/Resources`:

- `resource_compatibility.py`: baseline JSON shape, strict integer schema, exact two-package set, revision/Manifest agreement, size/BOM handling, split-revision labels and immutable views. The public `Shipped` baseline is exactly the current code-owned `configuration.SUPPORTED_RESOURCES`: executable 1.3.0, DataPackage `1275_2026_10_21_18_27_33_84`, MainPackage `1275_2026_10_21_18_29_38_49`. Only internal tests can parse an alternate baseline; downloaded data cannot replace it.
- `official_source.py`: the exact two-host allowlist and default. Callers explicitly supply an optional host; the Core does not read process environment, probe hosts or fall back to another origin.
- `official_version.py`: strict Manifest comparison from `check_official_versions` and numeric revision comparison. Missing input stays unverified, a bare matching integer cannot verify a Manifest, republished timestamps differ, and the independent package revisions are not collapsed.
- `official_resource_sync.py`: bounded snapshot parsing and `compare_snapshot`, including four-component DataVer versus three-component ExeVer. Timestamps remain informational strings as in Python. No inferred TTL/freshness is added.
- `world/catalog_runtime.py`: `official_package_versions`, canonical `official_catalog_key` and `select_catalog_runtime`. Selection always requires source validation. Unicode and special ASCII quoting reproduce Python `ensure_ascii=True` identity hashes.
- `world/official_catalog_store.py` and `world/dynamic_bundle_runtime.py`: metadata-only validation from `active_official_catalog` and `load_dynamic_runtime_metadata`, against an already supplied metadata projection rather than SQLite I/O. All **five** current `catalog_adapters.FEATURES` (`npc`, `shops`, `crafting`, `scenes`, `items`) are required despite old Python docstrings saying four. Exact current catalog key, source-name/schema presence, lowercase digest shape and integer record-count bounds are preserved.
- `world/catalog_identity.py`: internal post-parser identity derivation checks both package specs and parsed headers, bounds source bytes, checks little-endian CRC32 and calculates SHA-256 plus the exact canonical identity. `dynamic_bundle_runtime._confirm_runtime_sources` before/after identity checks reject package/ExeVer/DataVer changes and replacement Manifest bytes, even if replacement bytes have a new matching CRC.

## Trust boundary

An observed version string or claimed JSON origin is not an authenticated official fetch. Catalog keys identify observations, not approval. Display metadata validates digest **shape**, not payload integrity. Every public decision/view remains non-ready and cannot authorize packets, login, runtime activation or catalog consumption. Extra incoming readiness/permission fields cannot elevate those outputs.

Manifest derivation and input types are internal because the official HTTPS fetch, complete YooAsset parser and receipt provenance adapter have not been ported. Synthetic tests use this internal seam without creating a public factory for caller-supplied “verified” bytes or CRCs. Derived immutable identities retain hashes, not game asset bytes. Public ItemData/SkillData fixed digest checks are unchanged; this slice cannot bypass them.

The shared Core has no environment/filesystem/SQLite/network/Unity/UI dependency here. There is no live activation, automatic source fallback or AccountSession wiring. Required image-file packaging checks and `resource_manifest.validate_resources` (PNG/ICO/ZIP/gzip integrity) remain Python.

## Bounded and immutable behavior

The baseline/snapshot limits retain Python's 4096-byte limits. Public observation/metadata projections add a conservative **64 KiB** cap, including ignored fields and whitespace, because Python receives these as already materialized dictionaries. This is deliberate fail-closed hardening, not a newly reviewed source schema. JSON also uses the platform parser's default depth bound of 64 and rejects invalid Unicode escape sequences when consuming identifiers. These narrower input rules do not broaden source trust.

Cancellation is checked around bounded JSON parsing and SHA operations, between metadata/Manifest entries, and every 4096 bytes during CRC processing. Platform JSON/SHA calls themselves are synchronous and cannot be interrupted mid-call; their inputs are bounded. Cancellation propagates instead of becoming a successful or partial result. Outputs own frozen dictionaries/read-only collections; mutable input buffers cannot change a completed identity. No state is installed or changed on failure.

## Reproduce

From the repository root:

```sh
python dotnet/Lala.Core.Tests/Resources/generate_resource_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Resources
```

The generator executes the retained Python functions against **228** synthetic cases, including baseline policy, snapshot shapes/comparison, strict package matching, Unicode canonical hashes, approved origins, actual SQLite metadata validation and synthetic post-parser Manifest CRC/SHA identities. No network calls, proprietary bytes, official downloads or credentials are used. Generated vectors are deterministic and checked in.

Additional tests cover frozen results, caller-byte ownership, missing/stale inputs, every required feature, unchanged prior results after failure, source replacement with matching new CRC, oversized input, JSON type coercion, non-authorizing flags and cancellation. The full retained Core test suite must also pass.

## Remaining integration/acceptance gaps

No complete source adapters, trusted source-contract issuance, source extraction, official fetch/redirect handling, persisted cache receipts, runtime loading/activation, safety-hold monitoring, installed asset/package validation or platform/server acceptance is claimed. Synthetic CRC/hash parity cannot certify official resource provenance. No Python source is deleted or marked fully migrated by this slice.
