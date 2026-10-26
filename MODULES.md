# 功能清單與模組契約

基準及逐檔證據見 [架構](ARCHITECTURE.md) 與 [完整對照](docs/rebuild/FILE_MAPPING.md)。下表為使用者功能盤點，狀態均為「既有功能待移植」，不是新模組完成清單。API 以既有入口為依據，移植時逐項保留 import 相容層。

| 功能 | 現有公開入口／主要位置 | 目標責任／共享相依 | 主要資料／事件 | 批次 |
|---|---|---|---|---|
| 帳號、登入、選角 | `ui/account_controller.py`、`login_controller.py`、`network/client.py` | character；設定、憑證保護、連線狀態 | 登入／角色列表／world_ready | P3 |
| 主程式版本驗證 | `version_gate_controller.py`、`game_version_gate.py` | 登入閘門；官方版本／協定核准分離 | 版本觀測、相容性報告 | P2/P6 |
| 主頁與目前活動 | `overview_ui.py`、`dashboard_builder.py`、`core/activity.py` | 主頁 UI；功能狀態投影 | 角色、戰鬥、徘徊、遠征摘要 | P6 |
| 角色能力配點 | `attribute_points_ui.py`、`battle/attribute_points.py` | character；已驗證指令 | 權威能力點／待確認操作 | P3 |
| 夥伴出戰 | `companion_ui.py`、`battle/companions.py` | companion；背包／隊伍共享協調 | 夥伴能力／出戰狀態 | P3 |
| 隊伍與隊員檢查 | `party_guard_ui.py`、`battle/party*.py` | party；連線與操作仲裁 | 隊伍快照、準備檢查 | P3 |
| 戰鬥狀態與技能 | `battle_view.py`、`battle/combat.py`、`battle_commands.py` | battle；PacketCodec／Router | 戰鬥、回合、單位及技能 | P3 |
| 自動戰鬥與設定 | `ui/auto_battle/`、`battle/auto_battle.py` | battle；預約物品、狀態協調 | AI 規則、開始／停止、戰鬥摘要 | P3 |
| 自動徘徊 | `world/roaming.py` | movement；戰鬥與補給仲裁 | 徘徊遇敵／遇敵戰鬥 | P3 |
| 移動與定位 | `world/movement*.py`、`display_position.py` | movement；單一網路狀態 | 伺服器座標、移動確認 | P3/P4 |
| 協力、房間與免費獎勵 | `features/cooperative/`、`services/instance*.py` | cooperation；共用房間協定與鎖定 | 房間／待命／開始／獎勵 | P5 |
| 一般副本、房間、獎勵、寶箱 | `features/dungeon/`、`network/instance_actions.py` | dungeon；共享房間與背包 | 副本目錄、資格、結果 | P5 |
| 場景與小地圖 | `features/minimap/`、`world/smallmaps.py`、`scene_names_1275.py` | minimap；官方場景模型與地圖 provider | SceneID／模型／尺寸／投影 | P4 |
| 座標與導航 | `world/coordinates.py`、`navigation.py`、`obstacle_scope.py` | navigation；與繪圖分開 | 世界／packet／圖片座標、網格證據 | P4 |
| 傳送點與逐圖核對 | `features/portals/`、`world/portal*.py` | teleport；Repository／Resolver／Validator | scene+事件語意鍵、官方 Door／Convey／Eve | P4 |
| NPC、對話、選項 | `features/npc/`、`world/npc_*.py` | npc；官方索引、事件鎖 | NPC／Talk／Text／事件 | P5 |
| 商店與交易證據 | `world/npc_shop*.py`、`network/npc_dialogue.py` | shop；共享背包／金幣／指令 | S23／S26／S27 權威觀測 | P5 |
| 遠征與自動領獎 | `ui/expedition/`、`services/expedition/` | expedition；工作排程、物品預留 | 官方任務、推薦條件、成功率、時間 | P5 |
| 背包與物品 | `bag_grid.py`、`items/inventory.py`、`catalog.py` | inventory；官方靜態目錄與即時數量分離 | 背包格位、數量、修訂／可信度 | P5 |
| 超空間袋與帳篷 | `items/room_storage.py`、`world/tent.py` | storage；共享移動、家具狀態 | S62／S65、倉庫／家具 | P5 |
| 補給與恢復 | `recovery_ui.py`、`items/field_supply.py` | supply；背包權威及物品預留 | HP／SP／恢復品實存 | P5 |
| 修理與戰後整理 | `maintenance_ui.py`、`items/post_battle_maintenance.py` | supply；共享交易仲裁 | 耐久、修復品、賣／丟待確認 | P5 |
| 煉金 | `services_ui.py`、`items/alchemy.py` | alchemy；背包與排程 | 官方配方、材料、結果 | P5 |
| 製作與製作排程 | `ui/crafting/`、`items/crafting*.py` | crafting；背包／家具／預留 | 配方、條件、佇列、確認 | P5 |
| 每日／每週任務 | `world/daily_task_1275.py` | daily_tasks；官方任務與狀態同步 | 任務文字／進度（實際支援範圍需驗收） | P5 |
| 一般任務 | NPC／事件流程中尚未獨立 | quests；先界定既有支援範圍 | 不新增猜測任務流程 | P5 |
| 聊天、公會、名稱 | `chat_ui.py`、`services/social/` | social；有界訊息儲存 | 即時聊天、公會狀態 | P5 |
| 經驗效率 | `efficiency_ui.py`、`core/efficiency.py` | efficiency；戰鬥結果事件 | 經驗、時間、樣本統計 | P5 |
| 官方更新與資源 | `official_*.py`、`world/*catalog*`、`runtime_1275.py` | resources；來源、解析器、驗證、快照 | ResourcePath／Manifest／Bundle | P2 |
| 圖示、主題、視窗 | `theme*.py`、`function_icons.py`、`button_art.py` | ui/components；經驗證資產 | 圖像透明度、尺寸與視窗生命週期 | P6 |
| 主程式更新／Launcher | `launcher.py`、`lala_updater.py`、`WLRE_Client.py` | launcher／updater；GitHub 正式發行驗證 | LaLaVersion 與官方資料版本分離 | P6 |

## 每個移植模組的契約關卡

必須記錄名稱、責任、公開 API、服務依賴、訂閱／發出事件、必要官方欄位、初始化／ready 檢查、啟動／停止、錯誤恢復、資源釋放及測試入口。模組狀態為 CREATED → INITIALIZED → READY → RUNNING → STOPPING → STOPPED，失敗轉 FAILED；未 READY 不執行功能。契約不是任意跨模組拿 State 或 UI 物件的許可。

停止反向解除訂閱、取消排程、通知背景工作停止並有界等待；不能僅將 boolean 設為 false 就宣稱執行緒已退出。失敗不能阻止其他模組釋放資源。官方必要欄位缺失應回報 UNKNOWN／MISSING／UNSUPPORTED／INVALID，不回傳假資料。

## 公用基礎層

TCP、Packet／FrameDecoder、指令驗證、State 單寫入、SessionBridge、事件佇列、原子儲存、物品預留、跨自動化協調、官方來源驗證與快取均共享。先建立契約再接既有實作，不在每個功能重寫網路或安全規則。
