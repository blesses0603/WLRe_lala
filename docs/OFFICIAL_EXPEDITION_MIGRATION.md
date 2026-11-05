# 第四階段：遠征改用官方資料庫 Runtime

接續第二／三階段本機分支，未推送或合併。`expedition_catalog.json` 已從種子 active／BLOB 表移除並 VACUUM，清單與封裝驗證同步調整；剩餘 **21 項**。第三階段逐項盤點仍適用，但其中遠征項目由本文件更新狀態。

## 已完成

- 共用 `load_catalog()` 相容入口現在轉交 `load_active_catalog()`，讀取已由官方 Bundle 驗證並規範化入 SQLite 的 Runtime；不再以舊種子或使用者資料庫中的舊 bundled row 作為目前版本資料。未知／未完成來源明確拋錯。
- 原有已獨立驗證的 1275 官方來源路徑仍保留；它不是把缺失的目前版本靜默替換成 1262 種子。未更動登入、協定或封包相容性閘門。
- 桌面既有來源錯誤提示、更新 token 與清單重載沿用。Android 頁面改為相同入口，冷啟動顯示資料未同步；catalog token 改變時重讀資料、清除舊任務選擇與按鈕，不以相同 ID 誤用舊名稱或獎勵。
- 遠征設定／使用者方案不刪除，未自動啟動。既有 manager 在缺少正式 Runtime 時仍拒絕自動派遣。
- 測試中舊種子的筆數／固定名稱斷言改為合成輸入、來源隔離、拷貝隔離、時間計算、條件與獎勵容量驗證。正式資料驗證另以下述實檔測試記錄，不把合成資料稱為官方資料。

2026-11-05：再次驗證官方版本並以已校驗的 1296 Bundle 快取建立 Runtime，經新版公共入口讀回 **260 任務、10 等級、7,586 夥伴**；所有任務都有名稱。測試用 scoped injection 將該真實 Runtime 提供給公共入口，未啟用遊戲連線，`can_send_packets=False`。同批原始與規範結果由既有 SQLite 交易及來源指紋保存。

## 進一步查證格式缺口

已從 `https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.23/LuaScripts/LuaScriptPathList.txt` 取得正式路徑，逐一下載對應 `LuaScripts/Lua/Data/` 檔案，禁止轉址、限制每檔 2 MiB，MD5 與同次官方清單一致：

| 檔名 | Bytes | 官方清單 MD5 |
| --- | ---: | --- |
| NpcTalkData.lua | 1040 | dfbe859643fee054d7f6bea29ebdc0e6 |
| EmojiData.lua | 992 | 4faa81b8e4ecac86df4828a4a7d4f70b |
| ItemData.lua | 168416 | 91ef3a2adfa340d5bcc0c4ac28f3a4ca |
| SkillData.lua | 24016 | 15e84005358823279d671e2fa3abdd2b |
| SkillMotionData.lua | 7632 | 789f7150c6e7ca281e4905965ab516d7 |
| StageMapData.lua | 3808 | 4ed49254cc2ce8b01f6800a9312c4351 |

這六檔都不是有效 UTF-8，開頭也不是一般 Lua／LuaJIT bytecode 識別碼。這只證明尚未辨識的二進位封裝，**不能由此斷言是哪一種加密或壓縮**。程式庫及 tools 搜尋未找到相應解碼器；未猜測金鑰、格式或執行下載內容。原始檔與本機 audit 留在 `/workspace/validation/official-lua-1.3.23/`，未加入 Git 或安裝包。

因此 NpcTalk 群組、Emoji mapping、物品堆疊／鍊金及 Skill／SkillMotion 戰鬥語意仍需官方格式說明、已知且可核對的解碼實作，或另一個同版可讀來源。只有雜湊相符不足以建立欄位語意。

圖集與導航缺口依第三階段盤點：還需要目前版本 sprite 裁切／旋轉／item ID 對應的全量驗證、場景幾何的可重現解碼與投影比對；Manifest 路徑存在不能代替這些驗證。NPC Eve／Talk／Text 現有 parser 已可使用，剩餘舊 fallback 與初始 catalog 成組依賴尚待逐一移除。

未完成手機實機／APK、正式服登入或完整零離線資料驗收。發布仍須先推送桌面縮減種子的提交，再發布引用該提交的 Android seed lock；本階段不推送。

## 測試

桌面最終全套 1,673 項通過（略過 163）；DISPLAY 遠征相關 63 項、冷啟動／GUI 3 項通過。Android 隔離執行 171 個檔案，共 1,354 項通過（略過 4），本輪沒有失敗；166 個共用核心檔案核對通過。第二階段已知的 Android 通用 repository audit 版本寫法限制仍未處理，沒有宣稱該檢查通過。
