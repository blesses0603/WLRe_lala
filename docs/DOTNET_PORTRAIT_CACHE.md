# ver 8.0.59 頭像 PNG／SQLite 整批回讀

## 已完成範圍

`PortraitPngStore` 是內部離線儲存層，承接有序、完整的 `PortraitCachePlan` 與候選重建 callback。生產組合將需以 `PortraitBatch.Process` 及當前來源重查建立此 callback；本批尚未把它安裝到 production。

- 頭像 base／mask 固定 256×256 RGBA，使用 filter None／zlib 壓縮 PNG。既有物品 Sprite PNG 使用原 stored DEFLATE 編碼，黃金向量保持不變。
- 每張 PNG 不超過 512 KiB、整批 base／mask 合計不超過 64 MiB，沿用 Python 的容量限制；索引至多 1024 組。完整正式索引由既有固定來源計畫提供 778 組。
- 寫入移交一個關閉且獨占的 DbConnection；工作在背景執行，SQLite 交易內逐張核對 key、來源、候選指紋、PNG hash 與實際 bytes。完整索引、行數及獨立累加的批次摘要均符合才重查來源並提交。
- 回讀使用新的連線與重新建立的候選，重新編碼比較完整 PNG bytes，不解壓縮資料庫提供的不可信 PNG。不信任資料庫自報的 hash；額外行、欄位型別、過大 blob、外加 schema／trigger 均拒絕。
- 寫入不留存整批 RGBA；回讀只持有有界 PNG 及深複製配色。回傳索引不可變，PNG／配色存取回傳副本。初始取消仍等待連線清理；半批失敗、來源改變及提交前取消回滾，既有資料保持完整。未知提交結果沿用既有 store outcome metadata，不能自動重試。

壓縮器版本可能改變同像素的 PNG bytes。升級 runtime 後舊快取若不再與重新編碼相符會被拒絕，需要經既有確認流程重建；不放寬比較、不默默採用舊資料。

## 驗證與限制

18 項新合成測試涵蓋完整獨立回讀、PNG 結構／CRC／解碼像素、資料及 hash 竄改、缺行／額外行／錯誤型別、半批及錯誤摘要、來源改變／取消回滾、64 MiB 容量拒絕與深複製。與既有 Sprite PNG／SQLite 共 40 項專項通過。這些測試不替換官方 pins，也不代表正式三檔資料或全 778 張頭像已驗收。

`HasVerifiedProvenance=false`。尚缺 production 組合、可撤銷發布、角色映射、配色與 Avalonia 顯示；表情 SpriteAtlas、小地圖及完整 Python UI 仍未完成。`HasVisualAssets=false`、一般遊戲操作 Held，未連正式服或使用真帳密。本批沒有新的 FPS／載入秒數改善宣告。
