# Bounded image pixel layer — overall PR 8.0.47

This is an internal, offline candidate layer, not an official image extractor or activation path.
An explicit internal bundle-to-image parser now composes this pixel layer. No production activation call site, downloader, SQLite writer, game socket, or public authority API is added.
`PreloginResourcePreparation.HasVisualAssets` remains false.

## Reviewed subset

- Texture2D base level: RGB24 (3), RGBA32 (4), ARGB32 (5), BGRA32 (14); exact byte length.
- Standalone Windows64 platform 19; one mip, one image, dimension 2; inline payload only.
- Texture sides at most 2048; Sprite sides at most 512. Validate limits before allocation.
- Sprite render-data rectangle: finite integer coordinates, entirely inside the texture;
  settingsRaw exactly 2 (unpacked, rectangular, no rotation, full-rect mesh, reserved bits zero).
- No atlas fallback, separate alpha texture, tight mesh, packing/rotation, streamed .resS,
  platform blob/swizzle, compressed format or guessed binary object layout.
- Crop unflipped texture bytes, then flip the crop vertically, matching UnityPy SpriteHelper.
  Preserve transparent RGB channels and alpha; no implicit color-space conversion.

## Source and cache boundaries

`SpritePixelContext` contains explicit version/manifest identity, bundle SHA256, serialized-file
identity, exact asset path and Sprite/Texture object IDs. These are **caller observations**, not
proof of PPtr resolution, official origin, currentness or bundle membership. Validation rejects
malformed fields but does not promote claims into provenance. Candidates always report
HasVerifiedProvenance=false. The default TextAsset path still rejects classes 213/28. The separate internal image extractor opts into the exact reviewed image shapes.

Decode owns the input and result. It hashes the entire texture payload, including pixels outside
the selected crop, and separately hashes top-down RGBA output. The in-memory SpritePixelCache
owns its own copy and requires a separately rebuilt current candidate on each read; exact context,
dimensions, full-source hash, pixel hash and retained bytes must all match. Returned copies cannot
mutate cache/candidate state. Cancellation never returns a partial result.

This is **not PNG/SQLite cache compatibility**, not a durable cache, and not a replacement for
production bundle MD5/CRC32/SHA256 verification or final source reobservation.

## Evidence

- Python repository: `wlre/services/world/item_image_database.py` verifies exact Sprite/Texture
  pairing in the same asset file, source bundles, PNG hash, decoded RGBA hash and source recheck.
- Fixed independent oracle: UnityPy **1.25.4**, already pinned in requirements-extractor.txt;
  `UnityPy/export/Texture2DConverter.py` CONV_TABLE and `SpriteHelper.py` get_image_from_sprite.
  Package source: https://pypi.org/project/UnityPy/1.25.4/ . No upstream source is copied or shipped.
- Unity API channel definitions: https://docs.unity3d.com/2021.3/Documentation/ScriptReference/TextureFormat.html .
  This documents channel semantics, not binary SerializedFile layout or actual official format use.
- `Resources/UnityImages/generate_vectors.py` in Core.Tests generates 20 owned pixel/field vectors
  with the actual pinned UnityPy converter and Sprite helper, using synthetic pointer stubs.
  They are **not SerializedFile fixtures** and do not prove real asset/PPtr admission.
- Boundary tests reject unsupported layouts, truncated/trailing payloads, invalid rectangles and
  context, cancellation, changed source identity/payload, and intentionally corrupted pixel cache.

## Next dependencies (not complete)

1. Extend the newly implemented fixed class 28/213 subset only with reviewed actual-source evidence;
   the current parser rejects atlases, external pointers, optional physics/bone arrays and unsupported pixel formats.
2. Determine actual official image formats from trusted source evidence; add only reviewed codecs
   with independent vectors, including compression/atlas cases where needed.
3. PNG encoder/decoder bounds and independent readback, PNG+RGBA hashes, full catalog input identity,
   transactional image SQLite cache, source recheck before commit, and revocable publication.
4. Separate item/portrait/emoji/smallmap mappings and desktop display wiring.

Validation: 56 image tests; 147 combined image/Unity decoder tests, public Core consumer and 15 repository/release checks passed locally. Release Core build: zero warnings/errors.

## 8.0.47 SerializedFile and exact pointer composition

`UnitySpriteExtractor` accepts 1–4 checksum-verified owned bundles (32 MiB combined), requires the
same data/package/version and unique bundle names, and reuses bounded UnityFS decompression.
`BoundedSerializedFile.Read(..., allowImages: true)` accepts class 28/213 only for the existing
little-endian SerializedFile22 / Windows64 / 2021.3.45f2 profile. Every embedded image tree must match
the reviewed normalized node fingerprint (type, name, size, depth, array and alignment); every object,
including unused ones, is validated. TextAsset callers never opt in automatically.

The exact AssetPath must have exactly two container entries in the **same SerializedFile**, resolving
to distinct class213 Sprite and class28 Texture objects. Both container PPtrs and the Sprite texture
PPtr must be local/non-null, and the Sprite must reference precisely that Texture. Missing, duplicated,
external, cross-file and mismatched-class targets are rejected; no basename, atlas or directory fallback.
Both object names must match the exact filename or stem. Read cursor bounds, optional-array limits,
finite numeric fields, texture byte lengths and supported full-rect features are checked before decode.
Full-rect geometry buffers are bounded and consumed, not rendered or exposed as trusted mesh data.

The returned cache context includes the caller's claimed version identity **and all input bundle specs
and SHA256 values**. Bundle checksums, typed parsing and exact PPtr matching prove byte/structural
consistency only; they do not mint official provenance, current catalog activation or game authority.

### Independent evidence and limits

- Unity's class-ID reference identifies 28/213: https://docs.unity3d.com/2021.3/Documentation/Manual/ClassIDReference.html .
- Exact release shapes are taken from UnityPy1.25.4's pinned bundled TPK, SHA256
  `16f1f8b809d1cd3bc3aeebf0cd43ecd3690b326a7a88b2273e57bcd83f5df608`.
  This is a format reference, **not a verified official game image** or a promise that official data uses this subset.
- The fixture generator retains TypeFlags directly from TPK: UnityPy's convenience node helper omits
  those flags. An independent AssetsTools read caught the missing TypelessData array flag; the generator
  was corrected, rather than relaxing accepted shapes. Core stores fingerprints, not a TPK/class database.
- Owned SerializedFile/UnityFS fixtures are rewritten by UnityPy's real SerializedFile writer and decoded through its
  SpriteHelper to expected RGBA. AssetsTools.NET3.0.5 separately reads classes, pointer targets, crop,
  dimensions, format and payload. Fixture hashes and mutation offsets are retained alongside evidence.
- The test fixtures contain two release type trees; UnityPy attribution/MIT license is included beside
  the generator. No upstream decoder or full TPK database is shipped in Core.
- This completes a bounded **offline extraction composition**, not production image activation.
  Actual official format coverage, PNG/SQLite, source reobservation before commit, revocable image
  publication, item/portrait/emoji/smallmap mappings and UI remain outstanding.

8.0.47 validation: 18 new SerializedFile/pointer tests, 165 combined image/Unity tests, Release Core build with zero warnings/errors, public consumer and 15 repository/release checks passed.
