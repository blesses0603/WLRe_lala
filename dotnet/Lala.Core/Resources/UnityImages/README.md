> 8.0.76: current-scene Python projection and confirmed-position overlay; official production resource owner bootstrap/read-only refresh, 562-map publication/revocation and 799 synthetic scene positions verified. Live account/game-screen acceptance remains pending. [Details](../../../../docs/DOTNET_SMALLMAP_RECEIPTS.md).

> 8.0.75: bounded small-map disk acquisition, version rechecks, private PNG publication and revocable current-scene desktop rendering are connected. Integrated official acceptance and coordinate mapping remain pending. [Details](../../../../docs/DOTNET_SMALLMAP_RECEIPTS.md).

> Production emoji activation is still capacity-blocked: required tables plus emoji closure total 33,772,710 bytes, above unchanged 33,554,432 retained-byte bound, including cache hits. Factory validation is not full production activation.

> 8.0.71: production emoji factory consumes immutable verified closure, rebuilds pixels and joins existing SQLite/current-publication path. Cached official 62-frame factory/readback validated; live owner/UI acceptance pending. Smallmap source preflight rejects observed 43,187,027-byte closure under unchanged 32 MiB capacity. [Details](../../../../docs/DOTNET_EMOJI_PRODUCTION.md).

> 8.0.70: exact local emoji graph projection retains full metadata validation and selected-object physics limits. Fractional crops follow UnityPy/Pillow double endpoint ties-to-even rounding. Verified private official cache: 62 full RGBA/token matches and independent SQLite round trip. Production source factory/publication and smallmap remain pending. See [evidence](../../../../docs/DOTNET_EMOJI_DISPLAY.md).

> 8.0.69: desktop now consumes a revocable emoji gallery request, decodes shared first frames in the background, fits a single-page grid and inserts local draft tokens only. Production emoji sources remain uninstalled: the fresh verified official root bundle is rejected by the full-object parser at an unrelated Sprite physics quota. See [display and source evidence](../../../../docs/DOTNET_EMOJI_DISPLAY.md). No full official image acceptance is claimed.

> Current update (8.0.68): emoji candidate batches now have transactional SQLite storage, independent readback and revocable owner/account PNG reads, exercised only through an internal offline factory. Production emoji acquisition/publication and desktop gallery are not installed. Desktop shows the pending path and write status only. See [cache boundaries](../../../../docs/DOTNET_EMOJI_CACHE.md). Official positive-format acceptance remains incomplete; historical sections below describe their original version.

> Current scope: v8.0.53 conditionally prepares, stores and publishes supported item images in production. BC1/BC3 now compose the same bounded pipeline; desktop native decodes reuse exact current bytes. Other image families and actual official positive-format acceptance remain incomplete. Earlier version sections below retain their historical scope.

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

## 8.0.48 canonical PNG and offline SQLite cache

`SpritePng` writes PNG RGBA8, filter None, one IDAT, noninterlaced, with deterministic stored
DEFLATE blocks, CRC32 chunks and Adler32. Dimensions remain 1..512. This intentionally trades
compression for a small auditable format, independent of runtime compression versions.
References: https://www.w3.org/TR/png-3/ and https://www.rfc-editor.org/rfc/rfc1950 and
https://www.rfc-editor.org/rfc/rfc1951 . `generate_png.py` verifies owned vectors with Pillow13
and Python zlib, including multiple DEFLATE blocks and 512×512 output.

`SpritePngStore` consumes an exclusively supplied closed SQLite connection, with a dedicated exact
schema (not the Python image database). It owns no path selection, HTTP, credentials or game I/O.
The supplied candidate list must be independently rebuilt from current sources, have one exact
VersionIdentity/source-set, unique exact AssetPaths, 1..8192 entries and at most 96 MiB estimated PNG
bytes. Reads require exactly that index, complete context/layout/crop/source/pixel identity, bounded
PNG storage, its SHA256, AND byte equality to a fresh canonical encoding of the independent candidate.
Thus a corrupt cache cannot approve its own pixels even if its hashes are replaced. Arbitrary PNG
filters, compressed streams and metadata are never parsed or inflated. This is a canonical-cache
validator and writer, not a general PNG decoder or Python cache import implementation.

Writes replace the complete catalog in BEGIN IMMEDIATE, independently read it back, then run the
required source-revalidation callback and cancellation check immediately before COMMIT. Reads use a
snapshot transaction and the same final revalidation. Existing inventory transaction machinery records
committed/not-committed/unknown outcomes and cleanup failures; a late/uncertain commit is not retried.
No source callback itself proves official provenance. Returned buffers are caller-owned offline data,
not a live/revocable publication; owner generation admission and replacement after return remain the
future production bridge's responsibility. This API must not be wired directly to a ready UI flag.

Tests cover owned UnityFS→Sprite/Texture→pixels→PNG→SQLite→reopen/rebuild; independent PNG vectors;
corrupt hashes/identity/PNG/storage/index; forged PNG plus matching hash; same-pixel version changes;
source-set mixing; aggregate bounds; source recheck failure/cancellation rollback; readonly writes;
unexpected triggers; and atomic replacement. No actual official game assets or credentials were used.

Remaining: actual official format evidence/coverage, trusted production image acquisition and final
source reobservation/generation admission, item/portrait/emoji/smallmap mapping, revocable publication,
Python cache compatibility if required, and UI. HasVisualAssets remains false. 8.0.47 CI is unverified.

8.0.48 local checks: all 22 new cache/PNG tests passed; Release Core build has zero warnings/errors;
public consumer and 15 repository/release checks passed. The full Core regression and exact-head CI
are recorded separately on PR #79; these focused results do not claim platform or official acceptance.

## 8.0.49 物品圖 MainPackage 來源與映射基礎

核對 Python item_image_database.py／dynamic_bundle_runtime.py 後，新增 MainPackage 精確物品圖清單及模型映射：s1000 預設圖不可缺、模型不得重複、未知物品或缺圖回退 1000；ItemData 必須提供 ReviewedDetails，舊版未知圖示欄位不猜測。映射包含圖示、寬高及 open_used，與 manifest SHA256 一起形成輸入指紋。

Bundle 計畫沿用 YooAsset 完整依賴集合語意，不遞迴擴張；上限 4 個 Bundle／32 MiB。取得沿用既有受限來源、版本／manifest、checksum 及 attempt 機制，並共享必要資料的總下載／保留額度；比 Python 分開圖資額度更保守，沒有增加總配額。以檔名為鍵的既有已持有來源遇到不同 package／spec 一律拒絕，不能跨 package 誤用同名檔。

本批為內部計畫／取得與唯讀映射層，尚未由 production owner 自動呼叫；未宣稱實際官方圖片成功解碼。後續仍需將每圖來源閉包、完整批次來源與映射指紋接入 PNG／SQLite，再接 owner 的版本撤銷及 UI。四類圖資、正式格式覆蓋、可撤銷 publication 與 UI 未完成，HasVisualAssets=false。

Python parity is for typed item IDs. Python also coerces arbitrary values through int(); Core accepts ushort IDs only. Parsed manifests and reviewed field shapes do not grant official provenance. The new acquisition entry point remains internal and uninstalled until decoding, batch context, storage and revocation are composed.

8.0.49 local focused validation: 62 mapping/source tests passed (18 new), public Core consumer and
15 repository/release checks passed; Core Release build zero warnings/errors. All source responses are
synthetic and Python vectors use owned inputs. Full Core regression and exact-head CI are recorded on PR #79.

## 8.0.50 物品圖 production 準備、撤銷與桌面顯示

已將物品圖條件式接入 production 資源準備：ItemData 必須有經審閱的圖示欄位，MainPackage 必須含精確圖示清單；未知欄位、未支援格式或來源取得失敗時不產生圖片候選。下載仍共用原有總額度，圖片閉包維持 4 Bundle／32 MiB，不增加帳密或遊戲傳送權限。

每個 Bundle 在整批只解析一次；每張圖仍僅能在 manifest 指定的 root＋完整依賴集合解析同檔 Sprite／Texture 指標。整批指紋包含版本 identity、manifest、映射／尺寸／open_used、全部 Bundle specs／SHA256 與每圖依賴；不同依賴的圖片可共同寫入快取，沒有降低逐圖來源驗證。整批像素／PNG 預算維持 96 MiB。

owner 將完整批次寫入固定 core_item_images_v1.sqlite3，關閉後重新開啟只讀比對全部 PNG，再重查遠端版本／manifest，清理完成後才建立圖片 publication。寫入前重查來源、commit 前檢查當前 attempt；遠端版本與本機交易無法原子化，寫入後來源變更仍會拒絕發布。必要資料庫與圖片庫不是跨庫交易，圖片寫入另回報 NotAttempted／NotCommitted／Committed／Unknown，停止不回復既有寫入、不自動重試不明結果。只讀 refresh 不建立缺少的圖片快取；圖片庫損壞或寫入失敗目前會阻擋本次 owner 發布，保留結果供確認。

圖片讀取沿用 ResourceRuntimeActivation 及帳號快照，逐次核對 owner／publication／generation；回傳僅為呼叫者擁有的歷史 PNG 副本，不能作為後續操作權限。停止、版本／帳號切換與釋放撤銷讀取。桌面背包及儲藏格每次刷新重新取得圖片，欄位未改變時也會處理圖片更新／撤銷；關閉與撤銷清除 Bitmap 並釋放。原生解碼前檢查 PNG header／尺寸上限；缺圖維持名稱與未通過驗證狀態。資源確認視窗新增圖片庫路徑及寫入結果。

測試只使用自有合成 Bundle／PNG、SQLite 與 loopback。owner 正向持久化測試使用明示 offline image hook，撤銷測試沿用 white-box publication seam；這些都不能證明官方來源正向驗收，production 建構不接受 hook／來源注入。原生 UI 測試發現「庫存不變便跳過重繪」會漏掉圖片撤銷，已修正並新增顯示／失敗／清除檢查。

**仍未完成**：實際官方圖片格式正向驗收、更多 Texture／Sprite 格式、頭像、表情、小地圖及 Python 全介面一致。HasItemImages 反映當前物品圖狀態；HasVisualAssets 仍為 false，不冒稱全圖資完成。既有帳密逐次確認、無 TLS／XOR 可逆提示、停止等待清理及一般遊戲操作 Held 均保留。

8.0.50 local desktop verification: Release build zero warnings/errors; offline checks 68;
native UI 233 checks with 30 rendered screenshots, catalog 10, resource confirmation 6 and login
loopback 11 passed. The owned red-pixel PNG screenshot was visually inspected. Public Core consumer
and 15 repository/release checks passed. Full final-source Core regression and exact-head CI are
recorded on PR #79; no real accounts, official HTTP/game sockets or user-computer operations were used.

## 8.0.53 壓縮圖像接線與背包解碼重用

新增 TextureFormat 10（DXT1／BC1）與 12（DXT5／BC3）的受限 base-level 解碼，接在既有精確 SerializedFile 圖片路徑，因此符合既有 Sprite 條件的壓縮圖片可進入原本 production 物品圖批次、PNG／SQLite 與撤銷 publication。尺寸、逐圖指標／來源依賴、manifest、版本與容量限制不變；不接納 Crunch、mip、外部 streamed texture、SpriteAtlas 或材質。

依據為 Unity TextureFormat 文件、Microsoft BC1／BC3 區塊規格及固定 UnityPy 1.25.4 的 Pillow bcn 解碼。Python 已審查頭像來源的 portrait_assets.py 明列格式 4／10／12，證明這是後續頭像的實際相依，但不代表本批已載入官方頭像。96 組自有向量覆蓋 RGB565 插值、透明色、兩種 alpha 端點模式、所有 selector、邊界 padding、跨 block 裁切與垂直方向；自有 SerializedFile／Bundle 經真實 UnityPy writer 和 SpriteHelper 對照後，再測 PNG／SQLite 關閉重開回讀。完整壓縮來源仍納入 SHA256，快取不能只以輸出像素證明來源一致。

桌面背包／兩種儲藏格原本每次 Paint 都重建每張 Bitmap。現在每次仍從目前 runtime 取得每格 PNG，檢查 header、尺寸與完整 bytes；僅重用完全相同內容的 native Bitmap，同幀重複圖也共用。每個 grid 最多保留目前 24 格所用的圖片，換頁、內容變更或撤銷會在舊控制項移除後釋放不再使用的 Bitmap，換帳與關閉清空。沒有全域跨帳號快取，沒有跳過來源檢查，也不新增背景工作或影響 UI 排序／選取。

測量方式是原生解碼呼叫計數，而非推測耗時／FPS：24 個相同 PNG 的可見格只需 1 次 native decode；接著 10 次相同刷新新增 0 次（舊 Paint 路徑需 240 次）。回歸同時要求每格每次仍取得來源，以及損壞／撤銷時清圖。仍會重建格位控制項與複製／雜湊 PNG；不是全面繪製或載入效能完成的宣告。

參照：
- https://docs.unity3d.com/2021.3/Documentation/ScriptReference/TextureFormat.DXT1.html
- https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression

尚缺：實際官方圖片正向驗收、頭像材質／遮罩、SpriteAtlas 表情、小地圖與全 Python 介面對齊。本批只做合成／loopback，不連正式服，不改 HasVisualAssets=false；恢復量仍未知。

8.0.53 local verification: 174 focused image checks passed; Desktop Release build zero warnings/errors, native UI 254 checks / 32 screenshots, offline presentation+inspector 81, public consumer and Python repository/release 15 passed. Full Core and exact-head CI are recorded on PR #79 separately. No official live-format acceptance is claimed.
