# LaLa 電腦版：依功能建資料夾與舊離線資源遷移規劃（v0.6.1）

> 2026-10-25。以已合併 PR #56 的 main（v0.6.1 開發版）為基準。**PR #57 已從規劃延伸為分階段實作：P1a 三批已拆出協力操作、房間與獎勵狀態，P1b 已拆出一般副本專屬操作／結算及共用官方目錄 UI；P2 已拆出小地圖畫布／點選／場景與路徑同步，P3 第一批已拆出 NPC／傳點 UI，P4 第一批已抽離共用視窗控制；P5 保持權威資源驗證服務不動。以上均不代表正式服 E2E 完成。未刪除資源、未提升版本號。** 以下路徑是實作提案，不代表已存在。使用者已回報「剛測試的功能都正常」，但未列出逐功能、環境與 Log，未測流程仍需驗收。

## 一、經確認的主要需求

1. **功能優先（feature-first）**：協力、一般副本、小地圖、NPC 等各有**獨立資料夾**，該功能的畫面、按鈕、資料呈現、流程協調放在同一個位置，而不是只把大型檔案任意切碎。
2. **同一階段同步處理舊離線資料**：整理某功能時，同時盤點該功能所依賴的 1262 靜態檔、手動 ZIP／舊圖像與導航資料，改接**官方驗證來源**或其他經審核的可信來源；替代品未達等效，**保留既有檔案與功能**，記錄阻塞原因。不另開「最後全部刪除」的大清理階段。
3. **使用者免手動準備正式遊戲資料包**：PR #56 已支援從官方 `.version`、`.bytes`、`.hash` 和所需 Bundle 取得、校驗並建立 1275 Runtime；不代表遊戲運作不需要任何**本機驗證快取**或 UI 靜態圖片。沒有來源／驗證失敗，絕不回退 1262 假裝相容。
4. **不重複底層共用程式**：真正多功能共用的 TCP、封包、State、資源校驗、保留量、圖片快取等仍由 `network/`、`core/`、共用 `services/`、`storage/` 所有；功能資料夾透過清楚的介面使用它們。不要把一套 TCP 協定複製到每個功能。
5. **先維持相容，再搬遷**：`wlre/ui/instance_ui.py`、`wlre/ui/home_map.py` 等公開匯入路徑保留輕量相容入口；逐一更新內部匯入與 tests，確認後才能考慮移除舊入口。

## 二、預定資料夾配置（部分已開始實作）

```text
wlre/
  features/                         # 同一功能：UI、按鈕、協調與唯讀模型
    cooperative/                    # 協力，非一般副本
      __init__.py
      panel.py                      # ✅ 協力專屬頁面入口（仍繼承共用 InstanceModePage）
      buttons.py                    # ✅ 已抽出協力準備／領獎／取消／自動領獎操作
      rooms.py                      # ✅ 協力人數／準備狀態顯示、創房人數與費用確認
      rewards.py                    # ✅ 領獎條件、寶箱狀態與保留欄位安全驗證
      widgets.py                    # ✅ 協力準備與獎勵按鈕畫面（維持原視覺順序）
    dungeon/                        # 一般副本
      __init__.py
      panel.py                      # ✅ 一般副本獨立頁面入口（繼承相容 UI）
      buttons.py                    # ✅ 房主開始／手動入場與正常副本專屬按鈕
      rooms.py                      # ✅ 依 StageData 最低人數及 S85-4 人數驗證
      readiness.py                  # ✅ 開始／進場 UI 條件與跨模式待確認鎖定
      details.py                    # ✅ S85 副本目標、Boss／積分／結算顯示
    minimap/                        # 小地圖專屬
      __init__.py
      buttons.py                    # ✅ 單擊選取／雙擊手動移動事件
      map_view.py                   # ✅ 地圖畫布、投影與座標渲染
      navigation_ui.py              # ✅ 地圖切換／路徑狀態及失效處理
    npc/                            # NPC 對話、互動、商店視窗
      __init__.py
      panel.py                      # ✅ NPC 選取、手動對話、唯讀商店及選項 UI（不支援自動交易）
    portals/                        # 傳送點與條件（與小地圖顯示分開）
      __init__.py
      panel.py                      # ✅ 傳點選取／手動觸發 UI 與安全拒絕顯示
  ui/
    instance_ui.py                  # 舊匯入相容層，保留兩種模式的共用 UI
    instance_room_dialogs.py        # ✅ 共用創房／加入／離開對話框及防重複點擊
    instance_room_list.py           # ✅ 共用房間列表、刷新與選取保持
    instance_catalog_ui.py          # ✅ 共用官方副本目錄、創房按鈕與選取
    feature_navigation.py           # ✅ 跨功能視窗開關、聚焦與單例管理
    home_map.py                     # 舊 HomeMap 相容層，委託 minimap/npc/portals
    gui.py                          # App 組裝／Tk 主執行緒入口
  core/                             # 跨功能 State／事件／排程／所有權
  network/                          # 共用 socket、封包、命令／狀態同步
  services/                         # 真正共用的服務、資源驗證、權威規則
  storage/                          # 設定與私人快取路徑
```

**上述檔名不是拆檔配額。** 先查現有相同職責檔案再定案；`features/*` 僅放各自特有功能，跨功能的邏輯不複製。真正的自動導航演算法、座標驗證、移動回覆確認仍由 `services/world/` 共用，不誤當成 UI 邏輯。目錄搬遷不等於允許用未知來源放行網路操作。

## 三、逐功能工作階段：分類與舊資源遷移**同時進行**

依使用者新決定，在 **PR #57** 以小範圍 commit 逐階段實作，模組各自執行對應測試，全部完成再執行完整跨平台 CI；階段中的「資源替代／清理」仍是同一階段的驗收項，不是最後另外一次全刪。若替代來源不足，完成安全搬遷並將舊檔列為**待替代／不可刪**，不得冒險硬刪。

| 階段 | 功能分類與主要原始碼 | 同階段檢查的舊離線／內建來源 | 完成條件 |
|---|---|---|---|
| P1a 協力 | `instance_ui.py` 協力部分 → `features/cooperative/`；沿用 `instance_room_flow.py` 等權威規則 | `instance_catalog_1262.json` 中協力資料及其所有讀取處 | 協力房間、準備、獎勵狀態等價；1262 資料只有在全部必要來源經驗證替代後才可取消引用 |
| P1b 一般副本 | `instance_ui.py` 一般副本部分 → `features/dungeon/` | 同一 `instance_catalog_1262.json` 的副本用途；**與 P1a 共用，不可先刪** | 副本詳細資料、創／入／退房、開始與人數限制保留；共享資料所有使用者都完成遷移後才評估移除 |
| P2 小地圖 | `home_map.py` 地圖繪製／按鈕／導航 UI → `features/minimap/` | `smallmaps.zip`、`navigation_data.zip`、`map_names.json`、`stage_coordinates.json` | 地圖圖像、座標與自動導航有經核對的替代來源；缺少則**保留舊檔**，不得用未驗證的官方資料填補 |
| P3 NPC／傳點 | `home_map.py` NPC／傳點相關 UI → `features/npc/`、`features/portals/` | `npc_event_index_1262.json.gz`、`npc_interact_1262.json.gz`、`npc_talk_1262.json.gz`、`npc_text_1262.json.gz`、`npc_battle_talk_1262.json.gz`、`portals.json` | 舊 1262 來源不再參與正式 1275 功能；NPC 文字、商店、傳送在對應驗證完成前仍維持安全拒絕與既有 UI |
| P4 主程式與會話 | `ui/gui.py`、`network/client.py` 只拆主控／跨功能協調，不為「搬到同資料夾」複製共用層 | 全程審核剩餘 `REQUIRED_RESOURCES`、打包清單與匯入；依實際所屬功能回歸 P1–P3 處理 | Tk／背景工作、State 單寫入者、網路事件與所有公開入口均不變 |
| P5 資源驗證服務整理（後置） | 官方更新／版本閘門／Bundle 下載仍是共用基礎設施，依責任細分，**不是額外刪除資源階段** | 檢查各功能已處理的資源清單、來源收據與封裝契約，不刪未替代項 | 有完整受影響流程 E2E 與安全回歸後才重整服務，不放寬 fail-closed 規則 |

### 每個階段都使用同一套遷移步驟

1. **盤點：** 找出該功能 UI、按鈕、業務規則、網路命令、靜態資料的全部匯入／讀取位置，建立「舊路徑 → 新責任歸屬」對照；確認共用消費者。
2. **抽取：** 先補現行行為測試；保留原公開類別、方法與指令契約，在功能資料夾逐步實作，原路徑作相容委託。
3. **替代：** 優先採用 PR #56 的已審核 1275 Bundle Runtime；地圖圖像、導航 mesh 等**未證實有等價正式來源**者不憑空宣稱可從官方下載。官方來源只依 `.version`＋`.bytes`＋`.hash` 與需要的 Bundle 審核。
4. **驗證：** 比對資料項目、Schema／SHA／MD5／CRC、權威伺服器回覆與主要 UI；執行三平台 CI 及對應 Windows／正式服 E2E。區分「資料已下載」「資料可解析」「安全允許操作」。
5. **移除（有條件）：** 只有**所有消費者歸零**、等價來源可從乾淨安裝重建、打包與跨平台測試、必要實機驗收通過，才從 `REQUIRED_RESOURCES`、打包清單與舊檔同步移除；任何一項缺乏證據，保留檔案且標註原因。**不刪使用者私人快取、帳密設定或官方遊戲安裝內容。**

### 功能、來源與安全保留矩陣（2026-10-25 程式碼查核）

| 功能 | UI／服務消費者 | 現行舊資源 | 處理結論 |
|---|---|---|---|
| 協力／一般副本 | `ui/instance_catalog_ui.py` → `services/instance_browser.py` | `instance_catalog_1262.json` | 共用資料，未證實有同 Schema／完整記錄的 1275 替代；**保留** |
| 小地圖／位置標記 | `features/minimap/map_view.py`、`ui/home_map.py` → `services/world/smallmaps.py` | `smallmaps.zip`、`map_names.json`、`stage_coordinates.json` | 尚無可重建的等價來源／投影核對；**保留** |
| 導航路線顯示 | `features/minimap/navigation_ui.py` → `services/world/navigation.py` | `navigation_data.zip` | 路由只作已審核資料參考；無法證明 1275 網格等價；**保留** |
| 傳送點 | `features/portals/panel.py` → `services/world/portals.py`／`portal_policy.py`／`portal_links_1275.py` | `portals.json`、1275 `Eve`／`StageMapData_C`／`EveDoorLinks` | 1275 官方門事件座標與所在場景可顯示；同版三表的場景／索引／座標／目的地全數一致才顯示真實目標名稱並解鎖**使用者二次確認的一次性 C20-8 試傳**，角色場景只由伺服器確認；來源不完整時仍停用、無 1262 門 ID 回退，尚須正式服驗收 |
| NPC／唯讀商店 | `features/npc/panel.py` → `services/world/npc_catalog.py`、`npc_talk.py`、`npc_shop.py` | `npc_*_1262.json.gz` 各索引 | 1275 NPC 索引由已驗證 Runtime 提供的部分，不代表對話／選項／交易全面相容；**舊檔仍屬封裝要求，禁止未經證實移除** |

上述每個資源目前仍在 `resource_manifest.REQUIRED_RESOURCES`。清單只做程式碼來源盤點，不代表已完成官方 1275 與 1262 等價性、使用者正式服流程或封裝乾淨安裝驗收。

### 已知事實與不可誤解之處

- `runtime_1275.active_runtime()` 已有經正式固定驗證的舊 ZIP 或**已驗證官方 Bundle Runtime** 兩條來源；因此兩份手動 ZIP **不是永遠都必須事先安裝**。
- 但目前 `wlre/resource_manifest.py` 的 `REQUIRED_RESOURCES` **仍列有** 1262 NPC 索引、`instance_catalog_1262.json`、`smallmaps.zip`、`navigation_data.zip`、`portals.json` 等。沒有等價替代時直接刪除會讓 self-test／封裝或功能失敗。
- 官方 1275 新版本不能因快取存在、候選 Schema 相容或離線測試通過，就跳過新的線上版本確認；未知版本必須拒絕登入。個人設定檔／本機官方驗證快取是必要的持久化資料，不屬於「應刪掉的舊離線資料」。
- 不將完整遊戲原始 Bundle 放入公開 GitHub，不引入未驗證來源；資源收據保持版本隔離，更新採原子切換，故障不覆寫可用資料。

## 四、原行為與安全驗收界線

- **協力／副本：** `InstancePanel`、`InstanceModePage` 的舊匯入與 callback 保持可用；創房、入房、退房、待命、開始、入場、獎勵狀態只接受伺服器證據；`pending`、`uncertain` 不盲目重送、不得跨房間領獎。
- **小地圖／NPC：** `HomeMap` 繼續提供原回呼；圖像顯示、地圖點擊、導航座標、NPC 商店與對話、傳送拒絕條件逐項比較；來源缺失時安全降級、不把 1262 事件編號冒充 1275。
- **網路與狀態：** UI 不接觸 TCP，Tk 只在 UI 執行緒；一個網路工作者改寫 State，先 `State.apply` 後 `SessionLogic.receive`；共享資源保留／互斥不改；登出與重登不能套用過期回覆。
- **CI 與實機：** 每張實作 PR 都要 Windows／Ubuntu／macOS 完整自動化、原始碼／打包資源完整性測試與 Windows GUI；實際遊戲協定與功能需另由使用者 E2E。macOS 沒有顯示器時 skipped 的 GUI 測試不等於通過。
- **版本：** 本文件 PR 維持 **v0.6.1**；各後續實作 PR 依最新 main 個別評估版本及 `[vX.Y.Z] 繁體中文標題`，不重複升版。PR 不經授權不合併 main，也不建 Release／Tag。

## 五、本規劃 PR 的完成界線

- [x] 明確採納**功能資料夾分類與同階段離線資源遷移**。
- [x] 已記錄 2026-10-25 使用者回報的已測功能正常。
- [x] 將原本較粗的「副本／協力」與「地圖／NPC」再拆為協力／一般副本／小地圖／NPC 傳送等不同功能所有權。
- [ ] 建立每張實作 PR 的精確 import dependency graph 和逐功能測試矩陣（開工前完成）。
- [x] P1a 首批將協力準備、免費領獎／取消、自動免費領獎 UI 操作移至 `wlre/features/cooperative/buttons.py`，協力房間人數顯示移至 `rooms.py`；原 `InstanceModePage` 以 Mixin 保留舊匯入及方法契約，新增 `tests/test_feature_cooperative.py`。
- [x] P1a 寶箱補強（2026-10-26）：1275 `S23-5` 背包快照直接保存伺服器明示的格位與數量，不再經 1262 `item_stackable.json` 重新配位；缺索引、重複或容量不符仍標不可靠。`S23-6` 新物品未知堆疊規則只容許明示空格的一件入袋，其餘安全拒絕。協力免費寶箱沿用至少四格的保守政策，並在 UI 精確顯示 S23-5 未同步、空位不足、保留物品或房間準備結果不明。準備操作逾時保留原房間及目標，**只有晚到的同房同狀態 S186-3** 才能解除不確定鎖。新增快照、回覆與 UI 回歸測試；尚無正式服領獎與 1275 滿袋政策 E2E，不得宣稱已發獎或可解除限制。
- [x] P1a 第二批以 `features/cooperative/panel.py` 提供協力分頁入口，`features/cooperative/rooms.py` 負責協力人數核驗與費用確認欄位；建立／加入／離開房間的兩模式共用對話框搬到 `ui/instance_room_dialogs.py`，不複製一般副本程式；新增單元與 Tk GUI 回歸測試（等待本批 CI 驗證）。
- [x] P1a 第三批抽出 `features/cooperative/widgets.py` 協力按鈕、`rewards.py` 領獎狀態、`rooms.py` 準備狀態顯示，以及 `ui/instance_room_list.py` 共用房間列表（避免兩種模式程式重複）；新增狀態與 Tk GUI 回歸測試（CI 待確認）。
- [ ] P1a 正式服 E2E 及 1275 協力清單替代來源驗證。現行 `wlre/services/instance_browser.py` 仍讀取內建 `instance_catalog_1262.json`，且一般副本共用；目前未取得可靠的等價 1275 副本清單，故**必須保留、不可冒險移除**。
- [x] P1b 第一批：一般副本獨立畫面入口、開始／進場動作與按鈕、最低人數／房主與場景校驗、伺服器副本目標／結算資訊移至 `features/dungeon/`；保留 `InstanceModePage`、`room_headcount_status`、`instance_details` 舊 API，補上非 GUI 與 Tk GUI 回歸測試（CI 待確認）。
- [x] P1b 第二批：共同副本官方清單的 Treeview／選取／建立條件搬至 `ui/instance_catalog_ui.py`；兩種模式仍共用，同步新增 API 和狀態回歸測試。CI #854 曾因新檔縮排錯誤失敗，已於後續提交修復；修正後 CI #855 三平台成功。
- [x] P2 第一批：地圖畫布、單擊／雙擊、場景載入及導航狀態更新移至 `features/minimap/`，保留 `HomeMap` 公開介面與導航安全限制；相關回歸測試已納入 #855。
- [x] P3 第一批：NPC 對話、唯讀商店、選項、傳點與手動觸發 UI 抽至 `features/npc/` 和 `features/portals/`；舊 `HomeMap` 仍組裝地圖／怪物／NPC／傳點清單，未改變伺服器操作。新增安全／介面回歸測試（CI 待驗證）。
- [x] P4 第一批：`App.open_feature/hide_feature/hide_all_features/open_instances/hide_instances/open_resources/open_attributes` 移至 `ui/feature_navigation.py`，只移動 Tk 視窗生命週期，不動 Worker、TCP、State 或事件佇列；新增權限與視窗單例相容測試（CI 待驗證）。
- [x] P4 第二批：`App._poll_once()` 移至 `ui/session_event_coordinator.py`，`App` 以 Mixin 保持原方法（`App._poll_once()`）供舊 GUI 與測試使用；Tk `poll()` 排程、版本閘門、網路 Worker、封包、State.apply 順序不更動。新增 `tests/test_feature_session_event_coordinator.py` 檢驗事件/快照順序、會話結束復原、健康事件不覆寫遊戲 State。跨平台 CI 與真實登入/斷線 E2E 分開回報。
- [x] P5 安全回歸底線：新增 `tests/test_feature_resource_safety.py`，驗證 1275 已驗證 NPC 索引不回退舊 NPC 事件資料、沒有可信傳送目的地時不啟用傳點、原必要封裝資源尚未遭刪除（最新 CI 待確認）。
- [x] P3 傳點顯示修復（針對場景 12170 畫面問題）：1275 `active_runtime().doors` 原本只統計總數並返回空清單，現將已驗證的門事件索引／本地座標呈現為 `1275 門事件` 唯讀標記，修復 `portal_policy.allowed_rows` 誤隱藏全部未知目的地、新增重新載入預登入空快取及 1275 專屬門事件核對視窗。仍不核發 C20-8 換圖權限；此批已補單元／Tk UI 測試，CI 待驗證，正式伺服器換圖仍需目的地與事件實測。
- [x] P3 傳點所在場景名稱匹配：從已驗證官方 1275 `ScenesData_C.name_id` 與 `TextData_C` 建立場景 ID→中文名稱，正式 ZIP／官方 Bundle 兩路 Runtime 共同輸出 `scene_names`；1275 傳點清單、選取狀態及小地圖標題共用此來源。缺正式中文名稱時只顯示「場景 ID」，不借用舊版 1262 名稱或把所在場景誤認為傳送目的地。目的地仍未知、換圖停用；新增場景名稱對應及安全回歸測試（CI 待驗證）。
- [ ] P4 其餘會話事件協調及 P5 服務責任核查，仍須正式服 E2E、官方 1275 副本／地圖等價性與完整跨平台打包驗收。
- [ ] 全功能正式服 E2E、乾淨安裝、正式安裝包／Release 驗收（尚未宣稱完成）。

### 小地圖傳送問題修復範圍（PR #57，待 CI／正式服驗收）

- **地圖／入口名稱所有權修正**：小地圖標題只從當前場景 ID 取得已驗證中文名稱；若 1275 尚缺該名稱，僅顯示「場景 ID」，絕不從門事件推斷或使用 1262 舊名稱。傳點列表僅顯示「傳點 #索引（目的地待確認）」或三表交叉核對後的**前往目的地**，不能把「門事件」當成地圖名。
- **1275 同版來源交叉核對**：新增 `portal_links_1275.py`，嚴格解析 `StageMapData_C`（門事件標記）、`EveDoorLinks`（目的地）、`Eve.NewDoor`（來源門 index／XY），要求場景、索引、來源座標與目的地場景全部吻合；對應資料從原本 Release-pinned Manifest／已驗證 Bundle 或經驗證正式 ZIP 載入，不能用 1262 路線猜測。
- **安全單次試傳**：只有完成上述匹配且目的地存在可預覽地圖時，讓使用者在明確確認視窗後送出既有 C20-8；仍由 `PortalTravel` 拒絕戰鬥／事件阻塞、同一請求重複送出，並等候真實位置同步，拒絕逾時重送與本機假造換圖成功。
- **安全降級**：需要資源未下載、二進位布局不相容、門事件座標不一致、目的地不存在或無可用小地圖時，一律顯示「傳點／目的地待確認」及可核對資訊但不允許送封包。**目前 PR #57 尚為 Draft、未併入 main**，一般 v0.6.1 主線執行檔無法驗證本 PR 的 UI 改動；本次補上地圖標題與傳點選取互不覆寫的回歸測試。
- **驗收限制**：目前只有本地程式碼與模擬資料可檢查這個流程。尚無本次 1275 正式伺服器真實 C20-8 換圖成功截圖／Log，不得將「手動可嘗試」宣稱為「已完成實機傳送」。

### 2026-10-25 新手海灘（11016）傳點只顯示編號的根因與修復

- **實際畫面已證明 UI 名稱去重生效**：小地圖標題為「新手海灘(11016)」，傳點清單為「傳點 #1／#2（目的地待確認）」，因此不能再把問題單純歸因於使用者沒有執行 PR 測試版；未核對成功的是傳點實際名稱／目的地資料。
- **程式根因**：原本 `StageMapData_C` 與 `EveDoorLinks` 一起進行交叉比對才建立 `portal_destinations`，丟掉 `StageMapData_C.NameID`，即使官方有明確的傳點文字名稱，也因目的地無法核對而全部回退「傳點 #N」。
- **這次修正**：以與同版 `TextData_C` 相符的 `StageMapData_C.NameID` 獨立建立 `portal_names[(scene_id, EvtID)]`，並在正式 ZIP 和驗證過的官方 Bundle 兩種 Runtime 都分開載入；UI 優先呈現官方名稱，其次才顯示已三表核對的目的地名稱，最後才顯示「傳點 #N（官方名稱未取得）」。**名稱已確認不等於可傳送**，目的地與觸發仍沿用安全閘門。
- **可觀測性**：除了詳細狀態文字，**首頁精簡小地圖**原本使用 `show_status=False`，導致診斷實際被隱藏；已在傳點列表下方新增常駐簡短提示，顯示 StageMap 資料未載入、格式無效或有多少傳點缺 NameID。完整資料仍寫入 `portal_metadata_status`，不把 1262 名稱冒充 1275。
- **證據限制**：使用者目前提供的 `DataPackage_1275.zip` 及 `MainPackage_1275.zip` 內容是官方 Manifest 索引與 hash，沒有 `StageMapData_C`／`EveDoorLinks` TextAsset 原始資料，因此**尚不能斷言場景 11016 兩個傳點的實際官方文字**。需在 PR 分支版本完成官方附加 Bundle 同步後，以實際狀態欄與正式伺服器操作驗收。

### 2026-10-25 傳點座標點位偏移：來源座標系統與投影修復

- **已確認程式根因**：PR #57 原本把 `Eve.NewDoor` 通用事件的 `x/y` 當成小地圖 packet XY，直接傳入 `Projection.packet_to_pixel()`。使用者回報圖示位置與實際入口不符，根據提供的 1262 Lua `UIMain._SetPortalPosition()`，一般傳點真正採用 `EveDoorLinksData.GetDoorDataByIndex()` 的 `mapPosition`，且 `PosXRatio/PosYRatio` 要先依場景套用。兩類座標不能混用。
- **已修改流程**：`parse_stages` 保留 `ScenesData_C` 官方 XY 比例與地圖尺寸／位移；`verified_portal_positions()` 使用經驗證 `StageMapData_C` 的 (SceneID, EvtID) 身分、`EveDoorLinks` 的原始格座標，再依 SceneData 的 X/Y ratio 轉換成可交給小地圖的 packet XY。`Portals` 僅在有獨立位置驗證時設定 `coordinate_valid`；原始 NewDoor 格座標另存 `event_grid_x/event_grid_y` 供診斷，不提供 UI 畫點、導航或換圖。
- **防止錯位與誤觸**：`portal_map_pixel` 統一檢查 [0, 1024] 地圖界線、來源座標與正式 1275 幾何是否匹配目前圖片投影；畫點、清單選點與滑鼠點擊使用同一安全判定，且手動試傳按鈕不可繞過不符的來源地圖校驗。缺可信座標時清單照樣顯示、地圖不顯示假標記，精簡版小地圖會提示「點位待官方座標換算」。
- **回歸測試**：`tests/test_portal_coordinates_1275.py` 使用合成官方 Schema 模擬「EventData grid=(42,64)、門連線=(200,300)、倍率=(3,2)、正確 packet=(600,600)」以及沒有來源、倍率無效、點位越界、地圖位移不相容時的安全拒絕。先前只以原始事件座標為正確位置的測試已更正。
- **限制與下一步實測**：1275 最新 `EveDoorLinks` 真實資產與場景 11016／12170 實際官方傳點位置，尚未獲取可驗證的 TextAsset 內容；CI 驗證的是契約、資料換算及 GUI 安全行為，**不等於正式遊戲圖示位置完全驗收**。使用 PR 分支實測時優先核對入口是否出現在對應地形位置，並比對官方遊戲傳點圖示。

### 2026-10-25 新手海灘（11016）官方傳點名稱仍缺失：實際資料載入問題

- **使用者實測證據**：場景 11016 的兩筆門事件列出 #1/#2，但傳點名稱都提示官方名稱未取得，稽核表的 X/Y 均為無效。這證明 Eve.NewDoor 基礎事件存在；**不證明** StageMapData_C 或 EveDoorLinks 已正確解包，不能再將之歸因於 UI 沒更新。
- **官方原始檔**：使用者提供的 1275 DataPackage Manifest 確有 `Assets/ResourcesBuild/Data/StageMapData_C.bytes` 與 `.../EveDoorLinks.bytes` 的 AssetPath 索引，但 ZIP 只有 Manifest .bytes/.hash，沒有 TextAsset 本體；需要另從官方 Bundle 下載、hash 驗證後解出內容。
- **已修正的根因**：(1) 1275 Runtime 原本優先使用有核心 NPC／物品資料的正式 ZIP，即使其缺少傳點資料也會遮蔽後續已驗證 Bundle；現在可優先採用同版且 StageMapData 已就緒的完整 Bundle Runtime。(2) 附加 Bundle 原本下載額度共用，若任一份下載受阻就兩者都得不到；現在優先且獨立下載 StageMapData_C 名稱表，再嘗試 EveDoorLinks。(3) 附加資產未快取、hash 不符、Unity TextAsset 解包失敗原本被靜默略過；現在會在首頁小地圖及稽核視窗以安全、不包含路徑的訊息明確顯示原因。
- **官方名稱與目的地**：StageMap Kind 2（普通傳點）、Kind 3（隱藏傳點）的有效 NameID 都能讀取；NameID 缺失時，可從同版 StageMap 的 SceneID/EvtID 對應 EveDoorLinks 目的地，以已核對 ScenesData＋TextData 的場景中文名做**唯讀參考**。不同座標系統的 XY 不作相等比對來決定名稱；*只有名稱*不會授權 C20-8 或直接換圖。
- **完整性與驗收**：新增正式 ZIP／Bundle 來源優先順序、缺資源診斷、Kind 3 名稱及唯讀目的地回退回歸測試。仍缺真正的 1275 場景 11016 StageMapData_C/EveDoorLinks TextAsset，故無法聲稱已取得兩個實際官方傳送點的中文名稱；必須以 PR 分支重新啟動並完成官方 Bundle 同步後，核對小地圖提示與兩筆實際名稱。

### 2026-10-25 跨版本傳點欄位辨識：1262 Lua 為契約參考，不沿用舊傳點實際值

- **來源可稽核**：由使用者上傳的 `WLRE_Lua_1262_Decoded_Analysis(1).zip` 讀取 `Lua/Data/StageMapData.lua`、`Lua/Data/EveDoorLinksData.lua`、`Lua/Logic/Data.lua` 和 `Lua/UI/Logic/UIMain.lua`；前者明定 `SceneID(u16), Kind(u8), CrossSceneNumber(u16), EvtID(u32), PositionX(u16), PositionY(u16), NameID(u32), Sorting(u8)`，總計每筆 18 bytes，表頭 Int32 筆數。
- **三份來源角色分離**：`StageMapData_C` Kind=2/3 分別為一般與隱藏傳點，可用 `NameID` 對當版 `TextData_C`；`EveDoorLinks` 是 UTF-16LE 場景標頭與方括號連線文字；`DoorLinkData_C` 是 Int32 筆數 + 每筆 6 個 u16 (12 bytes) 的場景連線資料，它沒有 EveDoorLinks 的傳點事件索引，不可拿順序強行當作 EvtID。
- **跨版辨識器**：`wlre/services/world/portal_schema.py` 提供 `recognize_portal_source(table, verified_raw)`，在來源已完成官方 hash/Manifest 驗證後，以**完整記錄長度／欄位範圍／文字編碼**識別既有 Schema；回傳不包含猜測欄位、也不允許送封包的 JSON-friendly verdict。結構不符直接回傳 `layout_unrecognized`，不做任意位元組掃描、偏移猜測或套用 1262 的實際場景座標。
- **實際接線**：已將結構辨識接入經驗證的 1275 Bundle Runtime 與正式 ZIP 讀取流程，保留 `portal_schema_report`，只在舊版欄位相容時進行當版資料表的名稱／目的地唯讀解析；未知結構保留 NPC／製作等核心功能且在小地圖提供不相容診斷。
- **未來版本限制**：結構辨識**不等於**新版本來源已通過審核。`runtime_1275` 及 `sync_pinned_runtime_bundles` 仍對 1275 Manifest 使用已審核 SHA-256 固定版本；未來官方版本需要由官方更新流程先取得可信 Manifest、Bundle 與 TextAsset，再做格式辨識與完整相容性測試。任何新版資料不得因 Schema 長得相似就自動放行 C20-8／換圖。
- **測試**：`tests/test_portal_schema_1262_compat.py` 覆蓋三種 1262 schema、Kind 2／3 名稱、未知尾段、截斷、錯誤 endian、無效目的地與格式交叉誤判；`tests/test_bundle_runtime_1275.py` 新增正式 Runtime 保留結構辨識報告與未知表安全降級。新手海灘 11016 兩筆**實際**傳點名稱仍須取得官方 1275 TextAsset 才能驗收。

### 尚未能由 CI 單獨證明的正式驗收

- **Windows 正式遊戲／網路回覆：** 1275 版本閘門、官方 Bundle 校驗與登入；副本創／入／退、房主開始及進場；協力房間待命與免費領獎；NPC 手動互動／唯讀商店，傳點不合法目標拒絕，全部需記錄正式伺服器回覆與操作前後 State。
- **乾淨安裝／資源來源：** 在無私人快取的乾淨 Windows 環境確認安裝包、官方 Manifest／Bundle 的 hash 與相依清單；取得真正等價的 1275 小地圖、導航、NPC 對話及副本資料後，方可刪除 1262 資源／解除封裝依賴。
- **整合驗收：** 確認視窗開合／登入登出／斷線重連與背景事件不混用舊狀態；正式打包、跨平台測試及原版功能回歸需要真實運行紀錄。本 PR 只有連續 CI 證明的部分才可標記自動化通過，不宣稱正式伺服器測試成功。

**接下來：** P3／P4 新提交需通過 Windows／Ubuntu／macOS 三平台 CI；P5 必須先有官方驗證來源與乾淨安裝證據再調整資源契約。登入、NPC 商店、傳點、協力／副本及正式遊戲 E2E 尚未實測，不宣稱正式完成。
