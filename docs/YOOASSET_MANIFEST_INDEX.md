# LaLa YooAsset 2.2.5 Manifest 索引解析器

此工具以官方 YooAsset 2.2.x Manifest `2.2.5` 格式為基準，在私人環境解析 `DataPackage` 與 `MainPackage` 的 `.bytes`／`.hash`，輸出完整 Asset / Bundle 索引及新舊版本差異。

## 主要功能

1. 讀取 ZIP／RAR5 的 Manifest 封裝，不將官方原始檔解包到工作目錄。
2. 驗證 `.hash` 對應的 CRC32、包裹名稱、內嵌版本、欄位長度、Bundle ID 與相依關係。
3. 解析 Asset 地址、路徑、GUID、標籤、對應 Bundle，以及 Bundle Hash、CRC、大小、依賴清單。
4. 以 Bundle 名稱與 Hash / 依賴名稱比對新增、修改、刪除；避免 Bundle ID 重新排序造成誤判。
5. 估計受異動 Bundle 及相依關係影響的 Asset 範圍。
6. 拒絕將完整索引輸出至任何 Git 工作樹內，降低誤傳到公開 GitHub 的風險。

## 執行方式

在存放原始資源的**私人電腦／環境**，從專案根目錄執行：

```bash
python -m tools.resources.lala_manifest_full_index \
  --old-data /private/DataPackage_1262.rar \
  --old-main /private/MainPackage_1262.rar \
  --new-data /private/DataPackage_1275.zip \
  --new-main /private/MainPackage_1275.zip \
  --output-dir /tmp/lala-manifest-private
```

輸出四份 `*_full_index.json`、一份 `difference.json` 和一份 `difference.md`。這些檔案含官方 AssetPath / Bundle 名稱，請只保存在私人儲存位置。

單純做封裝檔案層級比較：

```bash
python -m tools.resources.lala_manifest_compare \
  --old-data /private/DataPackage_1262.rar \
  --old-main /private/MainPackage_1262.rar \
  --new-data /private/DataPackage_1275.zip \
  --new-main /private/MainPackage_1275.zip
```

上述路徑為示例，不是現有檔案的實際位置。Linux 的 RAR5 讀取需要 `libarchive`；Windows 可先在本機將 RAR 裡的兩個 Manifest 檔案改封裝為 ZIP。ZIP 只需 Python 標準函式庫。

## 測試

```bash
python -m unittest -v tests.test_yooasset_manifest_compare tests.test_yooasset_manifest_full_index
```

測試使用合成的最小化 Manifest，不需要官方遊戲資源，也不會產生完整官方索引。

## 與已合併的官方 CDN 同步服務串接

PR #55 的 `wlre.services.official_manifest_sync` 已取得經驗證的官方
`{Package}.hash`／`{Package}.bytes`，並在完整索引解析前阻止未驗證的
Manifest 被用來挑選 Bundle。本 PR 將匯入路徑接到
`tools.resources.lala_manifest_full_index.parse_manifest`。

```bash
python -m tools.check_official_manifests
python -m tools.check_official_manifests --package DataPackage
```

上述指令先查官方 DataVer 及兩包 `.version`，再驗證完整 Manifest
與個人使用者快取。畫面只輸出版本、雜湊、Asset 數與 Bundle 數，
不輸出完整資產路徑。使用合成 YooAsset 2.2.5 二進位資料的整合測試
涵蓋 Manifest → 索引 → 單筆 Bundle 驗證／快取，無官方素材也無網路請求。

## 安全界線及後續

- **這次 GitHub PR 只加入 Python 程式、測試、文件**。不要提交官方 Bundle、RAR、ZIP、完整 JSON 索引或擷取素材。
- 舊的 ZIP／RAR 解析工具只處理私人本機檔；新的
  `tools.check_official_manifests` 會依請求下載兩份官方 Manifest
  至使用者私有快取，但**不下載全部 Bundle**，也不修改 LaLa 相容性鎖。
  不應據此宣稱 1275 遊戲登入／導航已驗證。
- 新版若不再使用 `2.2.5` Manifest 格式會安全失敗，須更新解析器並重新驗證。
- 官方 `DataVer` 三階段版本偵測沿用現有
  `wlre.services.official_resource_sync.observe_official_versions`，
  不另外實作第二套版本來源。正式更新排程、下載配額與權限仍未完成。
- 專案現有的資源 ZIP 可能已追蹤在公開 Git 歷史；`.gitignore` 或本工具的私人輸出保護**無法清除已公開的歷史資料**。如需清理，必須單獨規劃與核准，以免破壞應用程式對圖示、小地圖、導航資源的依賴。

YooAsset 格式參考：[tuyoogame/YooAsset 2.2.10](https://github.com/tuyoogame/YooAsset/tree/2.2.10) `DeserializeManifestOperation` 與 `BufferReader`。
