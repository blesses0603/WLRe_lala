# LaLa PC：官方 CDN 為唯一資源來源（B-only）

## 目標

玩家不必安裝官方遊戲；LaLa 只向官方來源取得所需檔案，在玩家電腦建立與驗證快取。GitHub 原始碼庫與公開 Release 不得重新分發官方 Bundle、貼圖或衍生遊戲資料表。

此方案依賴官方伺服器的可用性與允許的存取方式。公眾可下載不等於取得了重新散布或無限制自動下載的授權；正式開啟大量 Bundle 同步前須先確認相關規範。

## 已完成：第 1 階段「版本資訊」

沿用 `wlre.services.official_version` 已有的網址白名單、TLS、容量上限、尾端逗號解析及版本閘門。不重寫或放寬已驗證的官方版本取得流程：

1. `https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat`
2. `{DataVer}/ResourcesPC/AssetBundle/DataPackage.version`
3. `{DataVer}/ResourcesPC/AssetBundle/MainPackage.version`

新增 `wlre.services.official_resource_sync`，無需安裝官方 EXE／Unity `_Data` 即可比較當前與上一次觀測的完整 Package 版本。僅保存 `%LOCALAPPDATA%/WLRE_LaLa/official_sync/pc_versions.json` 等效的 per-user 路徑中一個小型版本資訊快照。

```
python -m tools.check_official_sync
python -m tools.check_official_sync --save
```

預設只查詢、輸出；加上 `--save` 只原子寫入版本快照。該快照不表示玩家已下載 Manifest／Bundle，`assets_ready` 永遠為 false，不會更動 LaLa 的發行版相容性基準、不繞過登入版本閘門、不複製遊戲檔案。

## 已完成：第 1.5 階段「單一 Bundle 的安全下載元件」

對已由獨立可信流程驗證的 YooAsset 2.2.5 Manifest，新增 
`wlre.services.official_bundle_download`：

- 從 Manifest 的 BundleName（output_name_style=1）組合使用者觀測的 `wlreftp.chinesegamer.net/.../ResourcesPC/AssetBundle/{BundleName}` 路徑；不接受任意網址、路徑穿越或跨網域轉址。
- 單一 HTTPS 下載受檔案長度上限限制；串流驗證 Manifest 提供的檔案大小、MD5 FileHash 與 CRC32。全部通過後原子存入使用者電腦；下載中斷不留下可被當成完成的檔案。
- 已校驗的本機 Bundle 不重複下載。這項元件預設**不主動呼叫網路**；目前未接到 UI 或登入路徑。
- 2026-10-24 用使用者提供的 DataPackage 1275 Manifest，確認 `datapackage_data_v.bundle` 為 4,695 bytes、FileHash `5bf5ead224fd61bbd8fc72af64b46864`、FileCRC `a64f27a7`。尚未取得遠端實際內容並完成網路端到端校驗。
- `wlreftpsrc.chinesegamer.net` 是使用者另行提供的候選資源主機；在確定回應及官方路由前，**不自動設為下載來源**。

## 已完成：官方 Manifest 網址驗證與驗證後本機快取元件

2026-10-24 對 `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/` 做唯讀查詢，證實官方不使用帶版本號的 Manifest 檔名，而使用固定名稱：

| Package | Manifest | `.hash`（CRC32 little-endian 編碼） | SHA-256（與使用者 1275 ZIP 一致） |
| --- | --- | --- | --- |
| DataPackage | `DataPackage.bytes`，16,830 bytes | `dcace626` | `8af6b9374d2e31e5bda4d82d2ec4be6b3a673e9188a522eb2c1b110e68c51dee` |
| MainPackage | `MainPackage.bytes`，2,564,950 bytes | `b4e21f83` | `65da10fab29b8ce96247a18e611ee0ba3c5c3bc5cb71a42c4e177001a8c4ba49` |

完整 URL 使用：`{DataVer}/ResourcesPC/AssetBundle/{Package}.bytes` 及同名 `.hash`。官方目錄頁僅作為發現路徑的證據，**程式不需要抓取、解析或大量掃描目錄 HTML**。

`wlre.services.official_manifest_sync` 已實作：

- 從經驗證的版本快照取得 `{DataVer}`、`{Package}` 與完整版本識別碼；只存取官方固定 HTTPS 網址、拒絕轉址、施加 8 MiB 資料上限。
- 每次先取得 `.hash`，以 `zlib.crc32(bytes).to_bytes(4, 'little').hex()` 比對；再由 YooAsset 2.2.5 全量解析器驗證內嵌 Package 名稱、版本與輸出格式，確認成功才原子寫入使用者電腦的私有快取。
- 已快取版本仍會向官方讀取 `.hash`；不一致就重取 Manifest。回傳完整索引供後續 Bundle 依賴分析，不會因此將 `assets_ready` 改為 true。
- 全量解析器位於 **Draft PR #53**；該分支尚未合併前，預設解析會明確拒絕（不以未驗證位元資料挑選 Bundle）。測試可注入合成解析器。
- 不提交 `.bytes`、`.bundle` 或遊戲內容的全量索引到 GitHub。

## 已完成：官方 LuaScriptPathList 唯讀差異索引

2026-10-24 唯讀取得官方 `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/LuaScripts/LuaScriptPathList.txt`，確認由相對路徑、分隔符 `|` 及 32 位 MD5 構成，實際解析 **866** 筆。這是 Lua 資源清單，並非 YooAsset Manifest。

`wlre.services.official_lua_index` 對路徑及 MD5 嚴格驗證，阻止重複、跨目錄及過大資料；僅比對檔名雜湊是否新增／修改／移除，沒有下載或執行 Lua 程式碼。小型私有快取放在使用者資料目錄，未提交官方腳本到 GitHub。

```
python -m tools.check_official_lua
python -m tools.check_official_lua --save
```

同樣僅提供觀測結果：某個 Lua 的 MD5 改變不能直接推論 LaLa 網路封包已相容；仍需人工或自動回歸驗證。

## 尚未完成：不能宣稱 B-only 已經能完整登入／導航

- **第 2 階段：整合全量 Manifest 解析器與差異報告。** 遠端 `.bytes`／`.hash` 已證實，須待 Draft PR #53 合併並正式將完整索引、依賴圖與差異判斷接入同步協調器。
- **第 3 階段：必要 Bundle 的遠端驗證。** 已有單 Bundle 的嚴格下載元件，仍須確認實際 Bundle 回應與 Manifest 校驗一致。對照依賴關係後才能挑選必要檔案；增量下載佇列、全域流量／磁碟配額、重試及暫停尚未實作。僅於玩家本機快取，不上傳 GitHub。
- **第 4 階段：Unity 內建資源與功能相容驗收。** 確認 `resources.assets`、`unity default resources` 等遊戲內建資源是否另有官方來源；缺少 `12910` Mesh 等關鍵內容時，不得宣稱導航完成。
- **第 5 階段：端到端驗收及安全遷移。** 在沒有官方遊戲安裝與既有 LaLa 資料的乾淨 Windows 環境測試。確認資源服務成功後，遷移所有 UI/服務讀取路徑並停止發版打包素材，再由維護者審核刪除舊素材與清理 Git 歷史。

## 驗收原則

無官方主程式並不等於沒有必要遊戲資料。沒有驗證來源、缺少 Package、離線首次執行、伺服器異常或完整性不符時，必須回報明確狀態；不得靜默回退 1262、猜路徑、跳過登入保護或將版本一致當作協定功能已驗證。
