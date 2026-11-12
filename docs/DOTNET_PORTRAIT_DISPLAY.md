# ver 8.0.62 桌面頭像背景渲染與顯示

## 實際接線

`AccountRuntime.TryGetPortrait` 只對 host 正在呈現的精確接收快照建立請求，依目前帳號／資源 binding 選取玩家或夥伴圖片。`PortraitRenderRequest` 不提供公開建構器，身分摘要含來源圖片指紋、角色、出戰 NPC、key 與配色。每次 currentness 檢查重新選取目前接收狀態並核對圖片引用、角色、出戰 NPC 及配色；單純 HP 變化不重繪，同角色換來源會重新准入。請求及輸出不授權登入或發送指令。

背景工作僅解碼 `PortraitPngStore` 已獨立核對且持有私有副本的 PNG；固定 256×256、RGBA8、filter None、IHDR／單 IDAT／IEND、CRC、512 KiB 壓縮輸入及精確解壓長度皆受限。套用既有 Python CPU 配色投影後輸出 PNG，工作前後檢查 currentness／取消。這不是開放任意外部 PNG 的匯入功能。

DesktopSession 的 reader 受目前 presentation 世代與快照引用檢查，登入資源流程接入，停止與換帳清除。Dashboard 的玩家／夥伴列使用 40×40 尺寸，未出戰夥伴隱藏待同步文字。每列至多一個背景渲染／Bitmap 解碼工作和一張顯示 Bitmap；相同身分重用，失敗身分暫不重試至輸入改變。換角立即清舊圖，舊 callback 即使不理會取消也不能與下一個工作並行或覆蓋新圖。每次更新及 200 ms 顯示 timer 重查 currentness，撤銷清圖；關閉先取消、清圖並等待工作釋放後才完成視窗關閉。

這採每列一張快取，尚非 Python 32 張 LRU。沒有宣稱 FPS 或載入秒數改善；原生測試以 RenderCount 驗證同身分刷新不新增渲染，以及非合作舊工作不擴大並行數。

## 測試與尚未完成範圍

Core 測試比較快取 PNG 解碼／渲染與直接 RGBA 演算法的完整像素，涵蓋私有副本、角色／配色／出戰識別、工作中撤銷、取消、CRC／幾何／截斷與容量。原生 UI 使用自有紅色像素測試真正 Bitmap 顯示、40 像素布局、同圖重用、撤銷清除、晚到工作、損壞圖拒絕及等待關閉。

**仍未以正式三檔／NPC 資料完成正向驗收，也未證明正式 778 張或 GPU／手機畫面一致。** 有條件的 production 接線不等於使用者已看到正式頭像；未通過來源 gate 時仍為占位狀態。表情 SpriteAtlas、小地圖與完整 Python 介面尚未完成，HasVisualAssets=false，一般操作 Held，未連正式服或使用真帳密。

## v8.0.61 CI 歷史

精確提交 `22ead0c2cda6dccbecc7256db2cd0cd7b7280082` 的 Windows／Linux Python 及 .NET、Android 成功。兩個 macOS 工作在 2026-11-09 16:46:43／44 UTC 等待 15 分鐘後取消，runner_id=0、無 steps。GitHub annotations 確認 hosted runner 多次未取得，另註記 macOS arm64 容量不足。Python run 42655676710、.NET run 42655676736 均為 failure，不能算 macOS 通過；未取消、重跑或升版來隱藏該紀錄。
