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

## 已完成：官方 LuaScriptPathList 唯讀差異索引

2026-10-24 唯讀取得官方 `https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/LuaScripts/LuaScriptPathList.txt`，確認由相對路徑、分隔符 `|` 及 32 位 MD5 構成，實際解析 **866** 筆。這是 Lua 資源清單，並非 YooAsset Manifest。

`wlre.services.official_lua_index` 對路徑及 MD5 嚴格驗證，阻止重複、跨目錄及過大資料；僅比對檔名雜湊是否新增／修改／移除，沒有下載或執行 Lua 程式碼。小型私有快取放在使用者資料目錄，未提交官方腳本到 GitHub。

```
python -m tools.check_official_lua
python -m tools.check_official_lua --save
```

同樣僅提供觀測結果：某個 Lua 的 MD5 改變不能直接推論 LaLa 網路封包已相容；仍需人工或自動回歸驗證。

## 尚未完成：不能宣稱 B-only 已經能完整登入／導航

- **第 2 階段：Manifest 遠端路徑實證。** 必須從官方遊戲的實際 HTTPS 請求確認兩包 Manifest `.bytes`／`.hash` URL。僅憑版本號及本機壓縮檔名稱猜測的幾種 URL 均回傳 HTTP 404。不可對未驗證路徑進行大量猜測／掃描。
- **第 3 階段：必要 Bundle 的完整 URL 與實際遠端驗證。** 已有單 Bundle 的嚴格下載元件，但尚須確認官方回應與 Manifest 校驗一致。對照依賴關係後才能挑選必要檔案；增量下載佇列、全域流量／磁碟配額、重試及暫停尚未實作。僅於玩家本機快取，不上傳 GitHub。
- **第 4 階段：Unity 內建資源與功能相容驗收。** 確認 `resources.assets`、`unity default resources` 等遊戲內建資源是否另有官方來源；缺少 `12910` Mesh 等關鍵內容時，不得宣稱導航完成。
- **第 5 階段：端到端驗收及安全遷移。** 在沒有官方遊戲安裝與既有 LaLa 資料的乾淨 Windows 環境測試。確認資源服務成功後，遷移所有 UI/服務讀取路徑並停止發版打包素材，再由維護者審核刪除舊素材與清理 Git 歷史。

## 驗收原則

無官方主程式並不等於沒有必要遊戲資料。沒有驗證來源、缺少 Package、離線首次執行、伺服器異常或完整性不符時，必須回報明確狀態；不得靜默回退 1262、猜路徑、跳過登入保護或將版本一致當作協定功能已驗證。
