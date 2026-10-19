# 副本／協力副本建置紀錄（官方 1262）

## 第 01 階段：入口（PR #22 已合併）

- 主頁左側「副本」主分頁，內有「主要」、「協力」次分頁，未確認進入指令不會送出。

## 第 02 階段：靜態表解析

官方 Lua 原始碼可核對 **格式**，不等於已取得二進位表 **內容**。目前提供嚴格解析：

- `DungeonData_C`：副本 ID、類型、難度／分組、地圖 ID、NPC、16 格獎勵與加倍／特殊旗標。
- `CooperateEventData_C`：協力種類與描述 ID、場次、標記、四個指定夥伴與額外獎勵。
- `ScenesData_C`（由 `StageData:New` 解析）：場景文字 ID、最低等級、最少／最多人數、時間限制與房間數。

來源：上傳的 `WLRE_Lua_1262_Decoded_Analysis(1).zip` 中 `Lua/Data/{DungeonData,CooperateEventData,StageData,AwardData}.lua`。透過 `wlre.services.instance_catalog.catalog(dungeon, cooperative, scenes, names)` 提供已抽出的原始表位元組。對無法取得的表與文字不建立假資料，不自行推測名稱、開放狀態或獎勵。

## 後續實施準則

原版一般副本使用 C/S85；協力使用 C/S186。**封包格式核對、在測試模擬下正確收發**不等於已通過正式伺服器測試。涉及建立、加入、開始、領獎或付費操作時，必須以當前角色／隊伍／事件狀態及回覆為準，逾時不可盲目重送。

## 第 03 階段：S85 / S186 連線與唯讀房間列表

- 嚴格解碼兩種房間列表、成員、階段、倒數、協力獎勵狀態；未知子協定保持未實作，不推測封包。
- 手動按「更新房間清單」送出官方 C85-1 或 C186-17；不自動輪詢，戰鬥與事件中阻擋查詢。
- 房間建立、加入、離開、開始、副本進入、準備與領獎尚未開放，避免在正式服上誤操作。

## 第 04 階段：狀態與介面綁定

- State.instances 各自保存一般／協力的房間、成員、階段、計時與獎勵旗標。僅根據伺服器資料更新，不採本機樂觀加入／扣獎。
- 主要／協力次分頁呈現伺服器房間，未取得官方地圖文字時只顯示房間 ID。退出與角色登入重設狀態；不跨帳號沿用。
- 尚未實現建立房間、配對、指定寵物、通關自動化及獎勵領取；這些操作仍需官方流程與實服驗證。

## 第 05 階段：回歸與安全驗收

- 單元測試涵蓋 1262 三種二進位表解析、16 筆獎勵與四個指定夥伴、缺料／尾端長度拒絕。
- S85 與 S186 房間列表、建立／加入回覆、成員同步、退出、倒數、協力獎勵、非同步狀態安全邊界。
- GUI 測試驗證兩模式清單刷新與按鈕限制，沒有未經核對的建立、進入或領獎操作。
- Windows/Linux/macOS GitHub Actions 及 Nuitka 驗證結果以 PR 下最新工作流程為準，不宣稱實服端到端測試。

## 2026-10-19 已上傳 ManifestFiles 解析結果（1262）

使用者提供的 `DataPackage_1262.rar`（只含 16,830 位元組的 Manifest）與
`MainPackage_1262.rar`（只含 2,549,190 位元組的 Manifest）均可讀取，
**但均不含實際的 `BundleFiles/**/__data`**。因此目前無法產出官方副本名稱表。

1262 `Lua/Logic/Data.lua` 明確呼叫
`GameDataList["ScenesData_C"] = this.OnLoadSceneData`，而
`OnLoadSceneData` 逐筆呼叫 `StageData:New(binaryReader)`。
因此 **`ScenesData_C` 才是 `parse_stages` 的輸入**，並非 `StageData_C`。

| 正式資源 | Bundle | Manifest hash | 大小 |
| --- | --- | --- | ---: |
| `CooperateEventData_C` | `datapackage_data_c.bundle` | `e600b2b2ef3044fc5e5a7ff3641d1df8` | 4,732 |
| `DungeonData_C` / `DungeonRewardData_C` | `datapackage_data_d.bundle` | `014e88153786c77eaed00d04ec29f8a3` | 39,020 |
| `ScenesData_C` / `StageMapData_C` | `datapackage_data_s.bundle` | `b470fcf69d58da6ac1a7c899068b2bf4` | 428,919 |
| `TextData_C` / `TextData_SC_C` | `datapackage_data_t.bundle` | `277be57613f8b1306fc645c63835b2ee` | 3,619,162 |

上述 hash 來自 `DataPackage` 官方 Manifest 的 bundle 表，用以定位安裝路徑：
`<遊戲>_Data/yoo/DataPackage/BundleFiles/<hash前兩碼>/<hash>/__data`。
不應把 Manifest `.bytes` 當成表本身，也不應自行生成不存在的官方名稱。

## 副本七項開發清單

- [x] 01 完整官方繁體中文副本清單（已匯入 1262 官方文字、30 筆設定、24 個 ID；未經實服驗證的開放狀態仍不推定）
- [ ] 02 建立公開／私人房間（待正式服操作及 ACK 安全驗收）
- [ ] 03 加入或離開房間（目前已有唯讀房間／成員同步）
- [ ] 04 協力準備與指定夥伴（已有原始資料格式，尚未開放操作）
- [ ] 05 房主開始挑戰（尚未開放操作）
- [ ] 06 進入副本戰鬥（尚未開放操作，保留原有戰鬥與事件閘）
- [ ] 07 自動完成與領取獎勵（尚未實作，不可盲目重送或推測發獎）

這份清單以**可在正式伺服器實際使用且完成驗收**為勾選標準。

## 2026-10-19：四個 UnityFS Bundle 已成功解析（取代上方 Manifest 尚缺檔案的舊狀態）

使用者已補充完整 `WLRE_1262_Instance_Bundles.zip`，包含 `datapackage_data_{c,d,s,t}.bundle`。
已從實際 Bundle 內取出 `DungeonData_C`、`ScenesData_C`、`CooperateEventData_C`、`TextData_C`。

- 30 筆 DungeonData 設定，涵蓋 24 個獨立副本 ID：一般 26 筆、協力 3 筆、新式 1 筆。重複 ID 是原版不同難度變體，不可覆蓋。
- 1,336 筆 ScenesData；2 筆 CooperateEventData；39,901 筆官方繁體中文 TextData。
- 匯入共 178 筆非空獎勵格，保留原始 `[格位、kind、ID、數量]`，沒有擅自推斷領獎成功或機率。
- `wlre/resources/instance_catalog_1262.json` 提供可在 Nuitka 打包的固定版本資料。僅把 30 筆與副本有關的場景名稱和條件納入執行時資源，避免包入非必要全遊戲中文文字。
- `wlre/services/instance_browser.py` 讀取並驗證這份資料；「主要」和「協力」頁面各有獨立的官方靜態清單與伺服器房間清單。真正的可加入狀態仍以 S85／S186 回覆為準。
- **協力活動名稱必須取自 CooperateEventData.TextID**，因此 ID 27「黑薔薇之影」、ID 28「萬聖鬼武來襲」不能錯用共用地圖的「麥哲倫艦隊」。
- 已補單元與 GUI 測試；必須再以 GitHub Actions 驗證跨平台及 Nuitka 包含資源檔。

更新至此：七項清單僅第 01 項（正式靜態清單）勾選，創房、入房、協力準備、房主開始、實際副本戰鬥與自動領獎仍未實作。

## 房間操作封包預備層（仍未對正式伺服器開放）

來源 `Dungeon.lua`、`CooperateEventManger.lua`：

- 一般 C85-3 公開創房：`mapId:u16,public=1:u8,password=0:u16,recruit=0:u8`；私人：`mapId:u16,public=0:u8,password:u16`。
- 協力 C186-1：`playerCount:u8,kind:u8,npcIdx:u8,public:u8,password:u32,recruit=0:u8`；活動 27／28 使用從原始資料核對的 `npcIdx=1/2`，協力對戰 21 使用 0。
- 一般 C85-5 加入：`roomId:u16,SN:u16[,privatePassword:u16]`；協力 C186-4：`roomId:u16,password:u32`；離開 C85-6 或 C186-5 為空內容。
- `wlre/network/instance_actions.py` 僅提供封包 builder 與嚴格參數驗證，**未加入手動指令路由、不會自行送出**。創房及加入可能涉及點數／門票消耗，需完成 S85／S186 回覆、角色狀態、超時不重送與費用確認後才解鎖 UI。此時七項清單的 02／03 項仍不得標為完成。

## 第 02 項：公開／私人房間建立（2026-10-19）

已接入 `instance_create` 手動指令、公開／私人創房 UI 與密碼／協力人數參數、網路執行緒 pending、20 秒逾時、不自動重送、連線中斷凍結及 S85/S186 伺服器回覆判斷。

- 一般副本使用 C85-3，S85-2 為受理／拒絕，S85-5（房主 ID、房間 ID）才確認入房。主分頁已可選擇官方 1262 副本及建立公開／私人房間。
- 協力對戰 ID 21 使用 C186-1，S186-2 code 9 代表成功且扣點，S186-3 帶建立與房主資訊才確認房間。送出前必須明確確認可能的門票／點數消耗。
- 依據 1262 官方 `CooperateEventData_C`，協力活動 ID 27／28 的 `follower_ids` 全是 0、`follower_reward.kind` 為 0，因此原版 `UIDungeonPartner.TryOpen()` 不會開啟指定夥伴提示，目前兩個活動也開放創房。未來若官方資料更新為有額外夥伴獎勵，將要求使用者明確確認夥伴條件。
- 私人房間必須填入 4 位 ASCII 數字密碼，不把密碼寫入 State、diagnostics、通知或存檔。
- 未確認結果時禁止再創房；20 秒逾時後直到重新登入都不允許重試。這是防止雙重扣點的保守設計。
- **CI/封包測試通過不代表已在正式伺服器實測創房成功**；實服端到端測試仍須由帳號使用者驗收。
