# PR #79 ver 8.0.51：Python 桌面介面對照盤點

範圍是全部桌面畫面及其子視窗，保留使用者較新的「背包／特技各自獨立視窗」要求。參照 PR 原 head `59416bde817f39035176ae9c1e2eeb5b23896d58` 中 Python 7.3.1 原始碼；本批未改 Python，也未聲稱已全部移植完成。

## 已確認的登入差異與修正

Python `login_controller.py` 使用伺服器／分流選單，不讓使用者填 IP、XOR、平台或語言。`services/official_server_list.py` 從官方 HTTPS 清單取得分流，群組 `id // 100` 對應地球／水星，分流標示 `id % 100` 線。切換端點清除帳密，選群組後使用第一條可用分流。新版先前的技術參數表單不符合此流程，現已移除。

Desktop 使用既有 `OfficialServerDiscovery`：官方 HTTPS allowlist、限制大小、禁止 redirect、版本前後一致與完整清單解析通過後才顯示。沒有內建或猜測的正式分流地址、離線清單替代或下載內容提供的協定參數。正式端由使用者選擇的該份清單取得；驗證端與協定來自 `wlre/configuration.py` 的發行程式碼：`34.81.10.22:16988`、TX/RX 173、platform 3、language 0。此歷史觀測設定只接受已知 exe `1.3.0` 和群組 1／2；其餘阻擋，不能把清單的 TLS 觀測當成遊戲端已驗證。清單載入失敗、取消、超過五分鐘或無選擇時不能登入，refresh 先撤銷舊選擇。

仍與 Python 不同：尚未移植可信 SQLite 清單快取、完整資源 gate，以及安全帳號記憶；8.0.43 已補入啟動版本／唯讀資源檢查視窗。載入／儲存帳號與記住密碼維持停用，不讀取舊帳密。角色必須手動選擇，不沿用 Python 首筆預選。每次驗證／正式帳密傳送仍各自確認；官方 TCP 沒有 TLS，XOR 可逆，不提供安全加密。關閉與停止等待釋放；一般遊戲命令保持停用。

## 全畫面清單與實作差距

尺寸是 Python 原碼的設計尺寸，並非每個平台實測的最終像素。**已建版面不等於操作或資源已完成**。

| Python 畫面／流程 | 原始碼（wlre/ 下）與尺寸 | Avalonia 現況／剩餘工作 |
|---|---|---|
| 啟動資源準備、線上版本、背景更新 | ui/version_gate_controller.py、background_version_controller.py；1000×710，內容可增高 | 8.0.43 已接獨立啟動視窗、實際官方 metadata 與選定目錄的 Core SQLite 唯讀檢查；8.0.44 已接登入後必要資源下載／驗證／唯讀目錄綁定；8.0.45 補入登入前必要資料準備及精確同版 gate；全圖資、背景 observer、GitHub 更新、計時及 Python 自動增高仍缺 |
| 登入、帳號清單、分流、選角 | ui/login_controller.py、account_controller.py；900×620 | 已還原下拉流程與自動來源，接共用 Core；帳號設定與可信快取未移植，風險說明可捲動 |
| 主畫面／十張總覽卡片 | ui/dashboard_builder.py、dashboard_layout.py、overview_ui.py、layout.py；1280×800 左870右380 | 既有 Dashboard；補齊所有主要功能入口，仍有卡片完整欄位／資源差距 |
| 聊天／頻道／表情 | ui/chat_ui.py、chat_emoji.py、emoji_picker.py；表情依圖數自動計算 | 既有聊天唯讀、文字草稿；新增無資料表情提示；真實表情網格、文字插入與聊天發送未接 |
| 戰場／選目標 | ui/battle_view.py；嵌入主畫面 | 既有 16 格位置、HP、選取；圖像／效果與所有送出停用 |
| 主地圖／導航預覽 | ui/home_map.py、minimap.py、official_navigation_preview.py；380×320／640×520 | 既有地圖／導航表單；官方圖資、事件／NPC清單與完整導航預覽未完成 |
| 背包／超空間袋／儲藏轉移 | ui/resource_view.py、bag_grid.py、storage_transfer_form.py、room_storage_status.py；1040×700 | 保留獨立背包、6×4格、搜尋／分頁；圖示目錄與可送出的物品操作未完成 |
| 角色與夥伴特技 | ui/resource_view.py | 依使用者新要求獨立視窗，保留列表／詳情；正式技能成本／效果及施放未完成 |
| 配點 | ui/attribute_points_ui.py；570×505 | 已新增五屬性列、加減／預覽入口；基礎屬性投影、本機加點預覽與確認未接 |
| 組隊／必要隊員 | ui/services_ui.py、party_guard_ui.py；950×620 | 已新增成員／申請表與右側四人草稿；核心隊伍／請求唯讀；候選玩家、規則儲存與全部操作未接 |
| 夥伴出戰 | ui/companion_ui.py；1040×650 | 已新增六欄列表與出戰／休息入口；核心夥伴唯讀；選取詳細能力與操作未接 |
| 遠征 | ui/expedition_ui.py、expedition/panel.py、controls.py、task_list.py、task_detail.py、team_view.py、planner.py、settings.py；1080×650 | 保留既有三欄、草稿與換帳隔離；資料目錄、實際派遣／領獎未接 |
| 副本／協力主頁 | ui/instance_ui.py、instance_catalog_ui.py、instance_room_list.py；features/dungeon/panel.py、cooperative/panel.py；1040×600 | 已新增兩頁、目錄／房間欄、獎勵入口；完整目錄／房間投影及動作未接 |
| 建立／加入副本房間 | ui/instance_room_dialogs.py；建立470×315／協力470×355 | 子對話框尚缺；公開／私人密碼、次數與可加入限制不得用假的可操作表單取代 |
| 福利：魔方／每日／每週／每日助手 | ui/benefits_ui.py、daily_tasks_ui.py、daily_assistant_ui.py；860×620 | 已新增四頁、選項／額度、任務表；魔方收到狀態可顯示；任務／獎勵完整投影與助手套用未接 |
| 其他：方舟／組織 | ui/other_features_ui.py、star_ark_ui.py、guild_actions_ui.py；1080×740 | 已新增兩頁、事件／題目／捐獻額度表單；核心狀態文字可顯示；事件列表／題目／費用及套用未接 |
| 煉金 | ui/services_ui.py；1040×650 | 已新增五材料列、次數及狀態側欄；清空本機選取可用；材料資格與技能／消耗投影未接 |
| 製作主頁 | ui/crafting_ui.py、crafting_browser.py、crafting/catalog_grid.py、recipe_detail.py、item_icons.py、icon_cache.py；功能入口1080×650，獨立 browser1160×700 | 已新增設備／配方／詳情三欄及子視窗入口；正式圖示格、收藏／搜尋、材料與可製作判斷尚缺（目前以空表標示，非宣稱同版） |
| 自訂製作清單 | ui/crafting_plan_ui.py；900×580 | 已新增列表與操作位置；本機增刪／排序／匯入匯出及排程接線未完成 |
| 製作排程 | ui/crafting/queue_view.py；820×420 | 已新增進度及核心佇列唯讀；時間投影、重排與開始／停止未接 |
| 經驗效率 | ui/efficiency_ui.py；960×610 | 已新增對象／單位、進度與統計表；經驗與升級時間投影、重設未接 |
| 自動戰鬥／補給／維修／停止條件 | ui/auto_battle_ui.py、auto_battle/model.py、rule_card.py；1080×720 | 保留既有五頁、本機設定匯入匯出；細部規則卡／真實資源與 automation 接線未完成 |
| 行動／條件編輯、補品／維修物品挑選 | ui/auto_battle/action_editor.py；960×640；recovery_ui.py 720×540、maintenance_ui.py 680×520 | 現有簡化行內編輯不等同這些子視窗；專用挑選／驗證流程仍缺 |
| NPC 資訊、商店價格、互動選項、對話紀錄 | features/npc/panel.py；560×320、680×475、520×360、560×360 | 四個子視窗尚未移植；不得從空清單或未知資料開啟遊戲交易 |
| 傳點位置預覽、逐圖／全場景核對 | features/portals/panel.py；730×460、1000×600、980×620 | 三個預覽／核對子視窗尚缺，導航主視窗不能代替 |
| 啟動器下載／安裝進度 | launcher_progress.py | Python launcher 專屬；Avalonia packaging 已有獨立流程，未重製相同啟動器介面 |
| 系統檔案挑選、確認／錯誤提示 | 各頁 filedialog／messagebox；theme.py、theme_surfaces.py、theme_styles.py、window_layout.py、rounded_notebook.py | 現有 Avalonia 原生 picker／風險 modal；字型度量、鍵盤焦點、DPI、主題邊界仍需 Windows／macOS 實機核對 |

其他 UI 支援模組（session_bridge、session_event_coordinator、event_queue、connection_status、display_time、portrait_rows、button_art、function_icons、automation_control_icons、instance_menu_icons、halo_button、feature_navigation）不是額外畫面；其行為分別歸入上表的生命週期、時間顯示與素材／入口項。原封包檢查器為 C# 額外入口，不算 Python 等價畫面。

## 驗證與後續順序

- 本批實測：Release build 0 警告／錯誤；Desktop 離線 63；原生 Avalonia UI 206（28 張截圖）；新增 catalog UI 9；loopback 登入 11（最後 Stop 清理修正再跑 UI 150，未重產截圖，另加 catalog 9／loopback 11）；Core discovery 136；Python 發行／倉庫檢查 15，全部通過。全部測試只使用合成資料，不連正式服／官方 HTTP，不輸入真帳密。
- UI 測試涵蓋每個新增視窗單實例、換帳重建、所有缺漏操作停用提示；新增登入測試涵蓋群組／分流、切換清密碼、未知設定、過期／失敗清單及取消等待。
- Python 參照曾以隔離儲存、停用帳密載入、禁止 socket 連線實際建窗；Linux Tk 字型渲染不完整且截圖關閉有 Tcl cleanup 錯誤，因此只能支持建窗與尺寸檢查，**不能作為完整視覺一致驗收**。Avalonia 截圖亦不證明與 Python 每一格相同。
- 接續優先：完整資源 gate（版本與唯讀檢查入口已補）→ 既有頁完整資料投影與本機編輯 → 製作圖示網格／配點／效率 → 房間／NPC／地圖／設定子視窗 → 各平台視覺、焦點、縮放與可及性。不得只補停用按鈕後宣稱全介面完成。
- 真實登入與遊戲送出不屬於本輪驗證；一般遊戲動作仍停用，正式服驗收須另由使用者知悉風險後手動操作。

## 同批圖示修正

標題列移除功能圖 `MainIcon_041.png`，直接解碼既有 `app.ico`；原生 WindowIcon
及 Windows ApplicationIcon 使用同一來源。實際 win-x64 publish 的 PE 原生圖示
7 個圖框逐一與 ICO 位元組比對通過，CI 已加入相同檢查。沒有重新編碼或另製圖案。
C# 尚無安裝器／捷徑／Linux desktop entry／macOS bundle 產生器，未驗收這些產物。
Python Nuitka／macOS 既有打包命令已引用 app.ico，本批未重打包 Python。

## 8.0.43 資源入口接線與驗證

`VersionWindow` 是正式啟動入口，1000×710；結果、官方版本、本機資料庫、資源啟用限制及
程式更新區塊依 Python 版本畫面順序安排，底部按鈕固定、內容可捲動。版本與 Package
只顯示本次查詢值，不把發行設定或本機檢查結果當成已安裝官方版本。

使用者選目錄後以背景工作呼叫 `ResourceInventoryInspector.InspectAsync`，固定讀取
`official_sync/derived_catalogs/resource_inventory.sqlite3`；沒有目錄掃描、下載、建立／
修復資料庫或帳密讀取。缺檔、損壞、無法讀取和自洽分開顯示。取消、關閉與重試
串行管理；停止等待來源／檢查返回，取消後無晚到准入。

進入登入僅代表已取得新鮮且支援的 metadata。登入頁會重新取得清單並要求使用者
選擇伺服器／分流，不重用過期端點；仍不是 Python 的完整資源就緒 gate。未連正式服。
完整下載／資源啟用、背景版本 observer、程式更新、自動增高與各平台原生 picker
仍待接入／驗收，不能從此入口推定整套 UI 已對齊。

本批驗證包括缺檔不建目錄、損壞合成 SQLite 不覆寫、版本欄位顯示、失敗撤銷、過期阻擋、
停止等待與窗口路由；合成自洽結果亦不單獨啟用登入。Core discovery 136、資源 bootstrap／
inspection 201、Desktop 離線 63 通過。原生 UI 224（29 張截圖）、catalog UI 9、loopback 11 與 Python 倉庫／發行 15 通過。CI 以 PR 本批驗證紀錄為準。

## 8.0.44 登入後資源準備

已從選定資料目錄接入真實 `AccountRuntime.CreatePrepared`；資源範圍與兩次帳密傳送
分別確認。Core 完成官方取得、SQLite 回讀／來源重查後才綁定當前帳號目錄，Desktop
同步物品／場景名稱及綁定／失敗狀態，撤銷時清除。完整流程與證據見
[Desktop 資源接線](DESKTOP_RESOURCE_INTEGRATION.md)。這不是全部圖資啟用或 Python
登入前完整 gate；前節 8.0.43 的未接線描述是歷史狀態，以上述本批範圍為準。

## 8.0.45 登入前必要資源

官方 metadata 不再足以開啟登入；先明示確認下載／寫入，由 Core 準備必要表、SQLite 回讀和來源重查，再以新清單精確比對 exe／data／Package。停止撤銷並等待資源釋放，登入後仍獨立重查。圖資未啟用：Core 缺 Sprite／Texture2D 圖像解碼及 Python 圖片資料庫的來源／像素／快取驗證橋接，詳見 [實際流程與相依差距](DESKTOP_RESOURCE_INTEGRATION.md)。

## 8.0.46 圖像候選解碼

Core 已有受限四格式 Texture2D 像素／矩形 Sprite 裁切與像素快取比對，但沒有 production 圖片抽取或 UI 啟用。class 28／213 精確解析、PNG／SQLite、同版來源重查及映射仍缺；所有圖資狀態維持未就緒。

## 8.0.47 精確 SerializedFile 圖像解析

已補上固定型別樹的 Texture2D／Sprite 解析與同檔指標核對，從驗證 Bundle 到像素候選可做離線整合測試。未接 production 圖資 publication；PNG／SQLite、實際官方格式覆蓋、四類圖片映射與 UI 啟用仍缺。維持未就緒狀態。

## 8.0.48 離線 PNG／SQLite 快取

已加入固定 RGBA8 PNG 編碼與獨立 SQLite cache，輸入必須為同版本／來源集合的精確候選清單。每次讀取重新對照完整 context、texture payload／像素雜湊及由獨立候選重建的 PNG 位元組；不以資料庫自存 hash 證明正確。限制單圖 512×512、8,192 張及合計 96 MiB；來源重查與取消在提交前執行，交易失敗保留既有資料。回傳僅是離線 PNG，不是 production publication。

PNG 使用固定 stored DEFLATE 區塊，避免執行不可信快取的通用解壓；不是 Python PNG 編碼或 SQLite schema 相容層。Pillow／zlib 獨立解碼證據涵蓋最小尺寸、跨區塊與最大尺寸；自有 Bundle→候選→SQLite→重新開啟回讀有整合測試。官方來源取得與重查 owner、item／portrait／emoji／smallmap 映射、可撤銷 publication、UI 與實際官方格式覆蓋仍待接入，HasVisualAssets=false。

8.0.47 CI 維持未驗證；8.0.48 需在推送後核對精確 head，不沿用歷史綠燈。

## 8.0.49 物品圖 MainPackage 來源與映射基礎

核對 Python item_image_database.py／dynamic_bundle_runtime.py 後，新增 MainPackage 精確物品圖清單及模型映射：s1000 預設圖不可缺、模型不得重複、未知物品或缺圖回退 1000；ItemData 必須提供 ReviewedDetails，舊版未知圖示欄位不猜測。映射包含圖示、寬高及 open_used，與 manifest SHA256 一起形成輸入指紋。

Bundle 計畫沿用 YooAsset 完整依賴集合語意，不遞迴擴張；上限 4 個 Bundle／32 MiB。取得沿用既有受限來源、版本／manifest、checksum 及 attempt 機制，並共享必要資料的總下載／保留額度；比 Python 分開圖資額度更保守，沒有增加總配額。以檔名為鍵的既有已持有來源遇到不同 package／spec 一律拒絕，不能跨 package 誤用同名檔。

本批為內部計畫／取得與唯讀映射層，尚未由 production owner 自動呼叫；未宣稱實際官方圖片成功解碼。後續仍需將每圖來源閉包、完整批次來源與映射指紋接入 PNG／SQLite，再接 owner 的版本撤銷及 UI。四類圖資、正式格式覆蓋、可撤銷 publication 與 UI 未完成，HasVisualAssets=false。

## 8.0.50 物品圖 production 準備、撤銷與桌面顯示

已將物品圖條件式接入 production 資源準備：ItemData 必須有經審閱的圖示欄位，MainPackage 必須含精確圖示清單；未知欄位、未支援格式或來源取得失敗時不產生圖片候選。下載仍共用原有總額度，圖片閉包維持 4 Bundle／32 MiB，不增加帳密或遊戲傳送權限。

每個 Bundle 在整批只解析一次；每張圖仍僅能在 manifest 指定的 root＋完整依賴集合解析同檔 Sprite／Texture 指標。整批指紋包含版本 identity、manifest、映射／尺寸／open_used、全部 Bundle specs／SHA256 與每圖依賴；不同依賴的圖片可共同寫入快取，沒有降低逐圖來源驗證。整批像素／PNG 預算維持 96 MiB。

owner 將完整批次寫入固定 core_item_images_v1.sqlite3，關閉後重新開啟只讀比對全部 PNG，再重查遠端版本／manifest，清理完成後才建立圖片 publication。寫入前重查來源、commit 前檢查當前 attempt；遠端版本與本機交易無法原子化，寫入後來源變更仍會拒絕發布。必要資料庫與圖片庫不是跨庫交易，圖片寫入另回報 NotAttempted／NotCommitted／Committed／Unknown，停止不回復既有寫入、不自動重試不明結果。只讀 refresh 不建立缺少的圖片快取；圖片庫損壞或寫入失敗目前會阻擋本次 owner 發布，保留結果供確認。

圖片讀取沿用 ResourceRuntimeActivation 及帳號快照，逐次核對 owner／publication／generation；回傳僅為呼叫者擁有的歷史 PNG 副本，不能作為後續操作權限。停止、版本／帳號切換與釋放撤銷讀取。桌面背包及儲藏格每次刷新重新取得圖片，欄位未改變時也會處理圖片更新／撤銷；關閉與撤銷清除 Bitmap 並釋放。原生解碼前檢查 PNG header／尺寸上限；缺圖維持名稱與未通過驗證狀態。資源確認視窗新增圖片庫路徑及寫入結果。

測試只使用自有合成 Bundle／PNG、SQLite 與 loopback。owner 正向持久化測試使用明示 offline image hook，撤銷測試沿用 white-box publication seam；這些都不能證明官方來源正向驗收，production 建構不接受 hook／來源注入。原生 UI 測試發現「庫存不變便跳過重繪」會漏掉圖片撤銷，已修正並新增顯示／失敗／清除檢查。

**仍未完成**：實際官方圖片格式正向驗收、更多 Texture／Sprite 格式、頭像、表情、小地圖及 Python 全介面一致。HasItemImages 反映當前物品圖狀態；HasVisualAssets 仍為 false，不冒稱全圖資完成。既有帳密逐次確認、無 TLS／XOR 可逆提示、停止等待清理及一般遊戲操作 Held 均保留。

## 8.0.51 低資源優先目標

低 SP 補品與友方技能按 SP 排序，低 HP 按 HP；門檻仍是絕對值且嚴格小於。
保存的 target 1／2／3 不變，友方含義為最低資源／座標／最高資源。
敵方技能仍走原 HP／屬性目標邏輯；基本普攻的 2 原本是最低 HP，介面明示。
防禦／逃跑無目標；原有設定值保留但選單停用。次階技能按最終 TargetKind 分類。
友方技能不等於補 SP；本機只有原始 SkillData 欄位與消耗，沒有可靠恢復量分類。
本批沒有以不明 FightWay 或 Variable 欄位新增自動恢復技能。

依使用者附圖，HP < A → B 技能與 SP < C → D 技能分列保存；角色／夥伴各自獨立。
保留嚴格小於和兩條件同時成立時先 HP 的既有順序。舊 JSON 不需遷移。
測試資料皆為合成，沒有正式服驗收或真實遊戲發送。

最終原生驗證：Avalonia Release 零警告／錯誤；UI 240 項、31 張截圖，SP < 門檻行動視窗已目視檢查。
Desktop 離線 76 項（presentation 67＋inspector 9）；公開 consumer、Tk 原生編輯器及模型 6 項、倉庫／發行 15 項通過。
