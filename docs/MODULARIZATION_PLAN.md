# LaLa 電腦版：依功能建資料夾與舊離線資源遷移規劃（v0.6.1）

> 2026-10-25。以已合併 PR #56 的 main（v0.6.1 開發版）為基準。**PR #57 已從規劃延伸為分階段實作：P1a 第一批抽離協力準備／領獎與房間人數顯示，第二批新增協力專屬分頁、抽離共用房間創／入／退對話框並補上回歸測試；其餘模組尚未完成。未刪除資源、未提升版本號。** 以下路徑是實作提案，不代表已存在。使用者已回報「剛測試的功能都正常」，但未列出逐功能、環境與 Log，未測流程仍需驗收。

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
      rooms.py                      # ✅ 協力人數顯示、創房人數輸入與驗證、付費確認欄位
      rewards.py                    # 寶箱／獎勵 UI 狀態（不自行認定領獎成功）
    dungeon/                        # 一般副本
      __init__.py
      panel.py
      buttons.py
      rooms.py
      details.py
    minimap/                        # 小地圖專屬
      __init__.py
      panel.py                      # 小地圖容器
      buttons.py                    # 地圖上的操作按鈕
      map_view.py                   # 地圖繪製、投影、選取
      navigation_ui.py              # 導航／自動導航的 UI 協調
    npc/                            # NPC 對話、互動、商店視窗
      __init__.py
      panel.py
      dialogue.py
      shop.py
      buttons.py
    portals/                        # 傳送點與條件（與小地圖顯示分開）
      __init__.py
      panel.py
      buttons.py
  ui/
    instance_ui.py                  # 舊匯入相容層，保留兩種模式的共用 UI
    instance_room_dialogs.py        # ✅ 共用創房／加入／離開對話框及防重複點擊
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
- [x] P1a 第二批以 `features/cooperative/panel.py` 提供協力分頁入口，`features/cooperative/rooms.py` 負責協力人數核驗與費用確認欄位；建立／加入／離開房間的兩模式共用對話框搬到 `ui/instance_room_dialogs.py`，不複製一般副本程式；新增單元與 Tk GUI 回歸測試（等待本批 CI 驗證）。
- [ ] P1a 協力剩餘畫面繪製與房間狀態渲染拆分、正式服 E2E；`instance_catalog_1262.json` 仍供協力與一般副本共用，尚無等價已核准替代來源，不可移除。
- [ ] P1b～P5 實際搬遷、逐功能替代／清理及全域 `REQUIRED_RESOURCES` 檢核（尚未完成）。
- [ ] 全功能正式服 E2E、乾淨安裝、正式安裝包／Release 驗收（尚未宣稱完成）。

**接下來：** 核對第二批 CI，再於 PR #57 拆分 P1a 其餘協力狀態渲染與畫面元件，進行專屬回歸及舊資源來源盤點。P1b 一般副本仍獨立驗收。
