# LaLa 電腦版模組化路線圖（v0.6.1 基準）

> 規劃日期：2026-10-25。基準：已合併 PR #56 的 `main`（合併 Commit `14af2ff`），`wlre/__init__.py` 為 **v0.6.1 開發版**。本文件屬**規劃／文件變更**，不拆檔、不更改執行期邏輯、不另升版本。以下行數僅為規劃當下靜態盤點，非重構品質指標。

## 1. 目的與目前邊界

LaLa 已有按領域劃分的 `ui/`、`core/`、`network/`、`services/`、`storage/`；並已拆出 `dashboard_builder.py`、`login_controller.py`、`account_controller.py`、`network/commands.py`、`network/service_scheduler.py`、`core/state_*_events.py`、遠征子介面與製作子介面。**不重做已有模組、不以檔案行數為唯一目標。**

這輪僅針對下列剩餘的「單一檔案同時協調多種責任」安排小批次重構：

| 優先 | 現有檔案（規劃時行數） | 尚混合的責任 | 建議先分離的單元 | 主要風險 |
|---|---|---|---|---|
| P1 | `wlre/ui/instance_ui.py`（約 1,012） | 副本／協力房間、創房／入房、待命、獎勵與畫面刷新 | 房間動作 UI、獎勵呈現、純顯示資料整理 | 房間鎖、結果不明與獎勵禁止重領 |
| P2 | `wlre/ui/home_map.py`（約 804） | 地圖繪圖、NPC 對話與商店、傳點操作 | NPC 視窗協調、傳點視窗協調、地圖描繪 | 舊 NPC 資料、座標與傳送憑證 |
| P3 | `wlre/ui/gui.py`（約 523） | App 初始化、工作者生命週期、畫面事件、命令佇列、連線 | 事件路由／畫面更新與會話生命週期協調 | Tk 主執行緒、背景回呼、舊帳號事件 |
| P4 | `wlre/network/client.py`（約 483） | SessionLogic 事件流、登入／斷線、命令協調、TCP 迴圈 | 會話階段協調／匿名診斷事件；沿用現有 commands 與 scheduler | 伺服器回覆先後、單寫入者 State、pending／uncertain |
| P5（後置） | `wlre/ui/version_gate_controller.py`（約 566）；`wlre/services/world/auto_catalog.py`（約 508） | 官方版本檢測、GitHub 更新視窗、下載狀態及 Bundle 候選建置協調 | 分離 UI 呈現、同步／候選服務調度、收據解讀 | PR #56 安全驗證、雜湊／相容性、失敗時禁止登入 |

**P5 門檻：** PR #56 已合併且 CI #822 的 Windows／Ubuntu／macOS 成功；使用者於 2026-10-25 回報**剛完成的功能實測均正常、未發現問題**。這是實機驗收的正向回報，但尚未提供逐功能清單、系統環境或 Log，故不能據此推定 NPC 交易、製作排程、傳送、戰鬥與官方 Bundle 自動補建等全部路徑均已逐項 E2E 驗證。P5 開工前仍須記錄受影響流程的可重現實機證據，並建立原行為回歸測試；不得把 CI 成功或概括回報等同於所有資源協定通過。

## 2. 建議開發順序與每張 PR 範圍

每階段各開**獨立分支、獨立 PR**；除非同一界面無法拆分，避免一次橫跨 UI、Network 與官方資源驗證。候選檔名僅供規劃，實作前確認倉庫沒有同名模組，並沿用現有目錄布局。

### P0：盤點、測試基準與相依界線（本 PR）

- [x] 記錄模組現況、順序、風險與安全界線。
- [x] 修正 README 對 PR #56 未合併的過期描述，連結本路線圖。
- [ ] 實作前建立匯入／呼叫關係基準，列出既有測試與畫面手動驗收清單。
- [x] 記錄使用者 2026-10-25 的實機測試回報：「已測功能正常，未發現問題」（尚無逐功能清單、環境與 Log）。
- [ ] 完成 **CI**、**Windows 實機 GUI**、**正式遊戲伺服器 E2E** 的逐項驗收矩陣；對未測路徑保留「待驗收」，不宣稱整體通過。

### P1：副本／協力 UI（第一張實作 PR）

- 保留 `InstancePanel`、`InstanceModePage` 公開入口、建立參數、指令名稱與既有使用者流程；先抽離可單測的純呈現計算，再移動房間／獎勵區塊 UI 方法。
- 抽取只讀視圖協調，不移動 `services/instance_room_flow.py`、網路封包、不改房間成功判定；必要時沿用匯入相容入口。
- 驗收：創房／加入／離開／待命／開始／入場、主副本與協力切換、領獎／取消與重開視窗；未確認狀態不得重送、不得跨副本操作。
- 測試起點：`tests/test_instance_ui.py`、`tests/test_instance_room_ui.py`、`tests/test_instance_room_flow.py`、`tests/test_instance_rewards.py`，並擴充拆分接口回歸。

### P2：地圖與 NPC UI（第二張實作 PR）

- 維持 `HomeMap` 的地圖選取、雙擊移動與公開回呼介面；候選責任：NPC 對話與商店視窗、傳點與清單 UI、純圖像／投影更新。
- 沿用 `services/world/npc_*.py`、`portal_policy.py`、`movement.py` 既有資料／政策，不在 UI 重寫協定或推定目標地圖。
- 驗收：NPC 查詢、對話與歷史、商店唯讀／操作入口、缺少資料安全降級、傳點禁止條件、地圖縮放／換圖後點擊對應。
- 測試起點：`tests/test_home_map_follow.py`、`tests/test_npc_catalog_v057.py`，另補 UI 快照輸入及選取／坐標案例；真服傳送另行驗證。

### P3：App UI 協調（第三張實作 PR）

- 讓 `App` 仍是唯一 Tk 組裝入口；將顯示事件分派／純格式化與背景工作者生命週期協調切開，**不改** `SessionBridge`、`DisplayQueue` 的既有所有權。
- 所有 Tk 操作留在 UI 主執行緒；工作者不直接更新控件；舊連線回呼不能污染新連線。
- 驗收：登入／斷線／重登、選角、背景佇列清空、頁籤顯示、視窗關閉與錯誤恢復、記憶帳號不洩漏敏感資料。
- 測試起點：`tests/test_login_and_tab_alignment.py`、`tests/test_optimized_ui.py` 與事件佇列既有測試。

### P4：網路會話協調（第四張實作 PR）

- 保留 `run_client`、`SessionLogic`、`verify_account` 對外契約；只移動可驗證的會話階段、匿名診斷及協調程式，不重新發明 `commands.py` 或 `service_scheduler.py`。
- **不變條件：** 單一網路工作者寫入 State；伺服器事件先 `State.apply` 再 `SessionLogic.receive`；回覆確認前不得假定操作成功；斷線／逾時保留 `uncertain`、避免重送。
- 驗收：登入拒絕與斷線、S23／S26／S27 交易觀測、封包解碼拒絕、隊伍／戰鬥事件、服務 tick 順序，以及資源保留／跨功能互斥。
- 測試起點：`tests/test_architecture_boundaries.py` 及既有 network／state／commands 領域測試；具體測試檔開工前再盤點，不猜測缺失檔名。

### P5：官方資源與版本閘門（**E2E 證據具備後**）

- `VersionGateController` 的官方資源版本與 GitHub LaLa Release 檢查可以在**UI 呈現層**拆分，但兩者仍須維持互不影響的安全決策。
- `auto_catalog.py` 的已知資料查找、下載、快取驗證與候選收據可分為純服務；候選資料不可跳過校驗升為正式 Runtime。
- **不變條件：** 官方只依已採用的 `.version`＋`.bytes`＋`.hash` 與實需 Bundle 校驗；固定 SHA／MD5／CRC／Schema 不降低；失敗時 fail closed，資料相容不代表遊戲協定相容。
- 驗收：官方更新、離線、缺檔、損壞、快取被竄改、資源路徑變動、登入拒絕和過期檢查；不得自動放行未驗證功能。
- 參考：`docs/AUTO_COMPATIBILITY.md`、`tests/test_prelogin_version_window.py`、`tests/test_game_version_gate.py` 及資源工具對應測試。

## 3. 所有實作 PR 的硬性門檻

1. **單一目的：** 保留公開入口、命令名稱、事件結構、設定格式與既有 UI 互動；先補 Characterization Tests（現行行為基準），再抽取。
2. **資料可信度：** UI 不直接寫 socket、服務不讀 Tk；只有網路工作執行緒改寫 State，且遵守 `@writes(owner)` 所有權限制。伺服器回覆才可結束 pending；uncertain 禁止自動重送。
3. **資源安全：** 不繞過官方 Manifest／Bundle 校驗、登入閘門或「未驗證資源不可啟用」原則。不改動 1275 固定基準與保護規則，除非另有經證據審核的專案需求。
4. **跨平台 CI：** 至少 Windows、Ubuntu、macOS 現有 GitHub Actions 完整通過；檢查 skipped 的 GUI 測試，不能把略過說成通過。
5. **人工實測：** 用 GitHub Desktop 切換待測分支，跑對應功能的 Windows 實機 UI 與遊戲伺服器 E2E（如需帳號／遊戲環境，由使用者執行）；結果、Log 與不能驗證的部分須分別註明。
6. **不提前發布：** 開發階段不因重構自動製作正式 EXE／APP、Release 或 Tag；不直接合併 `main`，合併前須使用者明確授權。
7. **版本紀律：** 本文件 PR 維持 v0.6.1；後續 PR 各自於建立及合併前讀取最新 `main`，依變更性質決定版本與標題 `[vX.Y.Z] 具體修改重點`，避免多 PR 版本碰撞。
8. **驗收報告：** 每張 PR 列出影響檔案、公開 API 相容性、測試數與跳過原因、已完成及未完成的實機驗收、風險、預計版本、CI 連結與合併狀態。

## 4. 下一步與完成定義

**下一張建議實作 PR 為 P1「副本／協力 UI 模組化」**。先讀最新 main、列出 `InstanceModePage`／`InstancePanel` 的方法依賴與既有測試，再分離低風險的顯示資料與子視圖，確保使用者入口與伺服器行為完全不變。每一階段通過三平台 CI 且相關人工驗收有明確紀錄後，才開始下一階段。

本路線圖本身完成僅表示**規劃文件已提交、可供審查**；使用者已回報已測功能正常，但尚不代表 P1–P5 的程式重構、全功能逐項 E2E 或正式發布已完成。
