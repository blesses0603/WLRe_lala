# 第十二階段：官方表情資料庫與兩端 UI

只在本機，未推送或合併。`emoji_catalog.json`、`emoji_images.zip` 已從兩端種子 active／BLOB、來源清單及必要打包清單移除，並列為 retired；種子剩 10 項，大小 68,431,872 bytes。既有使用者 DB 的歷史資料不刪除，也不作預設 fallback。

## 來源與版本化儲存

沿用第十一階段驗證的 YooAsset 相依語意。EmojiData_C 只接受完整 round-trip 核對的 SHA-256 `b21c48d487d83463332157e1d56af0a258f26cecf2e906ca518526badcd5a75b`，嚴格檢查 count、長度及欄位。未知指紋拒絕，不猜新版格式。桌面 parser 已加入 diagnosed／來源稽核註冊；Android 保留相同嚴格檢查及錯誤狀態，沒有宣稱移植桌面診斷模組。

同步時 EmojiData 列入既有核心剩餘預算的 optional table，排在原有 optional tables 後，不搶占原功能優先序。表情圖集使用獨立上限 32 MiB／8 Bundle，禁止超額／非整數參數；sync=False 不下載。導航限制未更動。Main 精確資產為 `Assets/ResourcesBuild/Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2`，全部相依 Bundle 必須存在並通過校驗、UnityFS header 及大小限制。

使用 UnityPy Sprite 解碼取原圖集的 `_1` 首幀，保留原有靜態表情呈現。依當次已驗證表格做全量 join，缺少或重複首幀、非 SpriteAtlas、尺寸超過 512、單張 PNG 超過 1 MiB、全部 PNG 超過 8 MiB 都拒絕匯入；不替換 SC 圖集或其他表情。

`official_sync/derived_catalogs/official_emoji.sqlite3` 沿用已測試的 normalized_resources schema 1，feature `emoji`／schema `emoji-known-sprite-v1`，以完整 catalog identity 分版。原始表格及全部圖集 Bundle bytes 以 SHA-256 保存，單一交易存入 entries 與 PNG 的 base64 表示、PNG／RGBA 摘要。用既有有界 codec 儲存二進位表示，不新增資料庫 migration 或覆寫未知 schema。

每次讀取快照前仍驗證官方來源；SQLite 衍生內容損壞可從完全相同的已驗證原始資料重建並保留損壞歷史。解析／缺圖失敗保留 raw 及失敗記錄，不發布半套快照。匯入期間再驗證 Bundle；同 identity 來源變更、raw 損壞、未知 schema 拒絕。圖像與表格一起載入 Runtime，UI 不組合不同版本。公開 PNG 讀取再檢查摘要、PNG 格式、尺寸與像素摘要。

## 桌面與 Android

桌面 EmojiImages 改讀當次 Runtime 的 DB 快照；冷啟動或失敗時保持文字 token。來源 identity 或同 identity 的 catalog 物件更新都清除 image cache。ChatPanel 每秒檢查來源變化，重繪既有聊天及關閉舊 picker；cleanup 取消 timer，草稿不變。

Android emoji_entries／emoji_texture／prefetch 改用同一來源，保留有界 texture cache，版本更新清除舊表情。聊天 refresh 會更新快捷表情、重繪訊息並關閉舊 picker。冷啟動 picker 明示官方表情尚未就緒，文字聊天及草稿保留。沒有透過舊 ZIP 補圖。

## 真實來源驗證

兩端對官方 1.3.23、catalog key `b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6` 完成公共 Runtime／DB 讀取：62 entries、62 張首幀，各 PNG 解碼後 RGBA SHA-256 全部等於第十一階段獨立解碼的 246-Sprite 圖集對應首幀。已移除種子後 Android 再驗證成功。使用既有已驗證官方快取，前後版本仍查核；沒有登入遊戲、發送封包或手機實機驗收。

## 測試結果與限制

- 桌面完整回歸 1,720 項通過、略過 166；之後補入 UI 生命週期與預算測試，相關 206 項通過（略過 1），實際 Tk 兩項通過。
- Android 隔離完整回歸跑完 180 個檔案：初跑 3 檔失敗。兩檔是新 UI helper 缺少 local import，修正後聊天相關 32 項通過；獨立 Emoji UI 測試未先建立 Kivy Window 導致程序崩潰，補上測試初始化後兩項獨立實際 UI 測試通過。沒有將這輪全套初跑宣稱為零失敗。
- Android 最終官方同步／Runtime／DB 相關 147 項通過。兩端新增 DB 測試包括冷啟動、copy isolation、未知來源保留、缺圖／重複／超尺寸原子拒絕、同 identity 來源變更、衍生損壞重建及歷史保存、匯入期間來源變動、未知 DB schema、PNG 損壞拒絕、下載預算不能繞過。
- 實際兩端 UI 測試覆蓋 cold→ready→同 key 內容更新→失效、texture/image 清除、picker 關閉、快捷表情刷新與草稿保留。測試圖片為合成純色，未把官方圖像或表格放進 Git。
- 桌面 repository audit 通過。未執行本階段遠端 CI、APK、手機或正式服驗收；Android 通用 repository audit 的既有版本表示限制未改。

## 剩餘 10 項

`stage_coordinates.json`、`graph_origins.json`、`navigation_data.zip`；`item_icon_map.json`、`item_icon_coverage.json`、`item_icons.zip`；`item_stackable.json`、`alchemy_catalog.json`、`combat_catalog.json`、`normal_attack_data.json`。具體證據缺口見第十、十一階段。導航樣本 88 Bundle／830,825,656 bytes 的超額限制維持，未放寬。官方 UI PNG／程式圖示仍另需分類，不在這 10 項內。
