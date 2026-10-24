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

## 尚未完成：不能宣稱 B-only 已經能完整登入／導航

- **第 2 階段：Manifest 遠端路徑實證。** 必須從官方遊戲的實際 HTTPS 請求確認兩包 Manifest `.bytes`／`.hash` URL。僅憑版本號及本機壓縮檔名稱猜測的幾種 URL 均回傳 HTTP 404。不可對未驗證路徑進行大量猜測／掃描。
- **第 3 階段：必要 Bundle 的正確 URL。** 對照 Manifest 的 Bundle hash、尺寸、依賴，僅下載必需部分。限定官方網域與明確路徑，限制並行數、總傳輸量、磁碟用量，串流校驗後原子切換；只在玩家本機快取，不上傳 GitHub。
- **第 4 階段：Unity 內建資源與功能相容驗收。** 確認 `resources.assets`、`unity default resources` 等遊戲內建資源是否另有官方來源；缺少 `12910` Mesh 等關鍵內容時，不得宣稱導航完成。
- **第 5 階段：端到端驗收及安全遷移。** 在沒有官方遊戲安裝與既有 LaLa 資料的乾淨 Windows 環境測試。確認資源服務成功後，遷移所有 UI/服務讀取路徑並停止發版打包素材，再由維護者審核刪除舊素材與清理 Git 歷史。

## 驗收原則

無官方主程式並不等於沒有必要遊戲資料。沒有驗證來源、缺少 Package、離線首次執行、伺服器異常或完整性不符時，必須回報明確狀態；不得靜默回退 1262、猜路徑、跳過登入保護或將版本一致當作協定功能已驗證。
