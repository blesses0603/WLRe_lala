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

## P1a 已實作核心契約

| 元件 | 公開 API／責任 | 相依與事件 | 停止與錯誤處理 | 測試 |
|---|---|---|---|---|
| Application | `initialize/start/pump/stop`；只組裝與協調 | Configuration、ModuleManager、EventBus、StateManager、DiagnosticLog | 初始化／啟動失敗反向回復；停止失敗保留 FAILED | test_rebuild_application |
| ManagedModule／ModuleManager | ModuleSpec、`initialize/start/stop/own/own_worker`、唯讀狀態 | 只注入已宣告且 READY 的相依公開 API；ModuleSpec 記錄事件與官方需求識別 | 相依循環／遺漏先拒絕；所有 API 先 quiesce；清理異常不阻止其他模組；工作逾時不能標成功 | test_rebuild_application |
| EventBus | `subscribe/unsubscribe/publish/post/drain/close` | frozen dataclass 精確型別；同步 owner dispatch、背景有界 mailbox | 重複訂閱冪等，遞迴同步分派拒絕，handler 失敗隔離；滿載明確 queue.Full；關閉清空待處理與訂閱 | test_rebuild_events |
| StateManager | `replace/snapshot/close`；不可變功能投影 | 只接受 owner 寫入與單調 revision，不載入官方資料或權威 State | 可變值／過期修訂拒絕，snapshot 不隨後續變更，關閉清空 | test_rebuild_application |
| DiagnosticLog | `record/snapshot/close`；固定識別碼與數值計數 | 標準 logging 可注入，無事件／憑證／例外文字 | 有界紀錄；sink 故障不遞迴 logging；關閉不再新增 | test_rebuild_application |
| ApplicationConfiguration | 事件容量／每輪上限 | 不載入帳密或歷史遊戲表 | 型別／界線錯誤拒絕，不偷偷使用預設取代無效參數 | test_rebuild_application |

上述元件是核心基礎，不代表遊戲功能已完成移植。核心相依／無循環／無 GUI 執行期載入由 `test_rebuild_boundaries.py` 自動檢查。現有完整三平台 PR CI 保留，新增 `core-rebuild.yml` 在開發分支推送執行三平台純核心測試，不安裝 GUI／UnityPy。

## P1b 桌面過渡轉接契約

`ui/application_host.py` 的 DesktopHost／DesktopModule 以 `legacy_desktop` 契約接入現有 `App`。公開 API 僅提供不可變 DesktopStatus；此轉接沒有將所有遊戲業務集中到新核心，也沒有聲稱各功能模組已移植。正常 `gui.main` 與來源 GUI smoke 均經新 Host 組裝；原 `App(root)`、`gui.main` 及功能視窗入口保持相容。

WorkerGroup 記錄遊戲連線、版本查詢、Release 查詢／下載背景工作；重複工作拒絕、結束後釋放登記。關閉時先取消及隱藏視窗，以 Tk 計時器等待，最長 15 秒，再核對所有工作是否退出。不能立即中斷的單次 HTTP 等待仍受既有 12 秒逾時限制；不使用強制終止執行緒。未退出或取消 callback 失敗會保留 FAILED，交給桌面入口回報，不標示成功。

版本閘門仍依原有來源驗證與 1275 Runtime 規則，不因加入取消而放行；更新下載仍驗證 SHA／ZIP CRC、原子更名且不安裝。取消會停止後續請求／串流／CRC 檢查，清除 partial 並保留既有成品。官方來源與固定版本的正式遷移仍屬 P2。測試：`test_rebuild_workers`、`test_desktop_application_host`、`test_shutdown_cancellation` 及既有登入／更新／連線回歸。

## P2 第一批正式資源介面

| 元件 | 公開介面與相依 | 安全／停止契約 | 驗證 |
|---|---|---|---|
| official/source | 唯一 ROOT／OFFICIAL_HOST、`package_url` | 路徑、Package 與副檔名白名單；沒有自動 I/O | test_official_resource_versions／原有來源拒絕測試 |
| official/versions | `VersionDetector.observe(exe_version, cancel_event=...)`、OfficialVersions | 只觀測；明確身分、兩輪一致、取消停止後續請求；保留原始映射供分析，無正式啟用 API | 新 6 項及真實官方受控觀測 |
| parsers/yooasset | `parse_manifest`、Reader、ParseError、bundle／asset fingerprint | 純標準庫、不依賴 tools、無背景工作；大小、EOF、bool、引用、重複與未知格式拒絕 | 既有 Parser／Manifest／增量測試及新邊界測試 |

既有 HTTP／Manifest／Bundle 服務逐步接入此層，保持舊 import 與驗證 API。VersionDetector 重用既有已測版本表語意；HTTPS 傳輸已抽離至下述共用下載器，沒有再實作第二套遊戲傳輸或靜態資料庫。資源層不匯入 GUI，也不執行 Lua。

共用下載器批次已完成 HTTP 傳輸抽離：`DownloadManager.read/download/verify_file/close` 統一來源驗證、長度與總時限、有限重試、取消、進度、原子檔案發佈及條件式 Range。它只依賴標準庫、來源政策及核心診斷，不執行資料解析、不擁有遊戲狀態、不決定版本／協定相容性。舊服務仍負責各自 Manifest 身分／CRC、Lua 索引及版本語意。可借用外部診斷，`close` 不關閉借用物件；沒有背景執行緒，回應及 partial 在返回／失敗時釋放。測試 `test_resource_downloader.py` 及原有官方服務回歸涵蓋此契約。

## P2 場景快照服務契約（限定範圍已實作）

| 元件 | 公開介面／責任 | 依賴與生命週期 | 驗證入口 |
|---|---|---|---|
| ResourceRequirement／ResourceStatus | 功能、索引、Package、完整路徑、版本化 Parser；缺口狀態 | 純資料契約；需求唯一且有界，不載入外部程式碼 | test_official_resource_manager |
| ResourceGapAnalyzer | analyze；精確資產與必要閉包、加密拒絕、整批配額 | 現有 Manifest／增量規劃服務；無 I/O 掃站或自有背景工作 | 缺失／未知／加密／循環／配額測試 |
| CompatibilityValidator | validate；已審核場景／文字格式，不授權封包 | 場景／文字 Parser；必要表為空、越界、重複、尾段均拒絕 | 場景／舊 API 回歸 |
| SnapshotStore | put／read／current_id／commit／diagnose | 私人快取、storage.atomic；內容定址、鎖與原子 CAS；磁碟收據不授權正式查詢 | 競爭提交、寫入失敗、竄改、重複 JSON 鍵 |
| OfficialResourceManager | refresh／diagnose／close、context manager | 版本、Manifest、共用下載器、Parser／驗證器／Store；單次 refresh 互斥，無自建執行緒。close 撤銷 view、取消 I/O，呼叫端仍須由 WorkerGroup 等待工作退出 | 整管線、變版／變 hash、取消／關閉、失敗保留舊收據 |
| OfficialDataService | records／get／scene_reference／reference_summary；同一快照不可變查詢、明確 validated_at | 僅由當次成功 refresh 提供；下一次核對或關閉撤銷。無離線 current、無遊戲封包 API | 不可變、舊 view 撤銷、離線拒絕 |

初次場景快照批次沒有新增事件或背景排程；後續已補名稱／模型索引稽核與資源 Module 的 READY／啟動契約，見下方。GUI 唯讀頁已接入；地圖業務消費者、模型內容及其他功能索引仍待逐項驗收；完整功能表的 P3～P6 狀態不因此改為完成。

## P2 場景引用稽核契約

- `parsers/texts.parse_text_table`：有界 UTF-16 LE 文字表，驗證筆數、ID、長度、編碼及 EOF；回傳不可變紀錄、SHA 與各列來源範圍。既有 `expedition.data.parse_text_data` 維持 dict／ProtocolError 入口。
- `official/adapters`：程式內審核的 `SCENE_DEFINITIONS`／`TEXT_DEFINITIONS` 精確配對。不同 Parser 各有來源格式與收據，不再把文字表當成 76-byte 場景表。
- `official/references.audit_scene_references`：同次場景／文字／MainPackage 索引的唯讀稽核；缺少文字不猜名稱，重複模型 ID、路徑與 address 不一致、缺 Bundle 或加密分別拒絕。模型內容與幾何不在本次驗收範圍。
- `OfficialDataService.scene_reference(scene_id)`／`reference_summary()`：沿用整份快照租約，refresh／close 後失效；沒有遊戲傳送、繪圖或導航授權。
- 無新增事件／背景工作／GUI 依賴；完整生命週期模組接入另批執行。測試入口 `test_official_scene_references.py`，常規 CI 使用合成樣本。

## P1／P2 OfficialResourceModule 契約

| 項目 | 已實作行為 |
|---|---|
| 職責／依賴 | 官方範圍快照取得與租約／工作清理；依賴既有 ManagedModule、WorkerGroup、EventBus、OfficialResourceManager，不依賴 GUI／Android API |
| 公開 API | `module.api.refresh(exe_version, scope=..., requirements=(...))`、`poll()`、`status()`、`cancel()`、`current()`、`diagnose(scope)`；只在 READY／RUNNING 且擁有者執行緒可呼叫 |
| 初始化／啟動 | 登記清理、建立 Manager 與受管工作群；沒有自動 I/O 或啟動資料更新 |
| 工作狀態 | idle → refreshing → current／failed／cancelled；取消尚未返回的工作為 cancel_requested，不把生命週期 RUNNING 當作資料可用 |
| 事件 | 不訂閱事件；`ResourceRefreshFinished(job_id, scope, phase, snapshot_id, code)` 只有固定代碼／識別。事件是當時觀測，不能授權遊戲指令，消費者仍須 current 查詢 |
| 背壓 | 一個工作／一個結果槽；`poll` 送完成事件時 EventBus 滿載則保留通知，下一 tick 重試，未交付前拒絕新更新，不靜默遺失或無界累積 |
| 取消／停止 | 立即撤銷舊 view，合作式取消下載；晚到成功不啟用。停止先 close Manager 再有界 join，清理結果與事件參照。超時仍有工作必須 FAILED，不假裝 STOPPED |
| 錯誤／資料 | 固定錯誤碼，不輸出原始 I/O 例外；失敗只有帶診斷標示的舊收據，不啟用離線資料。current 返回既有不可變 DataService，停止後租約失效 |
| 測試／使用者 | `test_official_resource_module.py`；命令列 `managed_snapshot` 已組裝 Application。GUI 唯讀頁已接入；地圖／舊 Runtime 消費者未移植 |

預設停止 join 2 秒，可明確設定至多 30 秒；同步 UnityPy 解壓不能硬式中斷。未能及時退出時回報失敗，不能承諾強制終止；GUI 已非阻塞等待合作式取消，再呼叫核心 stop。

## P2 場景欄位與 GUI 契約

- `assess_scene_fields`／`SceneAssessment`：九項欄位的狀態、固定理由碼與分離的可讀名稱／地圖／導航就緒狀態。缺少引用身分或歧義拒絕，虛擬零尺寸保留為 MISSING，不刪場景；所有未接入來源保持 UNKNOWN，傳送一律未核准。
- `OfficialDataService.scene_assessments()`／`scene_field_summary()`：同一快照不可變逐場景 DTO 與統計；refresh／cancel／close 後不可繼續查詢。來源收據包含同份統計，不另建人工資料庫。
- `features/scene_data/controller`：只經公開資源 API 更新／取消／查詢；窗口關閉釋放引用，不持有遊戲狀態。`window` 提供版本輸入、來源版本與核對時間、搜尋／100 筆分頁、鎖定表格與欄位詳情。沒有獨立 timer、Thread、網路或遊戲指令。獨立開啟也會安裝共用 Root 資源清理，原生參照由 UI 擁有者釋放。
- DesktopHost 將 official_resources 宣告為桌面相依；唯一 pump 納管新資料與舊 GUI，關閉等待兩群工作。Manager.close／revoke 不等待磁碟提交；提交結束後先換租約再查取消，避免晚到結果啟用。不可中斷的原子提交可能留下完整診斷收據，但不提供當前查詢。
- 測試：`test_scene_fields`、`test_scene_data_window`、`test_desktop_application_host`，另保留 Manager／Module 全部回歸。
