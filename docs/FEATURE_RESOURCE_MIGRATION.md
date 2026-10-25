# 全功能官方資源遷移盤點

盤點起點為 main `14af2ff` 與 PR #57 `cb9e9a77`，程式版本維持 v0.6.1。
功能歸屬依 [features.json](../architecture/features.json)，完整靜態引用見
[inventory.json](../architecture/inventory.json)。表中的路徑使用舊公開 API 名稱，
搬遷後仍應保留相容入口；實際實作位置由功能對照表決定。

此文件記錄來源與尚缺的遷移條件，不把資料下載、解析成功或目錄搬遷視為正式服驗收。
未符合移除條件的檔案與使用者資料均保留。模組搬遷不會自動將 1262 資料改標為 1275。

## 官方來源與共用驗證流程

主要路徑是 Launcher 的官方更新流程：

1. `official_resource_sync` 觀測官方版本；`official_manifest_sync` 驗證 `.version`、`.bytes`、`.hash`。
2. `official_incremental_sync` 與 `official_bundle_download` 只補齊明確列出的 Bundle 及依賴，核對官方 MD5／CRC 與版本化私人收據。
3. `bundle_runtime_1275` 以已審核的雙 Manifest SHA-256、確切資料表名稱與 Schema 建立 Runtime；`runtime_1275.active_runtime()` 對外提供已驗證來源。
4. `auto_catalog`、分類索引及候選索引是診斷／唯讀預覽。只有通過獨立正式來源核對的資料才可進入原有 Runtime；它們不能自行授權登入、交易或物品使用。
5. 網路命令仍須通過當前角色、房間、背包、保留量與伺服器回覆檢查。資料版本相符不能取代協定驗證。

`runtime_1275` 同時保留已驗證私人正式 ZIP 的相容讀取，但 ZIP 不是使用者啟動功能前必須自行準備的唯一來源。
不要新增「先上傳遊戲 ZIP 才能使用」的前置要求，也不要把完整官方 Bundle 加入公開程式碼提交。
必要的版本化本機快取、個人設定、UI 圖示與登入記憶不屬於可以一律刪除的舊離線表格。

目前固定 Bundle Runtime 的明確必要表包括 `Eve`、`ItemData_C`、`TalkData_C`、`TextData_C`、
`SmithData_C`、`ScenesData_C`、`AdventureData_C`、`AdventureLvData_C`、`NpcData_C`、`NpcCareerData_C`。
尚未列入且未審核的其他表格，不能只因 Manifest 中找得到名稱就宣稱已完成替代。

## 每功能的消費者、替代來源與保留條件

| 功能 | 舊檔與主要消費者 | 已存在的官方／權威來源 | 保留缺口與移除前條件 |
| --- | --- | --- | --- |
| `instances` 副本共用房間流程 | `instance_catalog_1262.json` → `instance_browser.official_catalog()`；`instance_ui`、創房／開始規則共用目錄 | S85／S186 房間、成員、階段與獎勵回覆；Runtime 已解析部分 `ScenesData_C` | 1262 目錄仍被讀取。尚無已完成審核的 1275 Dungeon／Cooperate 目錄替代，不能刪檔或用新版場景 ID 猜房間規則。 |
| `cooperative` 協力 | 與一般副本共用 `instance_catalog_1262.json`；`instance_creation`、`instance_room_flow`、`instance_standby`、`instance_rewards` | S186 權威房間與寶箱狀態；背包可靠同步及共享保留量 | 須同時遷移一般副本消費者。新目錄須核對關卡、人數、等級及獎勵參照；寶箱權限仍只接受伺服器證據，付費與未知獎勵不推測。 |
| `dungeon` 一般副本 | 同一 `instance_catalog_1262.json`；`instance_start`、`instance_entry`、房間詳情 | S85 房間／成員／開始／進場／結算回覆；正式 Runtime 的場景存在性 | 官方完整副本目錄、最低／最高人數及創／入房欄位仍須獨立驗證。沒有全部來源與協力消費者歸零前保留舊檔。 |
| `minimap` 小地圖與導航 | `smallmaps.zip`、`navigation_data.zip`、`map_names.json`、`stage_coordinates.json`、`graph_origins.json` → `SmallMaps`、`Repository`、`Coordinates`、`map_names`；`obstacle_scope` 也讀場景表 | Runtime 有經驗證 `ScenesData_C`／`TextData_C` 來源，伺服器提供角色定位 | 此基準仍直接讀舊名稱、圖片、網格與座標檔。名稱可個別接入已驗證新表；圖片、投影、完整可走網格及動態障礙沒有可直接宣稱等價的替代。名稱更新不能授權行走，也不能刪除圖像／導航檔。 |
| `npc` NPC／對話／商店 | `npc_event_index_1262.json.gz`、`npc_interact_1262.json.gz`、`npc_talk_1262.json.gz`；`npc_text_1262.json.gz`、`npc_battle_talk_1262.json.gz` 由 `npc_localization` 讀取；商店另用共享物品資訊 | 無參數 `NPCIndex`、`NPCInteractIndex`、`npc_talk.load_catalog` 在 1275 使用 `active_runtime()`；`npc_item_data.item_catalog()` 正式路徑使用新 ItemData | 不可把所有 NPC 檔視為已無消費者。`npc_localization` 的一般／戰鬥文字路徑仍讀已校驗 1262 檔；須核對新 `TextData_C`／`NpcTalkData_C` 語意及所有顯示消費者。顯式歷史測試匯入器和正式執行期要區分。 |
| `portals` 傳送點 | `portals.json`、場景名稱／座標檔 → `Portals`、`portal_policy`、`portal_travel` 與地圖顯示 | 1275 `Eve` 的 NewDoor 索引已固定來源解析 | 1275 預設 `Portals` 不將 1262 出口清單用於新封包，且對未核定目的地／條件保持唯讀。尚無完整目的地、觸發與正式服回覆證據，舊檔及歷史測試需保留。 |
| `accounts` 帳號／登入／角色／版本 | `default_profile.json`、`server_list.json`、`lala_supported_resources.json`；`storage.defaults`、`server_lines`、登入及版本控制器 | 官方線上版本觀測、受支援版本宣告、共享 `game_version_gate`；角色清單來自伺服器 | 個人帳密設定、帳號設定鍵、角色／線路選擇不是遊戲靜態表，不遷移為官方下載資料。未知版本、來源不完整或資源校驗失敗保持拒絕。保留 Windows 登入記憶保護與 PR #57 Tk 修復。 |
| `overview` 主頁／目前活動 | 直接使用 State snapshot；夥伴顯示名稱經共享 `CAT['npcs']`；背景、按鈕圖片屬 UI 資產 | 角色、活動、戰鬥、遠征與製作狀態由原共享 State 更新 | 舊 NPC 名稱顯示仍是間接消費者。替代名稱需有正式新資料與缺資料提示；不能把 snapshot 摘要當作操作完成。UI 藝術資產不因功能搬遷刪除。 |
| `party` 隊伍／必要隊員 | 房間外隊伍資料由伺服器同步；必要隊員設定為私人本機檔，無專屬 1262 表格讀取 | 權威隊伍成員與隊長回覆，既有權限／活動檢查 | 保留私人必要隊員清單及帳號隔離；不能用附近玩家／公會名單替代隊伍成員。無舊資源刪除項。 |
| `companions` 夥伴出戰 | 操作依 `knowledge.companions`；`companion_ui` 的名稱可間接讀 `combat_catalog.json` 中 NPC 項目 | S19 等現有身分／出戰同步；正式 Runtime 有部分 NpcData／NpcCareerData 遠征資料 | 顯示名稱替代可與 NPC 名稱遷移；動作身分仍須來自伺服器，不可從目錄猜相同 NPC ID 的實例格位。共享戰鬥目錄尚不能刪。 |
| `attributes` 能力配點 | 無專屬資源檔；現有 EAttribute／上限常數基於已解析 Lua 協定 | S5／S8 能力與剩餘點數回覆、既有配點 pending／uncertain 狀態 | 協定常數不是已審核 1275 DataPackage 的替代成果。保持角色同步、範圍與結果確認，不因資料搬遷放寬。 |
| `battle` 戰鬥／AI／設定 | `combat_catalog.json`、`normal_attack_data.json`；`items.catalog.CAT`、`combat_resources`、`battle.combat.DATA`、AI 模型 | 現有戰鬥／回合／技能學習與單位回覆；正式 Runtime 的 ItemData 僅已審核部分顯示／交易欄位 | `CAT` 的技能、NPC、裝備、恢復效果與普通攻擊仍存在舊靜態消費者，未完成 1275 效果／技能 Schema 等價替代。不能從物品名稱或價格欄位推導效果，也不能只換版號即允許未知動作。 |
| `expedition` 遠征 | `expedition_catalog.json` 的歷史／顯式載入入口；共用 `CAT`／背包與私人遠征設定 | `load_active_catalog()` 在 1275 使用正式 Runtime 的 AdventureData／AdventureLvData／NpcData／NpcCareerData／TextData，核對固定 SHA 及筆數 | 正式派遣不應以 `load_catalog()` 歷史入口或候選目錄作 fallback。剩餘歷史入口、測試、打包必要清單尚有消費者；保留檔案。恢復物品作用欄位仍受共享 ItemData／效果審核缺口影響。 |
| `alchemy` 煉金 | `alchemy_catalog.json` → `alchemy.META`；`combat_catalog.json` 的物品種類與效果；背包格位 | 原有背包／扣除／結果協定與保留量；正式 Runtime 有部分 ItemData 欄位 | `META` 目前仍於匯入時讀舊目錄，不能宣稱新 ItemData 已覆蓋煉金種類、限制與計算規則。需完整欄位核對、效果測試與結果確認後才可切換或刪檔。 |
| `crafting` 製作／排程 | `crafting_catalog.json` 初始 `RECIPES`；物品圖示 `item_icons.zip`、`item_icon_map.json`、`item_icon_coverage.json`；共享物品及家具資料 | 正式 Runtime 的 SmithData／ItemData 經 1,032 配方交叉校驗後原地更新 `RECIPES`；S64 排程與 S62 家具狀態 | 配方已有正式替代路徑，但初始化、舊版測試、圖示與共享消費者仍在。圖示不能假設由 SmithData 自動取得；器具／夥伴加速規則與實際排程屬獨立驗收。 |
| `inventory` 背包／超空間袋 | `item_stackable.json`、共享 `combat_catalog.json` 與物品圖示；背包欄位／說明在 `bag_grid` 使用 | S23 背包可靠快照／增減；S62 儲存槽資料；`verified_item_metadata()` 可提供正式 1275 名稱、價格、限制、需求等級與 open_used | 堆疊、完整效果、裝備及圖示尚有舊消費者。正式 ItemData 顯示欄位不能取代格位身分、數量和保留量；不清空使用者背包設定或快取。 |
| `supply` 補給 | 經 `combat_resources.heal_effects` 消費 `combat_catalog.json`，並使用背包可靠資料及藥水槽 | 既有 S23 藥水槽／背包更新與恢復結果；共享正式物品顯示來源 | 1275 Runtime 尚未宣稱提供完整已核准 HP／SP 效果表。恢復物品不能從名稱猜測；先核對效果 Schema，再更新所有補給、AI、遠征等共用消費者。 |
| `maintenance` 修理／戰後整理 | 共享 `combat_catalog.json` 的物品類型／效果／適用條件；私人修理／整理設定 | 現有背包耐久／扣除、修理／販售等已支援回覆與保留量控制 | 舊物品 metadata 仍參與物品選擇。新效果與裝備欄位未完整核定前保留來源；pending／uncertain 不能透過換資源或重登推定成功／自動重送。 |
| `chat` 聊天 | `emoji_catalog.json`、`emoji_images.zip` → `chat_emoji`；名稱由伺服器與私人聊天歷史取得 | 現有 S2 聊天協定與已同步對象名稱 | 表情映射與貼圖需有官方同版本等價來源才可替換；文字協定、限制與 UI 資產不是可刪的離線遊戲規則表。不自動對外發訊息。 |
| `social` 社交／公會 | 無專屬靜態表；`guild` 解碼既有 S39 已支援形態 | 伺服器公會名單、成員更新及名稱同步 | Lua 衍生協定結構不因官方資料更新自動證實新版所有形態。未知協定拒絕，沒有資源檔刪除項。 |
| `efficiency` 經驗效率 | 無專屬資源檔；夥伴名稱經共享 `CAT['npcs']`；經驗預估採現有 EXP_Monitor 參考公式 | 已完成戰鬥／角色能力／經驗快照及有界歷史 | 參考公式是估計，不是已核准官方 1275 成長表。名稱可接新來源；不能把估計升級時間當權威資料，不刪個人紀錄。 |
| `resources` 官方資源／相容性／檢視 | `lala_supported_resources.json`、`resource_manifest.REQUIRED_RESOURCES` 及上述所有必要檔；各打包與 self-test 消費者 | 共用 Manifest／Bundle 驗證、Runtime、版本隔離收據、原子快取與來源診斷 | 保留單一共用驗證服務。新版本未知、固定 SHA 不符、Schema／筆數不符或候選未審核時拒絕；不以 UI 分類數量當資源完成。刪舊檔時要同步必要清單與原生打包規則。 |

## 本次盤點確認的剩餘舊來源

以下是起點版本實際存在的讀取，並非「全部功能已使用 1275」：

- `instance_browser.official_catalog()` 固定讀 1262 副本目錄；一般／協力房間 UI 與行為檢查共用。
- `map_names.data()` 固定讀舊名稱，`Coordinates`、`Repository`、`SmallMaps` 仍有舊座標／圖像／導航來源；`obstacle_scope.known_scenes()` 亦使用舊場景集合。
- `items.catalog.CAT`、`alchemy.META`、`battle.combat.DATA` 於模組初始化讀本機目錄。`runtime_1275.ready()` 已啟用新製作配方，不代表已原地替換這三種共享資料。
- `npc_localization` 的一般文字／戰鬥台詞仍有獨立 1262 載入器；不能只觀察 NPC 對話入口已遷移就刪除兩份來源。
- `item_display_name()` 的歷史名稱 fallback 只影響 UI，正式 `verified_item_metadata()` 缺資料回傳 None。這兩者的語意必須維持分離。

對操作敏感的舊效果表、普通攻擊表、煉金規則與副本規則，這次盤點沒有足夠來源可將其直接重新標示為 1275。
此文件也不宣稱現有所有操作均已通過新協定 E2E；重構階段需保留現有權威回覆／安全檢查，並把新資料遷移作獨立驗收。

## 移除任何舊檔之前的共同門檻

1. 找到具有明確版本、Manifest／Bundle 指紋與欄位語意的正式來源；從乾淨安裝能透過既有自動官方流程安全重建。
2. 核對全部消費者，包含共用 `CAT`、匯入時常數、延遲匯入、圖片、診斷、self-test、原生打包與歷史相容測試；靜態搜尋零引用不足以單獨批准刪除。
3. 所有正式消費者已遷移且資料完整；未支援版本與缺資料保持拒絕，不能出現新舊資料混用或默默回退。
4. 通過功能測試、跨模組整合、Windows／Ubuntu／macOS CI 及該功能必要實機驗收；未執行 E2E／原生打包個別記錄為待驗。
5. 才能在同一可審查變更中移除舊檔及 `REQUIRED_RESOURCES`／打包宣告；不得刪除使用者設定、私人驗證快取、帳密或官方安裝內容。

本輪資源刪除核准項目：**無**。後續接入官方等價來源時，需更新此文件的對應功能與驗收證據。
