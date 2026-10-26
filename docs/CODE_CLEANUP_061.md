# v0.6.1 全程式無用碼盤點與清理（2026-10-26）

## 範圍與方法

已讀取／語法分析 wlre 的 234 個 Python 檔、tools 的 27 檔、tests 的 159 檔，
加上 WLRE_Client.py 入口，共 421 檔。掃描使用獨立環境中的 Ruff 0.17.2 與
Vulture 2.16，沒有修改專案需求檔或將分析器加入應用程式依賴。

Ruff 首次發現 136 項未使用匯入候選及 5 項未使用局部綁定；沒有發現本次選用規則內的
未定義名稱、重複定義或無效控制流程。逐一檢查專案內匯入、測試 patch 字串、
相容入口及共享用途後才批准刪除，不直接對整個專案執行自動修正。

## 已清理

- 43 個未使用的匯入名稱，涵蓋命令分派、遠征資料、更新、資源同步、
  本機設定、背包／製作 UI、發版工具與測試。測試內的 API 存在性匯入保留。
- 5 個未使用的局部綁定。DoorLink 記錄長度驗證仍保留呼叫，只移除接收但未使用的計數。
- 副本 Runtime 測試的一處重複賦值；AI 卡片存在性改以明確 assertIn 保留原本檢查。
- 小地圖重複名稱計數，以及已由 marked_portals 篩掉無效點位後永遠不產生提示的
  點位缺少／投影不相容計數區塊。未標記傳點仍留在逐圖核對。

## 經檢查後保留

- ui/auto_battle_ui、ui/expedition_ui、ui/minimap、instance_ui 與 HomeMap 的
  舊匯入與模組層 patch 出口；services/expedition 的 __getattr__ 等轉接契約。
- combat_resources 的 item_name、skill_name、reserve 等跨模組匯入出口。
- Python __deepcopy__(memo) 等協定簽章，以及錯誤回報／進度回呼的固定參數。
- auto_candidate_reader、feature_resource_index 的 mtime_ns 參數：即使函式內沒讀取，
  它仍是 lru_cache 失效鍵，刪除會讓修改過的快取不刷新。
- 所有打包／Launcher 入口、資源驗證、協定拒絕、使用者設定、私人快取與遊戲資源。

清理後選用規則仍列 94 項匯入候選，全部為 F401；包含相容輸出與測試的 API
匯入等未批准刪除項。沒有用全面忽略規則掩蓋它們。未找到足以安全刪除整個功能模組的證據，
因此沒有刪除功能檔、測試案例或資源。Vulture 的低信心函式報告也經核對；
例如 validate_resources 被主入口與測試使用，並不是可刪除函式。

## 驗證

- 完整回歸 1128 項：1126 通過、2 跳過。
- 應用資源 self-test、UnityFS／LZ4／Brotli 實際解包 self-test、Tk GUI smoke test 通過。
- 全程式 compileall、文件／資源稽核及 git diff --check 通過。
- 本輪不執行正式服 E2E、不打包原生 EXE，不宣稱 Windows／macOS 遠端 CI 已通過。
- 版本維持 v0.6.1，不建立 Release／Tag、不合併 main。
