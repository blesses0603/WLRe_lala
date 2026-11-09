# Bounded image pixel layer — overall PR 8.0.46

This is an internal, offline candidate layer, not an official image extractor or activation path.
No production call site, downloader, SQLite writer, game socket, or public authority API is added.
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
HasVerifiedProvenance=false. The production SerializedFile walker still rejects classes 213/28.

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

1. Independently produced class 28/213 serialized fixtures and reviewed exact type-tree shapes;
   bounded parser, exact container Sprite/Texture pairing and same-file PPtr resolution.
2. Determine actual official image formats from trusted source evidence; add only reviewed codecs
   with independent vectors, including compression/atlas cases where needed.
3. PNG encoder/decoder bounds and independent readback, PNG+RGBA hashes, full catalog input identity,
   transactional image SQLite cache, source recheck before commit, and revocable publication.
4. Separate item/portrait/emoji/smallmap mappings and desktop display wiring.

Validation: 56 image tests; 147 combined image/Unity decoder tests, public Core consumer and 15 repository/release checks passed locally. Release Core build: zero warnings/errors.
