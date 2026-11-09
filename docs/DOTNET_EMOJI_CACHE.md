> v8.0.71 最新接線與驗證界線見 [正式表情工廠](DOTNET_EMOJI_PRODUCTION.md)。以下保留各批實作與當時驗證紀錄。

# ver 8.0.68 表情 SQLite 與撤銷接線

## 已實作

`EmojiPngStore` 使用獨立 `core_emojis_v1.sqlite3`，兩張精確 schema 的表儲存首幀 PNG 與全部 token 列（含 hidden／共享首幀）。寫入在單一 transaction 內替換整批；回讀使用新的唯讀連線。兩次都從 producer 重新建立完整 `EmojiPixelBatch`，比對來源與整批指紋、逐圖輸入／像素／PNG SHA、完整 PNG bytes、尺寸及 token 的 id／mark／icon／text_id／visible／frame。額外或缺失列、異型欄位、額外 schema／trigger 拒絕。

沿用逐圖 1 MiB／整批 8 MiB PNG 上限與既有 SQLite 清理／回滾／提交結果標記；重新驗證與取消在 commit admission 檢查。已提交後最終來源重查失敗仍回報 Committed，但不發布。唯讀刷新不建立缺檔、不修復損壞快取；開始刷新先撤銷舊 publication。

owner 只在全流程重查與清理完成後發布；唯讀 PNG 需精確 owner-issued activation、當前 publication 及同一帳號快照，資料是私有複本。撤銷不能收回呼叫者已複製的 bytes，因此 bytes 本身沒有來源准入或發送權限。公開 `AccountRuntime.TryReadEmojiImage` 保留同樣的目前帳號檢查。

## 目前接線界線

只有 `EmojiRuntimeBatch.ForOfflineTests` 及離線 owner hook。**production 沒有完整來源工廠，不會產生或讀取此快取，不會啟用表情。** 候選／readback 的 `HasVerifiedProvenance` 仍為 false；離線 owner 不能 activate。生命週期正向測試使用明示 white-box publication，證明撤銷規則，不證明官方來源。

桌面登入與版本確認視窗列出「來源待驗證，尚不寫入」的表情快取路徑，結果列出獨立 EmojiStorageOutcome。`Purpose`／`Writes` 仍只描述 production 現有的 inventory／物品／頭像寫入。**表情網格、圖片實際顯示、文字插入與聊天發送尚未接線。** 沒有宣稱繪製效能改善。

## 驗證與剩餘工作

自有 fixture 覆蓋完整共享／hidden 映射、新連線重建、私有副本、資料庫竄改／自洽偽造 PNG、取消、來源漂移、rollback、缺檔唯讀、損壞不修復、精確 activation、帳號快照替換、invalidate／dispose／取消刷新撤銷。公開 consumer、Desktop build／離線與原生 UI、Python 回歸及完整 Core 結果以 PR 精確提交記錄為準。

本批不重試已逾時官方端點，沒有新官方下載或真實帳密／遊戲 TCP。仍需可信正式閉包定位與逐圖依賴、正式 62 首幀完整正向驗收、production 工廠及顯示接線、小地圖。既有來源、版本、雜湊及容量限制不放寬；`HasVisualAssets=false`，一般操作 Held。

本機最終驗證：Core.Tests 強制重建零警告／錯誤，完整 Core **45,767** 通過（新增 **31** 項快取／owner 案例）；公開 consumer、Python **18**、Desktop Release 零警告／錯誤、離線 **81**、原生 UI **198** 加頭像 **13**、catalog **10**／資源確認 **6**／登入 loopback **11** 通過，未產生截圖。原生 UI 首次 Unix display 不可用，改用同一雲端 Xvfb 的本機 TCP display 後通過；不涉及使用者電腦或外部遊戲連線。精確提交 CI 另記於 PR。
