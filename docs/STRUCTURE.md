# 目錄與模組索引

對照基礎：`main` 的 `3f27368` 加本次功能協調與狀態所有權改善，應用版本 `0.5.0`。本索引描述目前目錄；完整的啟動、資料流、狀態所有權、帳號保存與改善順序，請先閱讀 [整體架構](ARCHITECTURE.md)。

## 根目錄

| 路徑 | 責任 |
|---|---|
| [WLRE_Client.py](../WLRE_Client.py) | 桌面／打包入口、資源自檢、GUI smoke test與啟動錯誤紀錄。 |
| `run_client.bat`／`run_client.command` | Windows／macOS 原始碼啟動。 |
| `run_navigation.bat` | 獨立導航工具。 |
| `build_nuitka.bat` | Windows 打包入口。 |
| `requirements-*.txt` | UI、Windows 建置與 macOS 建置依賴。 |
| `wlre/` | 執行期程式與內建資源。 |
| `tools/` | 建置／發佈／資源維護工具。 |
| `tests/` | unittest 測試。 |
| `docs/` | 架構、介面、協定與驗證說明。 |
| `.github/workflows/test.yml` | main／PR 的 Linux、Windows、macOS（Apple Silicon）測試與 GUI 冒煙檢查。 |
| `.github/workflows/release-windows.yml` | Windows 與 macOS 共用發版工作流程，檔名仍保留 windows。 |

## wlre：套件入口

| 模組 | 責任 |
|---|---|
| [__main__.py](../wlre/__main__.py) | 命令列解析與離線地圖／研究連線命令。 |
| [launcher.py](../wlre/launcher.py) | 原始碼啟動與圖像依賴環境準備。 |
| [paths.py](../wlre/paths.py) | 以套件位置定義 PROJECT_ROOT 與 RESOURCE_ROOT。 |
| [resource_manifest.py](../wlre/resource_manifest.py) | 必要資源清單、內容驗證與建置收錄來源。 |

## wlre/ui：介面、畫面模型與顯示協調

| 模組 | 責任 |
|---|---|
| [account_controller.py](../wlre/ui/account_controller.py) | 帳號偏好載入、儲存與成功後啟用。 |
| [attribute_points_ui.py](../wlre/ui/attribute_points_ui.py) | 角色五項能力配點視窗與確認流程。 |
| [auto_battle_ui.py](../wlre/ui/auto_battle_ui.py) | AI 設定入口、整體套用、匯入匯出，保留原本的編輯器公開介面。 |
| [auto_battle/model.py](../wlre/ui/auto_battle/model.py) | AI 規則草稿驗證、已確認特技及可用行動清單。 |
| [auto_battle/action_editor.py](../wlre/ui/auto_battle/action_editor.py) | 行動編輯、技能與物品選取、目標與條件。 |
| [auto_battle/rule_card.py](../wlre/ui/auto_battle/rule_card.py) | 各類 AI 規則卡片與操作控制項。 |
| [bag_grid.py](../wlre/ui/bag_grid.py) | 背包與唯讀儲物格狀介面、分頁規格與物品詳情模型。 |
| [battle_view.py](../wlre/ui/battle_view.py) | 戰場陣形、單位卡片、目標選擇與檢視。 |
| [button_art.py](../wlre/ui/button_art.py) | 原版按鈕切片縮放、視窗控制與設定／包包／回復圖示按鈕。 |
| [chat_emoji.py](../wlre/ui/chat_emoji.py) | 聊天表情圖像資源與解析。 |
| [chat_ui.py](../wlre/ui/chat_ui.py) | 聊天顯示、頻道、輸入與發話結果。 |
| [companion_ui.py](../wlre/ui/companion_ui.py) | 夥伴資料與出戰／休息操作。 |
| [connection_status.py](../wlre/ui/connection_status.py) | 將傳輸健康證據轉成連線狀態文字。 |
| [crafting_browser.py](../wlre/ui/crafting_browser.py) | 製作配方瀏覽、設備分類與配方詳情；保留舊版 ItemIcons 匯入相容性。 |
| [crafting/item_icons.py](../wlre/ui/crafting/item_icons.py) | 製作／背包共用的道具 ZIP 圖像快取與貼圖載入。 |
| [crafting/catalog_grid.py](../wlre/ui/crafting/catalog_grid.py) | 製作物品圖示格位建置、分類結果分頁與格位刷新。 |
| [crafting/recipe_detail.py](../wlre/ui/crafting/recipe_detail.py) | 配方資訊、材料表、批量控制與可製作狀態顯示。 |
| [crafting/queue_view.py](../wlre/ui/crafting/queue_view.py) | 製作排程視窗、控制指令與伺服器佇列進度顯示。 |
| [crafting_plan_ui.py](../wlre/ui/crafting_plan_ui.py) | 本機自訂製作清單與伺服器排程操作介面。 |
| [crafting_ui.py](../wlre/ui/crafting_ui.py) | 製作主分頁整合。 |
| [dashboard_builder.py](../wlre/ui/dashboard_builder.py) | 主頁分頁、面板與事件區的視窗建立。 |
| [dashboard_layout.py](../wlre/ui/dashboard_layout.py) | 主視窗標頭、左右工作區與固定地圖區幾何配置。 |
| [efficiency_ui.py](../wlre/ui/efficiency_ui.py) | 角色／夥伴經驗摘要、進度與三列效率表格。 |
| [event_queue.py](../wlre/ui/event_queue.py) | 有界顯示信箱、最新快照合併與舊顯示事件清理。 |
| [expedition_display.py](../wlre/ui/expedition_display.py) | 遠征任務名稱、耗時與獎勵的顯示格式。 |
| [expedition_ui.py](../wlre/ui/expedition_ui.py) | 遠征設定、帳號保存、清單與背景組隊預估。 |
| [function_icons.py](../wlre/ui/function_icons.py) | 主要分頁的原版圓形功能圖示。 |
| [gui.py](../wlre/ui/gui.py) | App 組裝、登入、背景工作、命令送入與畫面事件分派。 |
| [halo_button.py](../wlre/ui/halo_button.py) | 主頁功能開關的動態七彩啟用邊線。 |
| [home_map.py](../wlre/ui/home_map.py) | 主頁地圖、NPC／怪物清單與傳點操作。 |
| [layout.py](../wlre/ui/layout.py) | 共用標題與可捲動表格。 |
| [login_controller.py](../wlre/ui/login_controller.py) | 登入視窗、記住帳號、分流與角色選擇協調。 |
| [maintenance_ui.py](../wlre/ui/maintenance_ui.py) | 戰後修理／整理設定與即時背包選物視窗。 |
| [minimap.py](../wlre/ui/minimap.py) | 小地圖索引、圖像讀取與投影換算；含待下移的共用資料模型。 |
| [navigation_gui.py](../wlre/ui/navigation_gui.py) | 獨立地圖／導航檢視工具。 |
| [overview_ui.py](../wlre/ui/overview_ui.py) | 主頁卡片、狀態摘要與功能快捷操作。 |
| [party_guard_ui.py](../wlre/ui/party_guard_ui.py) | 必要隊員名單設定。 |
| [recovery_ui.py](../wlre/ui/recovery_ui.py) | HP／SP 補給順序、門檻、背包補品選擇。 |
| [resource_view.py](../wlre/ui/resource_view.py) | 實際背包、超空間袋與已確認特技對話框。 |
| [rounded_notebook.py](../wlre/ui/rounded_notebook.py) | 以實際按鈕組成的分頁列、選取狀態與鍵盤切換。 |
| [services_ui.py](../wlre/ui/services_ui.py) | 組隊與煉金操作面板。 |
| [session_bridge.py](../wlre/ui/session_bridge.py) | 綁定單次連線的工作執行緒回呼與顯示信箱。 |
| [theme.py](../wlre/ui/theme.py) | 視窗背景合成、標題列、按鈕貼圖與表格欄寬鎖定；保留共用主題入口。 |
| [theme_styles.py](../wlre/ui/theme_styles.py) | 統一註冊 ttk 字型、色彩、按鈕、表格及輸入框樣式，不處理背景裁切。 |
| [window_layout.py](../wlre/ui/window_layout.py) | 功能對話框的尺寸限制與置中。 |

## wlre/core：會話狀態與共通處理

| 模組 | 責任 |
|---|---|
| [activity.py](../wlre/core/activity.py) | 伺服器活動事件解碼與活動／移動限制狀態。 |
| [diagnostics.py](../wlre/core/diagnostics.py) | 每個程序的 UI 效能、連線及錯誤位置診斷與輪替日誌。 |
| [efficiency.py](../wlre/core/efficiency.py) | 經驗樣本、效率、升級進度與倒數預估。 |
| [event_log.py](../wlre/core/event_log.py) | 將處理事件轉為本機事件紀錄文字。 |
| [inventory_updates.py](../wlre/core/inventory_updates.py) | 權威物品記錄新增／合併與庫存一致性檢查。 |
| [maintenance.py](../wlre/core/maintenance.py) | 每兩小時的快取清理計時器；不是戰後物品維護。 |
| [state.py](../wlre/core/state.py) | State 欄位、事件套用、位置證據與快照。 |
| [state_ownership.py](../wlre/core/state_ownership.py) | 單一寫入執行緒、巢狀容器保護與服務欄位修改範圍。 |

## wlre/network：連線與協定

| 模組 | 責任 |
|---|---|
| [client.py](../wlre/network/client.py) | TCP 連線、SessionLogic、登入階段與命令／排程協調；實際命令規則及服務 tick 已各自拆分。 |
| [commands.py](../wlre/network/commands.py) | 手動指令驗證與分派；保留 SessionLogic 入口。 |
| [connection_health.py](../wlre/network/connection_health.py) | OS TCP keepalive、收包時間與連線結束證據。 |
| [expedition.py](../wlre/network/expedition.py) | 遠征 S31 回覆解碼；不負責遠征策略。 |
| [layouts.py](../wlre/network/layouts.py) | 角色清單、世界角色與戰鬥單位的固定封包欄位結構。 |
| [live_data.py](../wlre/network/live_data.py) | 背包、裝備、角色能力、技能與夥伴即時資料解碼。 |
| [protocol.py](../wlre/network/protocol.py) | 封包解碼分派，以及登入／戰鬥等基礎封包建立。 |
| [service_scheduler.py](../wlre/network/service_scheduler.py) | 網路執行緒內的服務 tick 順序與狀態發布。 |
| [social_protocol.py](../wlre/network/social_protocol.py) | 隊伍與相關社交回覆解碼。 |
| [state_updates.py](../wlre/network/state_updates.py) | StatePublisher 快照節流與強制通知。 |
| [wire.py](../wlre/network/wire.py) | Packet、Reader／Writer、串流拆框與 XOR 編碼。 |

## wlre/storage：設定與檔案保存

| 模組 | 責任 |
|---|---|
| [account_settings.py](../wlre/storage/account_settings.py) | 帳號＋伺服器 AI 設定檔、驗證與舊分流設定遷移。 |
| [atomic.py](../wlre/storage/atomic.py) | 跨程序檔案鎖、原子 JSON 寫入及檔案權限處理。 |
| [defaults.py](../wlre/storage/defaults.py) | 讀取並驗證內建非憑證連線設定。 |
| [expedition_settings.py](../wlre/storage/expedition_settings.py) | 帳號遠征偏好驗證、鎖定與原子保存。 |
| [login_memory.py](../wlre/storage/login_memory.py) | 登入目標／帳號記憶與 Windows DPAPI 密碼保護。 |
| [paths.py](../wlre/storage/paths.py) | 共用資料路徑與帳號檔名驗證；保留歷史路徑。 |
| [server_lines.py](../wlre/storage/server_lines.py) | 官方伺服器與分流資料的讀取、驗證及 endpoint 對應。 |

## wlre/services：遠征功能

| 模組 | 責任 |
|---|---|
| [coordination.py](../wlre/services/coordination.py) | 共用指令互斥與活動暫停條件；遠征獨立啟用。 |
| [expedition/__init__.py](../wlre/services/expedition/__init__.py) | 舊版 `wlre.services.expedition` 的公開 API 相容入口，轉出原有遠征函式及類別。 |
| [expedition/manager.py](../wlre/services/expedition/manager.py) | 遠征狀態、派遣、好友度恢復、領獎及伺服器回覆確認（保留原本安全保護）。 |
| [expedition/data.py](../wlre/services/expedition/data.py) | 官方遠征／夥伴資料表解析、catalog 載入與資料根目錄。 |
| [expedition/teams.py](../wlre/services/expedition/teams.py) | 併用條件、成功率及最多四人的精確隊伍搜尋。 |
| [expedition_data.py](../wlre/services/expedition_data.py)／[expedition_teams.py](../wlre/services/expedition_teams.py) | 原始匯入路徑的相容轉接，不再維護第二份運算邏輯。 |

## wlre/services/battle：戰鬥、角色與隊伍

| 模組 | 責任 |
|---|---|
| [attribute_points.py](../wlre/services/battle/attribute_points.py) | C8-1 配點驗證、基準比對與能力同步確認。 |
| [auto_battle.py](../wlre/services/battle/auto_battle.py) | AI 預設與驗證、規則優先序、回合決策及戰後補給。 |
| [battle_commands.py](../wlre/services/battle/battle_commands.py) | 戰鬥單位所有權、目標與可送出指令檢查。 |
| [combat.py](../wlre/services/battle/combat.py) | 原版普攻資料、技能選擇與戰鬥效果文字。 |
| [companions.py](../wlre/services/battle/companions.py) | 出戰／休息封包與夥伴資料狀態。 |
| [party.py](../wlre/services/battle/party.py) | 隊伍狀態、邀請／加入與隊伍指令。 |
| [party_guard.py](../wlre/services/battle/party_guard.py) | 必要隊員設定、缺席判斷與 AI 逃跑條件。 |

## wlre/services/world：世界、移動與導航

| 模組 | 責任 |
|---|---|
| [coordinates.py](../wlre/services/world/coordinates.py) | 邏輯地圖、模型與封包／導航座標換算。 |
| [display_position.py](../wlre/services/world/display_position.py) | 將位置證據轉為介面可顯示的座標。 |
| [map_names.py](../wlre/services/world/map_names.py) | 地圖名稱與識別碼解析。 |
| [movement.py](../wlre/services/world/movement.py) | 本機路徑、移動封包排程與伺服器位置確認。 |
| [movement_display.py](../wlre/services/world/movement_display.py) | 移動要求與實際位置結果的顯示文字。 |
| [navigation.py](../wlre/services/world/navigation.py) | 離線導航圖、幾何查詢與路徑計算。 |
| [obstacle_scope.py](../wlre/services/world/obstacle_scope.py) | 地圖／小屋動態障礙變更的作用範圍。 |
| [portal_policy.py](../wlre/services/world/portal_policy.py) | 傳點目的地可用性；目前仍引用 ui.minimap.SmallMaps。 |
| [portal_travel.py](../wlre/services/world/portal_travel.py) | 步行到出口與單次傳點觸發狀態機。 |
| [portals.py](../wlre/services/world/portals.py) | 內建出口、目的地與可直接觸發資料。 |
| [roaming.py](../wlre/services/world/roaming.py) | 自動徘徊的四點順序、戰後續行與停止條件。 |
| [smallmaps.py](../wlre/services/world/smallmaps.py) | 共用地圖索引、投影與延遲圖像載入。 |

## wlre/services/items：物品、生產與戰後維護

| 模組 | 責任 |
|---|---|
| [alchemy.py](../wlre/services/items/alchemy.py) | 煉金選料、預留、結果確認與連續執行。 |
| [catalog.py](../wlre/services/items/catalog.py) | 唯讀物品與技能資料及名稱查詢。 |
| [combat_resources.py](../wlre/services/items/combat_resources.py) | 物品／技能目錄、即時知識套用、可用量與施放／補給規劃。 |
| [crafting.py](../wlre/services/items/crafting.py) | 製作設備、原料、官方排程與伺服器製作操作。 |
| [crafting_browser_model.py](../wlre/services/items/crafting_browser_model.py) | 製作瀏覽的已持有／可用數量模型與共用收藏保存。 |
| [crafting_plan.py](../wlre/services/items/crafting_plan.py) | 本機自訂清單續作與伺服器排程命令整合。 |
| [field_supply.py](../wlre/services/items/field_supply.py) | 場外補給的扣料／數值雙重確認與逾時鎖定。 |
| [inventory.py](../wlre/services/items/inventory.py) | 背包事件套用、可用量計算與格位保留。 |
| [maintenance.py](../wlre/services/items/maintenance.py) | 戰後修理／整理設定、背包篩選及官方封包建立。 |
| [post_battle_maintenance.py](../wlre/services/items/post_battle_maintenance.py) | 逐筆修理、販售、丟棄與格位／裝備確認。 |
| [recovery.py](../wlre/services/items/recovery.py) | HP／SP 補給偏好、藥水儲存槽與補給選擇規則。 |
| [reservations.py](../wlre/services/items/reservations.py) | 跨戰鬥、補給、煉金、製作、遠征與維護的背包保留登記。 |
| [room_storage.py](../wlre/services/items/room_storage.py) | S62 儲藏室／雜物櫃的唯讀解碼與權威狀態。 |

## wlre/services/social：聊天與公會

| 模組 | 責任 |
|---|---|
| [chat.py](../wlre/services/social/chat.py) | 聊天封包讀寫、頻道與發話驗證。 |
| [chat_names.py](../wlre/services/social/chat_names.py) | 聊天角色／群組名稱解析。 |
| [guild.py](../wlre/services/social/guild.py) | 公會資料與相關回覆狀態。 |

## tools/build：編譯與發佈工具

| 模組 | 責任 |
|---|---|
| [build_macos.py](../tools/build/build_macos.py) | macOS arm64／x64 原生 Nuitka app 建置及簽章驗證。 |
| [build_nuitka.py](../tools/build/build_nuitka.py) | Windows standalone 建置、依賴環境與共用資源列舉。 |
| [python_build_support.py](../tools/build/python_build_support.py) | Python 開發檔、函式庫與建置環境支援。 |
| [release_macos.py](../tools/build/release_macos.py) | macOS app ZIP 封裝與版本／內容驗證。 |
| [release_nuitka.py](../tools/build/release_nuitka.py) | Windows 發版標籤驗證、ZIP 封裝與校驗檔。 |

## tools/resources：資源維護工具

| 模組 | 責任 |
|---|---|
| [collect_emoji_resources.py](../tools/resources/collect_emoji_resources.py) | 表情資源收集工具，不屬執行期連線流程。 |

各目錄的 `__init__.py` 為套件入口；應用版本定義在 `wlre/__init__.py`。

## wlre/resources：唯讀執行期資料

| 資源 | 內容／使用方 |
|---|---|
| `combat_catalog.json`／`normal_attack_data.json`／`enums.json` | 物品、技能與戰鬥列舉。 |
| `crafting_catalog.json`／`alchemy_catalog.json`／`item_stackable.json` | 製作、煉金與堆疊資料。 |
| `expedition_catalog.json` | 官方任務、等級、推薦條件與夥伴對照。 |
| `map_names.json`／`portals.json`／`stage_coordinates.json`／`graph_origins.json` | 地圖、出口、座標與導航原點。 |
| `server_list.json`／`default_profile.json` | 官方伺服器列表與非憑證連線設定。 |
| `item_icons.zip`／`item_icon_map.json`／`item_icon_coverage.json` | 物品圖示及其索引／覆蓋資訊。 |
| `emoji_images.zip`／`emoji_catalog.json` | 聊天表情及其目錄。 |
| `smallmaps.zip`／`navigation_data.zip` | 小地圖與離線導航資料。 |
| `assets/app.ico`／`assets/exp_background.png` | 程式圖示與背景插畫。 |
| `assets/buttons/`／`assets/function-icons/` | 原版按鈕、功能圖示及來源說明。 |

所有執行期資源以 `wlre.paths.RESOURCE_ROOT` 定位。`docs/button-assets/` 只供網頁預覽與下載，不是程式讀取來源。

## tests：測試領域

| 領域 | 代表性測試 |
|---|---|
| 跨功能／狀態所有權 | `test_automation_integration.py`、`test_architecture_boundaries.py` |
| 封包／狀態／配點 | `test_state_updates.py`、`test_attribute_points.py`、`test_room_storage_1262.py` |
| AI／組隊／夥伴 | `test_optimized_ui.py`、`test_party_guard.py`、`test_companion_commands.py` |
| 遠征 | `test_expedition.py`、`test_expedition_teams.py`、`test_expedition_ui.py` |
| 背包／戰後維護／煉金 | `test_bag_grid.py`、`test_maintenance.py`、`test_post_battle_maintenance.py`、`test_alchemy_continuation.py` |
| 版面／操作 | `test_dashboard_layout.py`、`test_redesigned_layout.py`、`test_compact_crafting.py`、`test_overview_controls.py` |
| 連線／佇列／清理 | `test_connection_health.py`、`test_ui_event_budget.py`、`test_periodic_cleanup.py`、`test_position_cache.py` |
| 帳號／登入 | `test_login_memory.py`、`test_server_account_settings.py`、`test_login_and_tab_alignment.py` |
| 編譯／發版 | `test_build.py`、`test_macos_build.py`、`test_release_preflight.py`、`test_release_nuitka.py` |

以上為導讀，不表示其他測試無關或所有實服流程已覆蓋。完整測試檔案請以 `tests/test_*.py` 為準。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 整體架構、資料流、狀態、保存與重構建議。 |
| [UI_LAYOUT.md](UI_LAYOUT.md) | 介面版面、樣式與互動設計。 |
| [PROTOCOLS.md](PROTOCOLS.md) | 協定研究與限制。 |
| [EXPEDITION.md](EXPEDITION.md) | 遠征資料、組隊與自動化流程。 |
| [MAINTENANCE.md](MAINTENANCE.md) | 戰後修理／整理流程與原始協定。 |
| [attribute_points_1262.md](attribute_points_1262.md) | 角色配點協定與限制。 |
| [room_storage_1262.md](room_storage_1262.md) | 小屋倉庫唯讀資料同步。 |
| [CONNECTION_DIAGNOSTICS.md](CONNECTION_DIAGNOSTICS.md) | 連線與介面診斷。 |
| [CLEANUP.md](CLEANUP.md) | 週期清理。 |
| [NUITKA_BUILD.md](NUITKA_BUILD.md) | 原生打包與發版操作。 |
| [VALIDATION.md](VALIDATION.md) | 歷史驗證結果，需留意各次版本與日期。 |

## 維護約定

1. 介面放 `ui`，規則與操作狀態機放對應 `services`，協定讀寫使用 `network.wire`。目前既有依賴例外列於整體架構的改善章節。
2. 新增使用者設定要定義保存範圍、預設值、驗證與舊版遷移，不能默認所有設定均按角色或帳號隔離。
3. 送出指令不預先寫入伺服器成功結果；操作要有回覆確認、逾時與跨功能資源保護。
4. 新資源要同步核對自檢與編譯收錄。使用 resource_manifest 的必要清單與驗證器，不可只因檔案在目錄中就視為已驗證。
5. 根目錄保留啟動／打包腳本；一次性解包與開發環境檔案不要加入執行期套件。
6. 修改功能時，同步更新功能文件與本索引；此文件不代替程式碼或正式服實測。
