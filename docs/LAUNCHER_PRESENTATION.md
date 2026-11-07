# 啟動進度與版本視窗

這份變更以 v7.3.0 開發版為基礎，未變更正式版本號，也不代表正式發布或官方服驗收。

## 單一啟動視窗

一般來源啟動器（含 `run_client.bat`）、直接 GUI 入口與打包版共用 App 的官方版本視窗。第一次背景工作先執行原有官方資源準備，再獨立執行官方版本、資料庫與 Runtime 登入檢查，不再先開另一個 Launcher 視窗。

資源準備在每個 App 執行個體內只進行一次；重複點查詢不會同時產生多個資源寫入工作。後續手動查詢與過期檢查仍執行官方驗證，資源收據只供說明，不是登入授權。獨立診斷用 `python -m wlre.services.world.launcher_catalog --progress` 保留。

在背景啟動工作尚未結束時關閉程式，視窗會先顯示安全結束狀態，待目前寫入完成後才退出。已請求退出就不會再顯示可登入結果或進入帳號頁。

## 斷線後的登入頁

真正連線結束（手動中斷、遠端斷線或連線失敗）後，回到帳號登入頁，不自動彈出版本檢查視窗，也不自動重新連線。帳號記憶設定與角色清理維持原有行為。

這不會建立新的登入授權。按登入時仍要求完整且經確認的版本結果，原有 300 秒有效期不變；過期、尚未驗證或結果不一致時，仍須先完成版本檢查。實際連線的 `verify_first=True` 不變。重新開啟程式與手動按「版本檢測」仍會顯示版本檢查。

登入頁顯示上次檢查結果與有效期規則。有效期內沿用的是上次成功結果，不是即時監測，也不能偵測尚未重新查詢的伺服器變更。`verify_first=True` 是帳號驗證，不能當作每次重連都重新查過官方資源版本的證據。

## 呈現原則

- 深藍底、青色進度條採用同一個輕量 Canvas 元件，不依賴 Windows 原生 ttk 進度條顏色。
- 已知數量僅顯示該階段實際完成數量，例如 `8 / 24`。未知總量維持流動指示，不推算整個啟動流程的百分比。
- 動畫只有一個 40 ms 計時器；確定進度、結束或元件銷毀時停止。
- 資源進度採最新顯示快照，保留解析失敗與終止結果，不讓大量狀態訊息塞滿 Tk 事件迴圈。這只合併畫面更新，不略過資源驗證。
- 繁中字型優先使用 Microsoft JhengHei UI、Microsoft JhengHei、PingFang TC、Noto Sans CJK TC，再回退到平台預設。
- 獨立進度視窗依字型縮放與換行後的內容調整高度；測試涵蓋 96、144、192 DPI、窄視窗、長訊息與終止訊息。

## 解析效能範圍

Runtime 的 NPC 與互動索引在需要解析時共用一次 Eve 場景掃描。保留 main 的正式 SQLite 個別特徵快取與來源驗證；已驗證快取命中時不額外解包。兩個 JSON 輸出、各自的紀錄上限與完整場景驗證保持不變，不新增持久快取。

成功的冷載入配對索引建置，場景掃描從兩次減為一次。合併解析拒絕時回到個別解析，以保留每個特徵原有的成功／失敗紀錄，不繞過驗證。若診斷稽核啟用，包含既有診斷流程的掃描從四次減為三次。這不是整體啟動時間減半的承諾；官方版本、Manifest、Bundle 雜湊、內容、診斷與登入安全檢查仍各自執行。

## 驗證方式

- `python -m unittest discover -s tests -p 'test_launcher*.py' -v`
- `python -m unittest discover -s tests -p test_integrated_startup.py -v`
- `python -m unittest discover -s tests -p test_prelogin_version_window.py -v`
- `python -m unittest discover -s tests -p test_eve_v115.py -v`
- `python -m unittest discover -s tests -p test_dynamic_bundle_runtime.py -v`
- `python -m unittest discover -s tests -q`
- `python -m compileall -q wlre tools tests WLRE_Client.py`
- `python -m tools.audit_repository --strict-git`

GUI 測試須有桌面或 Xvfb。一般 CI 仍須驗證 Windows、Linux 與 macOS；無顯示環境下的測試跳過不能代替原生 Windows 呈現驗收。真實官方資源下載、完整安裝包與登入不在離線測試結果內。

## 啟動工作拆分與階段耗時

桌面準備階段改為只同步完整 Runtime 所需的官方來源，不再建立後即丟棄完整 Runtime。必要表格、選配路由、圖片、emoji、戰鬥來源的既有下載額度及前後版本／Manifest 檢查保留。登入前仍獨立建立完整 Runtime，驗證 Bundle 位元組、資料庫內容與官方身分；來源同步收據不授權登入。

正式檢查現在分別回報官方版本資訊、Runtime 驗證、資料庫內容比對。階段耗時使用單調時鐘，沿用現有 UI 輪詢更新，不新增計時器。完成或失敗會鎖定進度條終態，晚到進度不會重啟動畫；明確重試才重設。資源收集解析數量與正式登入驗證分開顯示。

### 離線量測範圍

Linux／Python 3.12.14，同一合成 Runtime 測試資料，每組五次取中位，診斷稽核開啟、imports 已暖機。Bundle 已在本機，TextAsset 提取使用測試替身；冷／暖僅指 derived SQLite，不是首次官方下載。量測包含來源同步與 Runtime 準備，不包含完整桌面或真實網路。

- 完整 Runtime 建構：每次啟動 2 → 1。
- TextAsset 提取：20 → 10；SQLite materialization：22 → 11。
- 官方版本觀測：5 → 5；Manifest 取得：4 → 4。這些新鮮度與內容驗證沒有因美化移除。
- 冷 SQLite 中位：46.4 → 26.3 ms；暖 SQLite：40.7 → 24.0 ms。
- tracemalloc 峰值約 8.49 → 8.47 MB，沒有證據顯示記憶體用量大幅下降。

這不是使用者硬體或影片中 27 秒等待的改善承諾。低可用 RAM、真實 CDN／網路延遲與完整 Bundle 大小仍需現場驗證。快取命中仍重驗內容；版本改變、損壞、離線與資料庫不一致不能放行登入。
