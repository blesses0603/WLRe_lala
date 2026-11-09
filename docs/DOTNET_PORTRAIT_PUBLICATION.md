# ver 8.0.60 頭像來源組合與可撤銷發布

## Production 接線

`OfflineBundleRuntimePreparation` 僅在固定 Data 1.3.23／Main 1296_2026_11_04_13_36_07_72 嘗試頭像來源投影，沿用既有共用下載／保留額度、官方 HTTPS、manifest checksums 與三檔 SHA256 pins。完整 `PortraitBatch.Process` 驗證解碼後才保留來源供 Bundle 快取；未知版本不請求頭像，未知格式或可選來源失敗讓頭像保持缺席。取消、過期 attempt、最後來源漂移仍拒絕整體發布。

`PortraitRuntimeBatch` 保存不可變來源與完整初始摘要。SQLite 寫入與新唯讀連線回讀各自重新解碼，摘要必須與初始批次一致。這會執行三次完整處理，不宣稱載入速度改善；先保留獨立驗證，後續優化需有測量與同等驗證。

`ResourceRuntimeOwner` 使用固定 `official_sync/derived_catalogs/core_portraits_v1.sqlite3`，寫入前重查遠端來源、commit 前重查 attempt；回讀及清理後再確認來源，最後才發布。遠端來源與本機資料庫不能原子提交，之後失敗可能留下已提交的快取，不能宣稱已回滾。`PortraitStorageOutcome` 獨立回報 NotAttempted／NotCommitted／Committed／Unknown，傳遞到登入前與帳號資源結果。多個資料庫不是單一交易，不自動重試不明寫入。

唯讀刷新不建立缺少的頭像快取；已有快取損壞時拒絕本次發布，不修復。下載確認與 disclosure 明示新增路徑及 SQLite journal 寫入。這不是新增遊戲網路或帳密權限。

## 撤銷與讀取

只有 owner 發出的精確 activation 能讀取目前 publication 的頭像 key；自行構造、舊 activation、未知 key 都不能取得資料。停止、刷新或釋放撤銷。帳號 binding 保留前後快照檢查。已回傳的不可變圖片資料不會被撤銷抹除，後續顯示必須每次重新檢查當前 binding，不能把快取引用當權限。

尚未新增公開角色頭像 API，也沒有完成角色到 key／配色映射、Avalonia 解碼與顯示。`HasVisualAssets=false`、一般遊戲操作 Held；表情、小地圖及完整 Python 介面仍待完成。

## 測試證據界線

新增合成 owner 流程涵蓋三次重建、唯讀缺檔、非審查版本不取得、離線 owner 不准入、commit 前撤銷、commit 後來源漂移、解碼漂移、損壞快取不修復及 invalidate／dispose／refresh 撤銷。沿用既有明示 white-box admission fixture 只測生命週期；離線 hook 不替換正式 pins，也不提供到 production factory 的注入參數。

**未完成正式三檔來源正向驗收或完整 778 張實際圖片回讀；合成測試不是正式驗收。** 未連正式服、未使用真帳密，未宣稱 GPU／手機畫面一致。
