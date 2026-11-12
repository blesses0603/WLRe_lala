# C# 電腦版／公用核心與 Python 逐項對照（2026-11-12）

目前 **尚不能判定 C# 與 Python 行為一致**。主要畫面與多數核心解析已有對應；本次仍找出儲藏、副本確認與夥伴出戰的可重現缺口，以及自動化生命週期、房間接續、方舟題庫等差異。先前「已接上」表示入口或主要流程存在，不代表所有失敗、重入與接收順序都已對齊。

## 比較基準與範圍

- Python 使用本儲存庫**目前工作目錄內的實際來源**，沒有只採用舊 PR 表格；C# 包含現有未提交的商店／道具修正。
- 逐檔建立 **421 個非測試 Python 檔案**的索引，其中 `wlre/` **321 個模組**，共 **2,661 個類別／函式／方法／巢狀定義位置**，分為 56 個對照群組。另有包裝標記及開發工具，不能把它們當成缺少的遊戲功能。
- [完整逐檔索引](desktop-python-comparison-2026-11-12.json) 保存來源位置、原始與換行正規化 SHA256、定義位置、歷史狀態、目前對應 C# 檔案群組與本次發現。群組對應不等於逐一證明全部 2,661 個定義相等；下方功能表及重現案例才是本次的行為結論。
- 舊 migration inventory 的 416 筆桌面紀錄已不足以表示現況。397 個原始指紋差異僅來自 CRLF／LF；真正超出換行的來源差異有 7 個，另新增 5 檔。不能將 404 個原始 SHA 差異誤報為 404 個邏輯修改。
- 以 Python 行為作比較基準，官方同版 Lua 作規則核對依據；不把 Python 的唯讀限制、未完成處或框架選擇都照搬成 C# 必須相同的行為。
- 使用者擱置的**交易所、星盤覺醒、角色／夥伴裝備穿脫**不列待補功能；Android 主機／服務及正式伺服器全情境驗收不在本輪範圍。

## 已重現的五個差異

本機探針直接載入已建置的桌面 `Lala.Core.dll`，呼叫實際操作規劃器及其成功判斷；只建立合成狀態，沒有連線、登入或消費。原始結果及該 DLL 的 SHA256 收在逐檔索引的 `reproductions`、`probed_desktop_core_sha256`。

| ID／優先度 | 操作情境 | Python 要求 | C# 實際結果 | 影響與來源 |
| --- | --- | --- | --- | --- |
| F01／高 | 儲藏：兩邊數量符合，但沒有收到搬移回覆 | `RoomStorageTransfer.observe` 必須有對應 `storage_move_result`，兩邊可靠且來源相符 | 成功判斷回傳 `true` | 不能僅依同物品總量就認定本次存取成功。`wlre/services/items/room_storage_transfer.py:119`；`dotnet/Lala.Core/Gameplay/InventoryGameCommands.cs:67` |
| F02／高 | 儲藏：來源格位已被同 ID、不同流水號物品替換，總量仍符合 | 比對 `reservations.identity`，包含物品 ID、流水號、版本 | 仍回傳 `true` | 可能把別筆物品異動當成本次結果；必須核對原格位身分。相同來源及 `wlre/services/items/reservations.py:13` |
| F03／高 | 副本房間重新查詢後，只更新不相關的狀態文字，沒有房間清單回覆 | 查詢、建房、加入、離開各有對應回覆及狀態要求 | 重新查詢成功判斷回傳 `true` | `ServiceGameCommands` 以整個 `Main/Coop` 物件參照改變作成功條件。已動態重現查詢；建房／加入／離開／開始另共用同型條件，需逐操作改寫。`ServiceGameCommands.cs:22`、`:104`；`wlre/services/instance_creation.py:103`、`instance_room_flow.py` |
| F04／高 | 要進入地圖 200，卻收到本角色進入其他地圖 999 | 確認同角色、房間 ID 與目標副本場景相符 | 仍回傳 `true` | C# 只檢查場景不同於原場景，沒有確認抵達要求的副本。`wlre/services/instance_entry.py:74`；`ServiceGameCommands.cs:104` |
| F05／高 | 初始夥伴 `CanGrow=0`，尚無後續同欄位覆寫 | Python 合併初始資料後禁止無法出戰的夥伴 | C# 規劃器仍接受出戰意圖 | 目前只讀 `StatOverrides["can_grow"]`，沒有回讀 `Data.CanGrow`。`wlre/services/battle/companions.py:17`；`dotnet/Lala.Core/Gameplay/ManualGameCommands.cs:113` |

這些是目前成功判斷／送出前驗證的問題；沒有據此宣稱正式服已發生錯扣、錯移動或封包重送。探針驗證的是規劃器行為，並未讓傳輸層實際送出命令。

## 已確認但尚未逐情境動態重現的行為差異

| ID | Python 行為 | C# 行為 | 判定 |
| --- | --- | --- | --- |
| D01 | `network/service_scheduler.advance_services` 在網路執行緒按固定順序推進維護、遠征、製作、補給、AI、煉金、徘徊與移動；每個服務邊界檢查 hold | `AccountAutomations` 為各功能使用 250 ms 工作，再由帳號操作通道、接收寫入者及協調條件保護 | 架構差異；不能說排程器逐行移植。現有互斥措施不等於已證明各種同時啟動順序都相同 |
| D02 | `AutoBattle.tick` 規劃失敗時設定 `failed_key`，本回合不再規劃，停徘徊，但 AI 仍可等待下一回合 | `SendBattleRoundAsync` 的一般例外轉成 `AutomaticStopException`；外層停 AI 與徘徊，即使本回合還沒送任何指令 | 使用者會看到 Python 下一回合可繼續、C# 需重新啟用。須區分送出前資料不足與送出後結果不明，後者不能自動重送 |
| D03 | Python 的死亡停機檢查包含戰後事件尚未結束的階段，且在特殊戰鬥暫停判斷之前 | C# 在 `NextAutomaticAction` 判斷非戰鬥／特殊戰鬥後才檢查死亡；戰後待接續時又先由協調條件暫停 | 死亡停機檢查的階段不齊；應補合成「退場後、事件結束前」與特殊戰鬥案例。`auto_battle.py:190`、`AccountAutomations.cs:184` |
| D04 | Python 第一次看到場次／回合時凍結本回合 roster，只對該集合規劃 | C# `AutomaticBattleRound.Plan` 每次掃目前所有存活自有單位，另以已送格位 guard 防重送 | 防重送已有，但晚到單位是否納入與 Python 不同；應以官方回合規則確認，不能直接把任一方當成正解 |
| D05 | Python 手動走路完成後可在仍啟用的徘徊內重新設中心、恢復循環；隊員／障礙等暫停也保留較完整的狀態 | C# `NavigateAsync` 先關閉徘徊，再開始手動導航；部分導航例外會停止徘徊 | 主動避免兩個移動意圖的設計差異。雙擊移動可用，不代表會像 Python 一樣自動恢復徘徊。`AccountNavigation.cs:125` |
| D06 | Python `npc_shop.py` 明確唯讀、`buy_enabled=False`，背包介面主要提供補給與存取 | C# 新增官方 Lua 核對的商店交易、一般消耗品、手動販售／丟棄 | C# 擴充；不能要求退回 Python 唯讀，也不能用 Python 原有測試當成新交易流程的全部證據 |
| D07 | Python 製作服務支援其來源資料與執行狀態下的計時／接續 | C# 領取前保守等待 `BaseTime`，原碼明確不推算缺少的加速資訊 | 可用但不完全等速；設備／夥伴加速與同時操作需要另比對 |
| D08 | Python 依服務保存 pending／uncertain 與保留物品；未知結果限制相關服務 | C# 單一帳號操作通道序列化操作，`uncertainActions` 非空時會阻擋全部一般遊戲操作，重新登入才重建 | 更保守的限制；不能稱保留／逾時生命週期逐項相同。聊天及必要核心事件另有獨立通道 |

## 未完整接入的 Python 功能

| ID | Python 來源 | C# 現況 |
| --- | --- | --- |
| G01 房間／NPC 自動接續 | `wlre/network/automatic_flows.py` 保存使用者明確建立的 NPC、房間與製作目標；到達 NPC 後互動、房間確認後繼續待命／開始／進入 | C# 有必要伺服器事件接續及個別手動命令，但沒有等價的 NPC／房間目標管理器。不是手動 NPC 對話全部應自動按下一步 |
| G02 協力自動領免費寶箱 | `instance_rewards.tick` 以 `auto_claim_enabled`、免費狀態、容量及去重控制送出 | C# 手動免費領獎已修正，但 `SetAutomationAsync` 沒有副本／協力領獎服務，桌面也無等價開關 |
| G03 方舟題庫自動送答 | `star_ark.tick` 在 pending 問答中使用已確認答案或經審核候選，並透過 `QuestionStore` 控制候選唯一送出、保存結果 | C# `ArkArithmeticSolver` 已接入，可自動回答能確定解出的算術題；但 `ArkQuestionStore`、審核候選查詢、候選 claim 與結果保存沒有完整接入帳號流程。無法由算術求解的題目仍等待手動回答 |
| G04 背景版本觀測 | `background_version_observer.py`、`ui/background_version_controller.py` 有定時識別碼觀測、狀態顯示及失效撤銷 | C# 有登入前／手動版本與資源核對；未找到等價的桌面背景輪詢接線。不能把每次登入重新核對當成背景 observer |
| G05 LaLa 自我更新 | `lala_updater.check_lala_release/download_verified_release` 與 Python UI | C# `VersionWindow` 明示發行更新尚未接入；不能下載 Python 安裝器充當 C# 更新 |
| G06 小屋／多層與未核對動態碰撞 | Python 有 `house_navigation.py` 及導航來源／遮罩限制 | C# 前批指定一般地圖；連續斜坡已有，不代表小屋多層與未知動態碰撞已驗收。此項另行逐模型核對，不能列為通用完成 |

## 逐項功能對照表

「已有對應」表示程式／入口與已核對切片存在；有缺口時優先採上面的 F／D／G 結論，並不表示正式服全情境相等。

| # | 功能 | Python 主來源 | C# 對應／目前結論 |
| --- | --- | --- | --- |
| 01 | 啟動與資源首畫面 | `WLRE_Client.py`、`version_gate_controller.py` | `DesktopApplication`、`VersionWindow`；按使用者新排版，與 Python 視窗結構不同 |
| 02 | 官方版本、分流 | `official_version.py`、`official_server_list.py` | `Sessions/Discovery`、`DesktopServerCatalog`；已有新鮮清單與身分核對，不用舊清單狀態推論未接 |
| 03 | 驗證登入、正式登入 | `network/client.py`、`login_controller.py` | `AccountConnectionRuntime`、Handshake 與 `LoginWindow`；已接，同版資源綁定保留 |
| 04 | 記住帳號／密碼 | `login_memory.py`、`account_settings.py` | `LoginProfileStore`、`LoginProfiles`；已有 Windows 加密儲存，與 Python 檔案格式分離 |
| 05 | 選角 | `login_controller.py` | `AccountRoleSelection`、`LoginRoleCards`；卡片、頭像、官方屬性圖，依使用者需求調整 |
| 06 | 連線與帳號生命週期 | `session_bridge.py`、`client.py` | `DesktopSession`、`AccountRuntime`、Receive；實作結構不同，舊 publication 撤銷已有 |
| 07 | 封包解框、批次與角色身分 | `wire.py`、`protocol.py`、`state_*.py` | `Protocol`、Receive、State reducers；大量離線向量已有，不等於未識別的官方全部封包都支援 |
| 08 | 事件接續與紀錄 | `SessionLogic.receive/flush_events`、`event_log.py` | `AccountServerEvents`、`PostBattleLifecycle`、`CharacterEventLog`；單次許可、角色篩選與摘要已有；G01 的選配目標接續另缺 |
| 09 | 版本／清單／下載驗證 | `official_resource_sync.py`、`official_manifest_sync.py`、`official_bundle_download.py` | Core 資源 owner／preparation／HTTP；已有實際下載與資料庫准入，版本與額度策略另有邊界 |
| 10 | 資料庫來源及舊資料遷移 | `resource_database.py`、`dynamic_bundle_runtime.py`、storage 模組 | `Resources/Inventory`、資料庫讀取及 RuntimeCandidate；缺來源不拿種子或未知版本補值，非所有歷史工具逐一搬入產品 |
| 11 | 背景版本／發行更新 | 背景 observer、`lala_updater.py` | G04、G05 尚未接齊 |
| 12 | 戰鬥解析、格位與下令 | `battle_commands.py`、`combat_resources.py`、`combat.py` | Battle／Inventory 規則與 `InventoryGameCommands.Battle`；已有技能、道具、普攻及角色／夥伴格位判斷 |
| 13 | 自動戰鬥決策 | `auto_battle.choose_action` | `AutoBattleRuleChooser`；優先條件、低 HP/SP 對象及技能升階等已有；完整生命週期見 D02～D04 |
| 14 | 同回合多單位、防重送 | `AutoBattle.tick`、`SessionLogic.sent_units` | `AutomaticBattleRound`、`AccountBattleRound`、SubmissionGuard；整輪預規劃、共用物品預留已有，roster 差異 D04 |
| 15 | 戰後延遲、事件結束 | `client.py` 戰後流程 | `PostBattleLifecycle`；2.5／5 秒與單次許可已接；死亡停機階段差異 D03 |
| 16 | 戰後 HP／SP、儲存槽 | `field_supply.py`、`recovery.py` | `GameFieldRecovery`；同物品扣除及同對象恢復核對已有；逾時／保留的整體架構不同 D08 |
| 17 | 修理／整理 | `post_battle_maintenance.py`、`maintenance.py` | `GameMaintenance`、`MaintenanceKnowledge`；工具、裝備、販售／丟棄回覆已有，預設開關不擅自啟動 |
| 18 | 四點徘徊 | `world/roaming.py` | 固定中心、四點偏移、五段預檢已有；手動移動後恢復與暫停狀態 D05 |
| 19 | 路徑規劃與斜坡 | `navigation*.py`、`official_movement.py` | 導航網格、走廊、連接、坡面分步與跨樓層排除已有；G06 未通用驗收 |
| 20 | 小地圖雙擊、指定座標 | `minimap.py`、`home_map.py` | `SmallMapImageView` → `MapView` → `AccountNavigation` 已接；留白／舊圖不送；D05 不自動恢復徘徊 |
| 21 | 出口及跨圖 | `portal_travel.py`、`event_portals.py`、`portals.py` | `GameTravelPlanner`、傳點／目的地資料與導航；不從模糊出口猜目的地 |
| 22 | 一般 NPC／門動態資料 | NPC position／visibility、`obstacle_scope.py` | WorldNpcRuntime 與障礙 scope 已接；trigger 不擅自當牆；未知碰撞保持限制 |
| 23 | NPC 靠近、對話、選項 | `npc_approach.py`、`npc_dialogue.py`、`npc_interact.py` | `MapView`、`NpcInteractionWindow`、`GameNpcChoices`；手動流程已有，自動抵達後接續 G01 |
| 24 | NPC 商店 | `npc_shop.py`、`npc_shop_evidence.py` | 同版商品與回覆已有，C# 另新增交易；D06，不能當成與 Python 完全同一功能 |
| 25 | 背包搜尋、分頁與排序 | `resource_view.py`、`bag_grid.py` | `InventoryWindow`；實體格位與顯示排序分開，使用者新要求的獨立背包／特技保留 |
| 26 | 一般消耗品、販售／丟棄 | Python 主要提供補給、維護與儲藏；一般特殊道具亦非全支援 | C# 新增受限一般使用及手動賣／丟；D06。專用道具不能混入通用使用 |
| 27 | 儲藏室／雜物櫃 | `room_storage_transfer.py` | 有操作入口與封包，但 F01／F02 的成功回覆與身分核對不齊 |
| 28 | 夥伴出戰／休息 | `battle/companions.py` | 有 NPC ID 命令與 S19 確認、重複 NPC ID 阻擋；F05 初始 CanGrow 檢查缺漏 |
| 29 | 特技資料／效果／施放 | `resource_view.py`、`skill_effects.py` | `SkillsWindow`、`SkillRecoveryEffects`、CombatResourceSkillValidation；HP/SP 恢復分類已有，恢復量未知不亂估；普通戰鬥技野外禁止符合官方 |
| 30 | 配點 | `attribute_points.py`、`attribute_points_ui.py` | AttributeAllocation 與操作規劃／介面已有；與徘徊等共同操作條件仍須依 D01 檢查 |
| 31 | 遠征 | `expedition/manager.py`、teams／data | `ExpeditionAutomationPolicy`、FaithCommands、ClaimReceipt；成功點數／時間／任務 ID 排序、選中隊伍才補品及實際入包已有 |
| 32 | 組隊／必要隊員 | `party.py`、`party_guard.py` | PartyEvent／命令／FeatureAssistantActions；角色 ID 比對、缺員逃跑、保存與更新設定已有 |
| 33 | 魔方／每日／每週 | `time_cube.py`、`daily_tasks.py` | Automation services 與 UI 已有；遵守伺服器週期及實際獎品，不從本機午夜推算 |
| 34 | 每日助手 | `daily_assistant.py`、`automatic_flows.py` | C# 分 daily／guild／ark 工作與設定；不是 Python 單一原子配置及全部目標管理器的完整移植 |
| 35 | 組織簽到／捐獻 | `guild_actions.py`、`guild_catalog.py` | GuildActions reducer、SocialGameCommands、同版報價與預算已有；一般自動排程 D01 |
| 36 | 方舟派遣／戰鬥／問答 | `star_ark.py`、ark candidates／QuestionStore | 手動流程、派遣／戰鬥及算術自動答題已有；非算術題庫／候選接線 G03 未齊 |
| 37 | 煉金 | `items/alchemy.py` | `AlchemyGameCommands`、FeatureAlchemyActions；材料身分／數量、配方類別與產物確認已有 |
| 38 | 製作及自訂清單 | `items/crafting.py`、`crafting_plan.py` | CraftingGameCommands／GameCraftPlan／介面已有；BaseTime 保守等待 D07；與其他服務排程 D01 |
| 39 | 副本目錄與房間查詢 | `instance_browser.py`、`instance_runtime.py` | 目錄已有；查詢成功條件 F03 |
| 40 | 副本建房／加退／開始 | `instance_creation.py`、room_flow／standby／start | 入口與封包已有；各操作精確成功及拒絕條件未等價，F03。協力 SellDataId 的錯誤入場費判斷已於前批移除 |
| 41 | 進入副本 | `instance_entry.py` | C# 入口已有，但目的場景成功判斷 F04 |
| 42 | 協力免費獎勵 | `instance_rewards.py` | 手動兩格預檢、獎勵明細與實際入包已補；G02 自動領獎未接；付費確認仍缺足夠官方流程證據 |
| 43 | 帳篷展收／進出 | `tent.py`、NPC／傳點來源 | TentReceive、ManualGameCommands、TentExitResolver 已有；小屋導航 G06 分開 |
| 44 | 聊天、頻道與表情 | chat／chat_names、chat_ui、emoji_picker | Core Chat、Dashboard、EmojiGallery 已接；不把附近角色事件混入自身事件紀錄 |
| 45 | 道具圖、頭像、屬性圖、小地圖 | 相關 image／portrait／smallmap 資料庫與映射 | C# 已有來源驗證、批次回讀、快取及撤銷。不能以有圖替代來源同版驗證 |
| 46 | 經驗效率與重設 | `core/efficiency.py`、`efficiency_ui.py` | Efficiency reducer 與介面已有；等待足夠樣本，不以未知數值計算 |
| 47 | 設定編輯、匯入匯出、換帳 | auto_battle UI modules、storage 設定 | SettingsWindow、Preferences、世代隔離已有；UI 排版依新需求，不追求原 Tk 一模一樣 |
| 48 | 記憶體監控與封包檢查 | 非 Python 等價主功能 | C# 額外測試／診斷入口；不作為 Python 移植完成的證據 |

## 本輪驗證及限制

- 421 檔 AST 解析全部成功，來源索引與 C# 對照群組完成；這不是將全部檔案狀態批次改成「已完成」。
- 直接執行桌面核心的五個反例，均重現上面的錯誤接受／成功判斷。探針獨立存於私人研究目錄，不加入一般測試套件，不對正式帳號送出命令。
- 使用現有 `.ui-env` 執行 Python 的儲藏轉移 18、建房 8、必要隊員 19、夥伴命令 4、進入副本 8、戰後 AI 策略 3、自動接續 11，合計 **71 項通過**。系統 Python 初次缺 PIL，改用既有環境後完成，未安裝或修改全域套件。
- 前批 C# **46,131 項**核心回歸與介面測試通過仍有效，但沒有覆蓋本輪發現的所有帳號操作包裝層差異。通過既有測試不能代替新增反例。
- 本輪只增加比較紀錄及逐檔索引，**未修改生產程式、未修正 F01～F05、未重啟使用者的預覽、未碰正式帳號**。

## 建議修正順序

1. 儲藏 F01／F02：加入本次搬移回覆、原格位流水號／版本、兩邊可靠庫存與拒絕／逾時處理。
2. 副本 F03／F04：查詢、建房、加入、離開、開始、進入各用自己的回覆及目標核對，移除「任意狀態更新即成功」。
3. 夥伴 F05 與 AI D02／D03：補初始欄位 fallback，區分當回合資料不足、真正已送出未確認及死亡停機階段。
4. 視需求接入 G01～G05；G06 維持前批一般地圖範圍，另外逐模型驗證。使用者已擱置的三項功能不加入此順序。
