# Phase 0：桌面版現況盤點與重製輸入

> 盤點基準：`main`，桌面版版本 `v0.6.1`；參照提交 `2dd6694b46e22e6e0102195036a859e3720a083c`。
> 本文件是 GitHub 原始碼靜態盤點，不代表本回合已執行測試、打包或正式伺服器驗收。
> 舊版只作為行為、協定及資料來源的證據，不作為新產品 UI／架構的直接模板。

## 1. 盤點摘要

| 項目 | main 現況 | 對全新 LaLa 的決策 |
|---|---|---|
| 程式入口 | `WLRE_Client.py` 啟動 Tkinter GUI；`wlre/__main__.py` 提供 CLI／實驗性 live client | 新版入口與啟動生命週期獨立，不把舊 GUI 當成新 UI |
| UI 技術 | Tkinter／ttk、Pillow；Nuitka 打包腳本與 GitHub Actions | 先做技術驗證與設計系統，不在 P0 直接定案新 UI toolkit |
| 內部模組 | 已有 `wlre/core`、`network`、`services`、`features`、`ui`、`storage`、`resources` | 既有分層是可查證參考，不代表依賴已完全隔離；新架構以明確 contracts 重建 |
| 專案規模 | 583 個 tree entries、438 個 Python 檔案、169 個測試 Python 檔、43 個 Markdown 檔、3 個 Actions workflow | P0 的工作是利用既有清單並找出缺口，不再重複造一份逐檔 AST 清單 |
| 版本／資源 | README 與 `wlre/__init__.py` 標示 `v0.6.1` 開發版；官方資料版本與客戶端協定相容性是不同判斷 | 保留資源信任閘門；資料可解析不等於協定或正式服功能已驗證 |

## 2. Battle（戰鬥）責任與依賴

### 現有程式位置

- UI：`wlre/ui/battle_view.py`、`wlre/ui/auto_battle_ui.py`、`wlre/ui/auto_battle/`。
- 核心／事件：`wlre/core/state_battle_events.py`、`wlre/core/state.py` 與狀態事件路由。
- 領域服務：`wlre/services/battle/attribute_points.py`、`auto_battle.py`、`battle_commands.py`、`combat.py`、`companions.py`、`party.py`、`party_guard.py`。
- 跨功能相依：`wlre/services/items/combat_resources.py`、`items/recovery.py`、`items/reservations.py`、`services/coordination.py` 及戰後維護。自動戰鬥不是獨立 UI 元件，會依賴角色狀態、耗材預留和其他自動化工作協調。
- 測試涵蓋自動戰鬥、隊伍守衛、戰後補給及狀態事件等多個模組；測試檔存在不代表每個戰鬥操作都已有正式伺服器 E2E 證據。

### 新版 P0 必須補齊的行為規格

1. 戰鬥進入、戰鬥中、勝敗／逃離、戰鬥結束與重新登入的狀態轉移。
2. 角色／夥伴／敵方單位快照、目標與技能選取的資料來源和有效性條件。
3. 每個輸出指令的前置條件、封包來源、回覆／事件、逾時、重連及結果不明處理。
4. 手動操作與自動戰鬥的互斥／優先權、啟停、取消、耗材預留和避免重複發送規則。
5. 部分／截斷／未知戰鬥資料的拒絕或降級行為，以及 UI 的「等待確認／失敗／結果未知」狀態。

## 3. Map（地圖）責任與依賴

### 現有程式位置

- UI：`wlre/ui/home_map.py`、`minimap.py`、`feature_navigation.py`、`navigation_gui.py`。
- 可拆分的功能元件：`wlre/features/minimap/`、`wlre/features/portals/`。
- 領域／服務：`wlre/services/world/display_position.py`、`map_names.py`、`navigation.py`、`portals.py`、`portal_policy.py`、`portal_travel.py`、`smallmaps.py`。
- 本機資料包含 `map_names.json`、`smallmaps.zip`、`navigation_data.zip`、`stage_coordinates.json`、`graph_origins.json`、`portals.json`。每種資料有不同來源及版本假設，不能把「檔案存在」當成「路徑／傳點正確」。
- README 的 1275 說明已明確指出，場景／門連結及資源解析進度不等於完成所有地圖導航或正式伺服器換圖 E2E；未知導航資料及傳點仍須受到安全政策限制。

### 新版 P0 必須補齊的行為規格

1. 地圖／場景 ID、角色座標與伺服器更新的權威來源；UI 點選座標與封包座標間轉換。
2. 地圖投影縮放、圖片缺漏、座標無效、場景切換與版本不匹配的行為。
3. 移動請求、停止移動、路徑失效、斷線與背景工作取消的順序及狀態回復。
4. 傳點資料來源等級、目的地合法性、伺服器確認與結果未知處理。
5. 以來源證據決定每個場景／傳點是否可用；未驗證項目只能顯示不可用／未知，不得自行補座標。

## 4. 封包規格及既有重製工作

桌面版已存在兩個可重用、但尚未合併的工作，重製時要整合其成果，避免另外建立相互矛盾的規格：

- [PR #58：重建 LaLa 主程式核心與模組化架構](https://github.com/blesses0603/WLRe_lala/pull/58)：分支內包含 `docs/rebuild/main_inventory.json` 與 `docs/rebuild/FILE_MAPPING.md`。檔案對照文件明確註明它是目標責任分配，**不是代表已完成移植**。PR 本身也包含漸進式核心骨架／相容性工作，因此不能視為全新 UI 與所有功能已重製完成。
- [PR #60：新 LaLa Phase 0 封包規格與 golden packet](https://github.com/blesses0603/WLRe_lala/pull/60)：分支內 `next/spec/behavior/`、`next/spec/golden/` 和獨立 `verify_golden.py` 可作為跨語言行為規格起點。其規格 README 明載目前案例沒有 `official_lua` 或 `live_capture` 級別；reference implementation／synthetic 案例只能驗證規格自洽與邊界處理，不能當成官方協定已逐項核實。
- 因此不要重寫另一份互不相容的 wire/login 規格。下一步應把 Battle／Map 的必要事件及命令，依同一來源分級補進規格與案例，再由新版實作獨立通過 golden tests。

## 5. 主要風險與處理原則

| 風險 | 盤點結論 | P0/P1 處理 |
|---|---|---|
| 舊 UI 與領域／網路責任交錯 | `home_map.py` 組合地圖、導航、NPC 及傳點互動；協定模組也會匯入多個服務解碼器 | 新版先定義 UI → Application → Domain → Protocol 的單向依賴，不搬移整個舊 UI 檔案 |
| 舊資料混有多版本來源 | 地圖／圖示／導航等資源分散於 JSON、ZIP 及執行期解析器 | 每個資源記錄版本、來源、雜湊、schema 與可信度；不可用舊資料無提示 fallback |
| 「測試通過」容易被誤讀 | 舊 repo 有大量單元／GUI 測試；PR #58 報告的 CI 與正式服 E2E 是不同層級 | 測試報告需分別標示單元、整合、GUI、打包、實機與正式服 E2E |
| 協定案例仍有來源缺口 | PR #60 目前案例來源分級不足以證明官方一致 | 針對高風險操作優先取得官方 Lua 對照或脫敏實機證據；沒有證據就保持禁用 |
| 跨平台共用核心可能漂移 | Android 另有自己的 `wlre` 副本，需明確定義共用界線 | 只共用已界定的協定／領域 contracts 和測試資料，桌面 UI／執行緒生命週期留在平台端 |

## 6. Phase 0 交付狀態

| 工作項目 | 狀態 | 證據／下一步 |
|---|---|---|
| 桌面原始碼與測試規模盤點 | 已完成靜態統計 | 以本文件的 main 基準為準；未在本回合執行程式測試 |
| 逐檔依賴／API 對照 | 有可重用成果，待審查整合 | PR #58 的 `main_inventory.json`、`FILE_MAPPING.md` |
| wire／login／基本 session golden cases | 部分完成 | PR #60；補齊來源核實與 Battle／Map 案例 |
| Battle 行為矩陣與協定往返 | 已建立需求矩陣初稿，待補協定證據 | 見 [Battle／Map 矩陣](PHASE0_BATTLE_MAP_MATRIX.md)；仍需補狀態圖、來源及逐案例測試 |
| Map／移動／傳點行為矩陣 | 已建立需求矩陣初稿，待逐項核實 | 見 [Battle／Map 矩陣](PHASE0_BATTLE_MAP_MATRIX.md)；座標／傳點來源與正式服狀態仍待填證據 |
| 跨平台共用界線 ADR | 待完成 | 比對 Android 複本的實際差異後決定共用契約範圍 |
| 新 UI 技術與架構正式決策 | 未決策（刻意保留） | P0 不猜選 toolkit；由小型可驗證原型比較後決定 |

## 7. Phase 0 完成門檻

開始 Phase 1 新骨架前，至少要有：

- [ ] Battle 與 Map 的狀態圖、命令／事件表、取消與錯誤矩陣。
- [ ] 每個高風險協定與資源資料的來源等級與未決事項。
- [ ] desktop／Android 共用 contracts 範圍、平台專屬責任與版本策略 ADR。
- [ ] 新 UI／執行平台決策的比較依據，而非只以舊技術慣性選擇。
- [ ] P0 golden test 可在不啟動舊 UI、不連正式伺服器的環境獨立執行。

## 8. 本次執行紀錄

- 讀取 main tree、README、入口、協定模組、Battle／Map 代表檔、測試與 workflow 結構，並檢視既有重製 PR 的範圍。
- 建立 [Battle／Map 跨平台行為與驗收矩陣初稿](PHASE0_BATTLE_MAP_MATRIX.md)，列出 12 個 Battle、12 個 Map、7 個 Android lifecycle 候選案例；尚未轉成正式封包 golden 或完成端到端測試。
- 本文件只記錄靜態盤點與決策缺口；沒有改動既有功能程式碼、沒有調整版本號、沒有合併任何 PR、沒有建立 Release／Tag。
- 本回合沒有執行本機測試或 APK／EXE 打包，也沒有宣稱正式服 E2E 完成。
