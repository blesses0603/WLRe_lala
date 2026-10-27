# 重建工程測試與驗收紀錄

測試以 main `2dd6694` 為基準。版本 0.6.1，Python 3.12，Pillow／UnityPy 依既有 requirements。雲端 Linux 使用 Xorg dummy `:99` 執行真實 Tk；不是 Windows EXE 或正式遊戲連線。

## P0 本地證據（2026-10-26）

| 項目 | 命令／來源 | 實際結果 |
|---|---|---|
| 首輪環境檢查 | unittest discover，DISPLAY=:99 尚未啟動 | 1 failure／109 errors；原因 couldn't connect to display；不作通過證據 |
| 顯示環境修復後完整基準 | `python -m unittest discover -s tests -q`，設定下述環境 | 1,198 項，84.453 秒，OK，跳過 2 項 |
| AST 工具回歸 | `python -m unittest discover -s tests -p test_core_rebuild_inventory.py -v` | 新增 3 項通過；相對匯入、動態匯入、循環、來源不執行／語法錯誤 |
| 靜態／入口檢查 | compileall、repository audit、盤點工具 Ruff、diff check | 通過；既有來源另有一項歷史 docstring escape 警告，不影響 AST 完整掃描 |
| 三項來源入口 | `--self-test`、`--self-test-unityfs`、`--smoke-test-gui` | 均 exit 0；GUI 使用真實 Tk，UnityFS 為空容器編解碼自測 |
| 官方受控探測 | 官方根目錄、ResourcePath、兩套 version／hash／bytes | HTTP 200，兩份 Manifest CRC／格式／版本一致；未下載 Bundle 或提升 Runtime |
| 已存在 main CI | [40330390002](https://github.com/blesses0603/WLRe_lala/actions/runs/40330390002) | Windows／Ubuntu／macOS 三工作成功；不是本分支新 CI |

本地完整基準輸出：`/tmp/lala-rebuild-p0-baseline-display.log`；首輪失敗：`/tmp/lala-rebuild-p0-baseline.log`。這些是本次雲端紀錄，不假設其他電腦存在相同路徑。

```bash
# 使用已安裝依賴的 Python；Linux 須先提供有效 DISPLAY 或 xvfb-run。
export WLRE_DISABLE_AUTO_CATALOG=1
python -m compileall -q wlre tools tests WLRE_Client.py
python -m tools.audit_repository --strict-git
python -m unittest discover -s tests -q
python WLRE_Client.py --self-test
python WLRE_Client.py --self-test-unityfs
python WLRE_Client.py --smoke-test-gui
```

`WLRE_DISABLE_AUTO_CATALOG=1` 保證常規 UI 測試不下載官方資源。跳過項目及平台限制照實記錄，不能當作功能成功。盤點可重現：`python -m tools.rebuild_inventory --ref 2dd6694 --output /tmp/main_inventory.json`。直接測試引用數不是 coverage 百分比。

## P0 分支 CI 與 P1a 本地驗證

- P0 提交 `ce159f5`：[40333188720](https://github.com/blesses0603/WLRe_lala/actions/runs/40333188720) 三平台全部成功；Ubuntu 2m34s、Windows 5m32s、macOS 39s。通過後才開始 P1a。
- P1a 新核心：`python -m unittest discover -s tests -p 'test_rebuild_*.py' -v`，**26 項通過**。包括真實背景工作停止、停止逾時明確 FAILED、生命週期回復、業務 API 閘門、事件訂閱釋放、相依無循環及無 GUI／服務載入。
- P1a 最終本地完整回歸：**1,227 項，91.445 秒，OK，跳過 2 項**。輸出 `/tmp/lala-rebuild-p1a-final.log`；之前一次 1,226 項通過後又新增停止期間 API 保護測試，因此重新執行完整測試，不以舊結果替代。
- 新增程式／測試 Ruff、compileall、repository audit、diff check 均通過。例外隔離及生命週期邊界的廣泛捕捉有逐行理由，固定錯誤碼取代例外內容；未降低既有檢查。
- P1a 本批 GitHub CI：推送後由 PR 完整三平台及新增純核心三平台流程驗證；尚未以先前 main CI 代替本批成功證據。

P1a 提交 `d808926` 的實際結果：純核心三平台 [40336014367](https://github.com/blesses0603/WLRe_lala/actions/runs/40336014367) 及完整 PR 三平台 [40336021156](https://github.com/blesses0603/WLRe_lala/actions/runs/40336021156) **全部成功**，之後才開始 P1b。

## P1b 桌面接入與背景取消

- 30 項純核心測試（包含新增 4 項 WorkerGroup）通過；4 項實際 Tk／舊主頁的 Host 整合測試通過；4 項關閉／下載取消測試通過。所有 HTTP 皆為替身，不下載正式安裝包。
- 完整本地回歸：**1,239 項，87.725 秒，OK，跳過 2 項**，紀錄 `/tmp/lala-rebuild-p1b-full.log`。之後來源 GUI smoke 改走同一 Host，再獨立重驗入口及既有 macOS 建置／smoke 測試，結果另列。
- 最終入口：`--smoke-test-gui` exit 0；`test_macos_build.py` 10 項通過、跳過 1 項（`/tmp/lala-rebuild-p1b-entry.log`）。此為雲端來源／建置計畫測試，沒有產生原生 APP。
- 測試曾發現 Tcl／ttk 計時器若用 Python `after_cancel` 刪除所屬 command，會造成停止 FAILED；已採原有 smoke 的 Tcl cancel 方式，交由 widget destroy 釋放 command。4 項 Host 測試全部重驗成功，不保留失敗待下批處理。
- 新檔完整 Ruff、舊檔未定義名稱／重複定義檢查、compileall、repository audit 與 diff check 通過。
- 本批 CI 尚待提交／推送；保留既有完整三平台 PR 檢查，純核心 CI 另加入合作式取消測試。Windows／macOS 原生安裝包及正式服 E2E 仍未執行。

P1b 首輪提交 `2d68ef9`：純核心三平台 [40339132736](https://github.com/blesses0603/WLRe_lala/actions/runs/40339132736) 成功；完整 [40339138846](https://github.com/blesses0603/WLRe_lala/actions/runs/40339138846) Ubuntu／macOS 成功，Windows 1 項新 Host 顯示斷言失敗（1239 項，跳過 7）。Windows 原生 Map 訊息尚未由事件迴圈處理，測試原先只呼叫 `update_idletasks`；已改以真實 Tcl 事件迴圈、最多 2 秒等待可見狀態，保留所有顯示斷言，不以 skip／取消安全檢查放行。此修復需重新跑三平台 CI，通過前不進入 P2。

修復提交 `408f6b1`：純核心三平台 [40340313642](https://github.com/blesses0603/WLRe_lala/actions/runs/40340313642) 成功；完整 [40340324695](https://github.com/blesses0603/WLRe_lala/actions/runs/40340324695) 最終三平台均成功。該完整流程的 macOS 曾因 **The job was not acquired by Runner of type hosted even after multiple attempts** 取消，沒有執行任何測試；僅重跑該失敗工作後成功，沒有為容量問題修改／跳過測試。等待期間，已通過必要核心契約且無 UI 相依的 P2 來源／Parser 工作繼續，沒有將排隊當成驗收成功。

## P2 第一批來源與正式 Parser

- UI／UnityPy 環境的 `test_official*.py`：92 項通過；Manifest 專用測試 5 項通過。新版本觀測／來源／邊界 6 項包含其中。
- 獨立無 GUI／UnityPy 環境，依資源 CI 選定七組版本／下載／Parser 測試：合計 68 項通過。嘗試完整 official 通配時，地圖影像稽核因該工具環境未安裝 Pillow 而 1 項匯入失敗；影像測試仍由完整 PR 安裝 Pillow 後執行，沒有降低合併檢查。
- 最終完整本地回歸：**1,245 項，92.582 秒，OK，跳過 2 項**，`/tmp/lala-rebuild-p2a-full.log`。新檔 Ruff、舊檔名稱檢查、compileall、repository audit、diff check 與直接工具 CLI `--help` 通過。
- 真實官方測試先發現 Accept 窄化會 406；調整為已觀測支援的 `*/*` 後，VersionDetector 兩輪六次版本讀取及兩份 Manifest 下載／CRC／完整解析成功，來源及 fingerprint 證據見 `docs/rebuild/official_pipeline_probe.json`。另外一般啟動的 cache-buster 查詢回報 `same_resources`。沒有登入遊戲、下載完整 Bundle、提升新 Runtime 或提交原始資源。
- 本批獨立 CI：推送後執行資源三平台、純核心三平台及完整 PR 三平台；此處尚未預先標為通過。

提交 `19074fc` 的實際 CI：[資源 40344585103](https://github.com/blesses0603/WLRe_lala/actions/runs/40344585103)、[核心 40344585562](https://github.com/blesses0603/WLRe_lala/actions/runs/40344585562)、[完整 40344609347](https://github.com/blesses0603/WLRe_lala/actions/runs/40344609347) 三組三平台 **全部成功**。

## P2 共用下載器批次

- 下載器新增 **15 項**單元／檔案整合測試通過：有限重試、429／404 不重試、慢速總時限、來源與大小、取消、原子覆寫保護、斷流重試不混接、條件式 Range／回退、錯誤 Range 拒絕、轉址回應釋放與共享診斷生命週期。
- 既有官方服務 92 項回歸通過。接入時曾發現轉址的舊錯誤訊息相容性失敗，已保留 `Manifest response location/status unexpected` 並重驗通過，沒有改弱既有斷言。
- 完整本地曾執行 1,259 項通過（97.894 秒、跳過 2）。補上 HTTP IncompleteRead 斷流恢復測試後，最終完整回歸另記，不把先前結果當作新測試已跑。
- 真實官方受控測試：一個 430,359-byte Bundle、HEAD 200／兩段 GET 206、三項完整性、UnityFS／完整 AssetPath 擷取及 1,337 筆場景表解析成功。僅驗證來源與既有 Parser，不是完整正式世界快照或遊戲 E2E。
- 新增程式 Ruff、既有服務名稱檢查、compileall、repository audit、diff check 通過。原始 Bundle／表格只留 `/workspace/output/lala-core-rebuild-downloader`；公開報告只含來源／雜湊／長度／筆數。
- 本批 CI 待提交／推送驗證；未發布／打包，未刪除歷史資源或使用者設定。

本批最終完整本地回歸：**1,260 項，91.864 秒，OK，跳過 2 項**，`/tmp/lala-rebuild-downloader-final.log`。舊 1,259 項成功結果沒有取代新增斷流測試後的完整執行。下載器及其後資源管線將以 `feature/lala-core-rebuild-resources` 的獨立 PR 審查，依賴核心分支 `19074fc`。

## 共用 UI 原生資源生命週期修復

資源子 PR #59 的完整 Windows CI [40354746790](https://github.com/blesses0603/WLRe_lala/actions/runs/40354746790) 曾在背景 GC 執行 `Variable.__del__` 時出現 `main thread is not in main loop`／`Tcl_AsyncDelete` 並以 exit 3 終止；核心及資源單獨 CI 成功。這是 GUI 原生參照生命週期缺口，不以重新執行掩蓋。

修復移回核心分支供 PR #58 與 #59 共用：只在完整 Tk root 銷毀後、原擁有者執行緒解除該 interpreter 的 Variable、圖像、Font、Style／widget 原生參照；其他 root 不受影響。Python 3.12 Variable 缺公開 dispose，因此對已銷毀 scope 使用其已驗證的終止欄位；失效 widget 呼叫仍回報 TclError。未停用正式 GC、未吞掉跨執行緒錯誤、未改動遊戲資料。

- 新增 3 項 UI 資源測試通過：另一個 interpreter 保持可用、錯誤執行緒 destroy 先拒絕、隔離子程序關閉後背景 GC 無 unraisable／原生崩潰。
- 隔離子程序另實際建立並關閉完整 DesktopHost，再由背景執行緒強制 GC，exit 0、無 stderr。
- 資源子分支完整本地 1,263 項通過（90.229 秒、跳過 2）。搬回核心分支後另跑基準完整測試與 CI，不混用不同分支的測試筆數。
- 核心分支最終完整本地 **1,248 項，90.173 秒，OK，跳過 2 項**（`/tmp/lala-core-ui-lifetime-full.log`）；加強後的隔離測試同時包含完整 DesktopHost，3 項另驗成功。

## 尚未驗收

- 新核心／新功能移植：以各批測試與 CI 另行追加，不引用舊 main 成功取代。
- 正式伺服器 E2E：未執行；沒有使用帳密或未知封包。
- Windows 原生 EXE／乾淨安裝、macOS 原生 APP：未打包；build dry-run 僅驗證建置計畫。
- 新版官方 Bundle 全面解析、場景及動態網格位置：未由本次 Manifest 探測證明。
- 效能／長時間執行／網路重連／完整關閉：P7 必須另有量測及結果。

## 已通過的前置 CI（本批開始前重新確認）

核心 `1750de7`：核心模組 [40361527383](https://github.com/blesses0603/WLRe_lala/actions/runs/40361527383)、資源模組 [40361527381](https://github.com/blesses0603/WLRe_lala/actions/runs/40361527381)、完整 [40361538388](https://github.com/blesses0603/WLRe_lala/actions/runs/40361538388) 的 Windows／Ubuntu／macOS 全部成功。

資源子分支 `0be8209`：核心模組 [40361648226](https://github.com/blesses0603/WLRe_lala/actions/runs/40361648226)、資源模組 [40361648236](https://github.com/blesses0603/WLRe_lala/actions/runs/40361648236)、完整 [40361659842](https://github.com/blesses0603/WLRe_lala/actions/runs/40361659842) 的 Windows／Ubuntu／macOS 全部成功。這些結果包含先前 Windows 原生資源生命週期修復；新場景快照批次需另跑 CI，沒有引用舊成功當作新程式已驗收。

## P2 場景定義快照批次

- 新增 `test_official_resource_manager.py` **28 項**：生成的非遊戲 Manifest／Bundle header／場景表，沒有下載正式資源。包含欄位與來源 offset、不可變紀錄、舊 buffer／import API、未知來源／缺失／未知 Parser／加密／循環／整批配額拒絕、CAS 競爭、原子寫入失敗、JSON 與 SHA、更新期間變版／變 hash、離線拒絕、取消／關閉／重入、擷取前再次拒絕遭更改的快取。
- 無 GUI／UnityPy 環境中，上述 28 項及既有 UnityTextAsset 12 項、instance protocol 8 項通過。全部官方服務測試 **120 項通過**（新 28 項包含其中）。
- 完整回歸曾以 1,289 項、1,290 項通過；之後補上的相容入口與擷取前快取變更測試均有重驗，不將早先結果當成新增測試已跑。
- 新資源程式、工具、測試及舊 Unity 相容入口完整 Ruff；舊服務名稱檢查、compileall、repository audit 與 diff check 通過。
- 真實來源：2026-10-26T19:33:21Z，新 Manager 完成兩套 Manifest、必要場景 Bundle、精確擷取、解析、再次官方核對與原子快照，**1,337 筆**，`protocol_approved=False`。公開收據 `docs/rebuild/official_snapshot_probe.json`，原始資料僅在私人快取，沒有轉成隨程式提供的固定遊戲資料表。
- 受控工具先因舊工具的 `.git` 存在檢查而拒絕雲端 `/workspace` 與 `/tmp` 空掛載標記；新工具改用真正的有界 Git 工作樹查詢，專案內／未知權限仍拒絕；沒有修改舊工具規則。修復後實際工具驗證成功。
- Manager 尚未接入 GUI／舊 Runtime，不把本批視為逐功能正式遷移。UnityPy 的單次同步解壓只在返回後檢查取消，沒有硬式中斷或完整記憶體隔離；資源清理、長時間效能與 P7 量測仍待驗收。
- 本批三平台模組與完整 CI 以 [PR #59 Checks](https://github.com/blesses0603/WLRe_lala/pull/59/checks) 的**本批提交**為準；保留全部必要工作，常規 CI 不下載官方 Bundle。

本批審閱後最終完整本地回歸：**1,291 項，101.756 秒，OK，跳過 2 項**（`/tmp/lala-p2-snapshot-reviewed.log`）。此結果已包含公開 Manifest 驗證介面、舊 buffer／地圖 helper 相容性、擷取前快取再核對及全部新測試。沒有實際 EXE 打包或遊戲正式服 E2E。
## macOS 原生 GUI 測試覆蓋修正批次

資源子分支提交 `34b7866` 的三套三平台 CI 全部成功（核心 40389292080、資源 40389292107、完整 40389302668）。檢視完整測試紀錄發現各平台均收集 1,291 項，但 Ubuntu 跳過 2、Windows 跳過 7、macOS 跳過 132；macOS 其中 **131 項 GUI** 被僅接受 `DISPLAY`／Windows 的舊 decorator 排除，另外 1 項是確實只支援 Windows 的 DPAPI。

29 個相關 GUI 測試模組加入 macOS 原生 Aqua 條件，不設定假的 DISPLAY、不刪測試或放寬斷言；Linux 無顯示環境仍跳過，Windows 行為保留。已有原生 Aqua smoke 測試以相同平台條件執行，本批讓一般功能與新 Host／原生資源測試也真正執行於 macOS。修正先提交核心分支，待三平台 CI 驗證後再正常合入資源子分支；不改寫歷史或修改 main。

這是 CI 覆蓋修正，沒有修改遊戲功能或官方資料。各平台實際執行數、剩餘 skip 與完整結果以本批提交的 Actions 為準；若原生 Mac 測試失敗，先修復，不將先前綠色但跳過 GUI 的結果當作驗收。

本批核心分支本地完整 **1,248 項，92.428 秒，OK，跳過 2 項**（`/tmp/lala-core-native-mac-guards.log`）。逐檔 AST 比對證明只有 29 個模組的顯示條件及必要 sys 匯入變動；沒有改動測試斷言／功能程式。名稱檢查、兩個新核心 GUI 測試 Ruff、compileall、audit、diff check 通過。macOS 執行結果必須等待本批原生 CI，不以 Linux 模擬結果聲稱通過。

原生 GUI gate 提交 `a8e793e`：核心 40391064681／資源 40391064672 三平台成功；完整 40391075638 的 Ubuntu／Windows 成功，macOS 執行至 15 分鐘上限而取消。這不是 runner 排隊問題，不能記為通過。該工作最後完成 `test_character_sync_safety`，下一個測試模組為 `test_compact_crafting`；尚無堆疊足以確認實際卡點。

追加 CI 診斷：macOS 先獨立執行完整製作 UI 8 項，90 秒未退出時由 faulthandler 輸出堆疊並非零結束；之後仍必須執行整套測試及原生 GUI smoke，整套每 60 秒提供診斷堆疊。保留 15 分鐘上限及所有斷言，沒有用跳過掩蓋。本地相同 preflight **8 項，12.814 秒通過**；整套診斷命令亦以連線／GUI **17 項通過**驗證。Mac CI 需重新執行，通過前不合入資源分支或開始依賴此結果的移植。

診斷提交 `31b0f78`：核心／資源三平台成功；Mac preflight 在 90 秒明確失敗（完整 CI 40394023562，Mac job 121822151675）。堆疊確認第一項 `CompactCrafting.setUp` 的 `root.update()` 卡在 `_tkinter`，沒有進入功能斷言。現有來源 smoke 原已註記 unattended Cocoa 的隱藏 Toplevel 切換可能阻塞完整 update；單純把 GUI gate 打開不足以驗收。

修復只在測試層：`_tk_native_pump.NativeTestRoot` 仍是真正 Tk root，Aqua 的 update 以 25ms 退出計時器驅動真正 mainloop，再處理 idle geometry；Windows／X11 繼續呼叫原 Tk.update。28 個測試模組改用此 root factory，AST 比對證明斷言與功能操作未變，子程序腳本沒有文字替換。不是把 update 換成 idle-only、假的 DISPLAY 或假 UI。新增 3 項實際 callback／計時器清理／callback 銷毀 root 測試通過。

本批本地完整 **1,251 項，98.045 秒，OK，跳過 2 項**（`/tmp/lala-core-native-pump-full.log`），最後清理分支再驗 3 項成功。新檔／核心 GUI 測試 Ruff、28 檔名稱與 AST、compileall、audit、diff check 通過。Mac 整套 CI 改為每個 case／類別交接最多 90 秒輸出堆疊並非零結束，仍保留完整 suite、source GUI smoke 與 15 分鐘 job 上限；沒有延長等待掩蓋卡住。實際 Aqua 修復是否成功須由本批原生 CI 判定，不能由 Linux 的結果推論。

有界 Aqua pump 提交 `0a55894`：核心 40395298214／資源 40395298316 三平台成功；完整 40395306705 的 Windows／Ubuntu 成功。Mac 製作 UI preflight 已通過，整套實際跑完 **1,251 項，186.302 秒**，但有 **8 failures／1 error／3 skipped**，未驗收通過。跳過為 Windows DPAPI 及兩項需更大 viewport 的重排測試，不再錯誤跳過 131 項 GUI。

實際暴露並修復的三類問題：

- Native Aqua 的 borderless 會重設 resizable，部分 Toplevel 設定還回傳不能轉為布林值的結果。Aqua 保留原生 WM 邊框與縮放狀態，Windows／X11 保留既有自訂邊框；最小化／恢復亦遵循同一政策。
- 原生 WM 映射後，對話框實際下緣達 773，而螢幕高 768。共用定位保留邊緣空間，Map 後依實際座標校正內容大小；不在使用者拖曳時持續縮小，保留 resizable 設定及既有固定視窗政策。加入邊緣與真實 Tk 映射回歸。
- 以 stdin 執行 unittest 時，Mac spawn 子程序嘗試匯入不存在的 `<stdin>`。改用 `python -m tools.run_native_unittest` 的真實檔案入口，保留同一套測試與 90 秒 deadline。新增隔離子程序測試驗證 spawn、失敗碼與阻塞 class setup 的堆疊／非零退出。

修復後本地完整 **1,257 項，88.749 秒，OK，跳過 2 項**（`/tmp/lala-core-aqua-final-window.log`）；runner 額外 3 項通過，既有跨程序寫入 7 項透過新入口通過。Ruff、舊檔名稱、compileall、audit、diff check 通過。Mac 修復需由下一批 CI 實際確認，不預先標為成功。

提交 `1b5b7c4`：三平台核心／資源 CI 成功；完整 40398181927 的 Ubuntu／Windows 成功，Mac 已修復 spawn、resizable 與 Toplevel 布林錯誤，但完整 **1,257 項／169.624 秒**仍有 **10 failures／3 skipped**。其中 9 個 failure 是固定視窗於 Cocoa 回報 zoomed 而非 normal；另外導航視窗下緣為 769，螢幕高 768。

修復原生座標四捨五入：映射後尺寸內縮一個座標單位。對五處導航可見性斷言，Windows／X11 仍嚴格要求 normal，另外確認實際映射；Aqua 只有在 resizable=False、minsize=maxsize 且實際映射時，才接受固定窗的 zoomed 回報。沒有改寫 Tk 的 state 值或把隱藏視窗當成正常；新增真實 Tk 測試證明隱藏窗會被拒絕，已映射固定窗才通過。既有選頁、選取、尺寸與禁止網路指令等斷言全保留。

本批本地完整 **1,258 項，92.183 秒，OK，跳過 2 項**（`/tmp/lala-core-native-state-final.log`）；事件迴圈／可見性 4 項另驗成功，Ruff、名稱及 diff check 通過。本批 native CI 仍需重新驗證，不能以 local X11 結果代替 Aqua。

提交 `d30ea5d` 的三平台模組與完整 Ubuntu／Windows 成功；Mac 完整 40399558610 實際 **1,258 項／154.262 秒**，已只剩導航視窗下緣 769 對 768 的一項 failure（跳過 3）。固定窗可見性與所有其他原生 GUI 項目通過。

最後的映射穩定修正：僅在 Map 後 100ms 內追蹤頂層 Configure，合併 idle 核對以涵蓋稍晚的原生框架位置；到期停止追蹤，不持續干預使用者拖曳。Destroy 明確取消核對與穩定計時器，新增真實 Map／關窗測試驗證兩者都釋放。補充失敗診斷使用實際 Toplevel，兼容製作頁的內嵌 Frame。

新增測試最初以 withdrawn 視窗的合成 Map 取不到工作，已改為真正映射後關閉並核對該 widget 的計時器；其後完整測試發現診斷訊息對 Frame 呼叫 title 不相容，已修復，未帶已知錯誤推送。模組 9 項、主畫面 8 項重驗成功。最終完整本地 **1,259 項，94.620 秒，OK，跳過 2 項**（`/tmp/lala-core-stable-map-final.log`）；名稱、compileall、audit、diff check 成功。原生 CI 結果仍以本批提交為準。

提交 `ded589d` 的完整 40402183737 在 Windows／macOS 於新增的關窗測試原生崩潰，位置同為視窗仍處理 Map 回呼時被銷毀。沒有標為通過。fixture 改為等待真實 Map 完成，再從 Configure 回呼返回後由測試主體關窗；測試自己的穩定期限延長至 10 秒，生產預設仍 100ms，以排除 CI 繪圖速度。明確確認關窗前兩項幾何工作存在、關窗後全部取消，沒有刪除測試或跳過平台。

Aqua 另外使用 32 單位初始邊緣預算容納原生選單列／陰影；Windows／X11 仍為原 24。新增純幾何回歸涵蓋 1024×768 的導航窗口及已觀測的 25 單位框架位置；實際像素斷言維持不變。完整 CI 開啟標準 PYTHONFAULTHANDLER，後續原生崩潰保留堆疊。

本批視窗模組 **10 項通過**，最終本地完整 **1,260 項，98.916 秒，OK，跳過 2 項**（`/tmp/lala-core-final-aqua-budget.log`）。名稱、audit、diff check 通過。Windows／macOS 的 fixture 修正及導航範圍仍待本批原生 CI 驗證；通過前不合入資源分支。

## 共用核心原生 GUI 驗收完成與資源分支整合

共用核心最終提交 `84d3bb1`：核心模組 [40404433631](https://github.com/blesses0603/WLRe_lala/actions/runs/40404433631)、資源模組 [40404433921](https://github.com/blesses0603/WLRe_lala/actions/runs/40404433921)、完整 [40404440099](https://github.com/blesses0603/WLRe_lala/actions/runs/40404440099) 的三平台 **9 個工作全部成功**。

完整三平台均收集 1,260 項：Ubuntu 131.876 秒／跳過 2，Windows 166.770 秒／跳過 7，macOS 192.532 秒／跳過 3；Mac 另執行製作 UI preflight 8 項成功。原先誤跳過的 GUI gate 已打開，仍有兩項大 viewport 測試因原生 runner 螢幕不足而跳過，另 1 項為 Windows DPAPI。沒有宣稱這兩個畫面尺寸情境已實測。

以正常 merge 帶回資源分支，沒有改寫歷史、沒有合併 main。TESTING 衝突已逐段保留資源與核心兩邊完整紀錄，另外通過 staged conflict-marker／diff check。合入後本地完整 **1,303 項，99.807 秒，OK，跳過 2 項**（`/tmp/lala-resources-native-integrated.log`），包含場景快照、下載器、舊協定／UI 及新原生測試支援。資源分支的最終三平台整合結果需以本 merge 提交的 PR #59 Checks 為準；原始官方資料、使用者設定及舊資產均未刪除。

## P2 場景名稱與模型引用批次

基準 `a88fc51` 的核心 [40405926554](https://github.com/blesses0603/WLRe_lala/actions/runs/40405926554)、資源 [40405926539](https://github.com/blesses0603/WLRe_lala/actions/runs/40405926539)、完整 [40405932541](https://github.com/blesses0603/WLRe_lala/actions/runs/40405932541) 三平台九項成功後，才開始本批。

新增 `test_official_scene_references.py` **13 項通過**，使用非遊戲合成樣本，測試文字格式／offset／舊 API、缺少與無效名稱、精確模型身分／歧義／加密／缺包、雙來源原子快照及撤銷。原 Manager 28 項、場景名稱 6 項通過。新 Parser／Manager／工具及測試 Ruff、舊檔名稱檢查、compileall、repository audit、diff check 通過。

完整本地 **1,316 項，91.833 秒，OK，跳過 2 項**（`/tmp/lala-scene-references-full.log`）；後續只調整既有場景 Finding 代碼的相容性，相關 41 項重驗通過。官方受控請求另外核對 1,337 場景／39,947 文字，收據與缺口見 [本批報告](docs/rebuild/P2_SCENE_REFERENCES_REPORT.md)，不當作實機遊戲驗收。已將引用測試加入資源三平台模組 CI；舊名稱 UI 測試保留於完整 CI，保留完整三平台 PR 檢查；常規 CI 不下載正式 Bundle。本批遠端結果需等提交後，不能以基準成功取代。

資源模組首次 CI `40425151470`：新增引用 13 項與原 Manager 28 項均通過，但額外加入的舊名稱測試匯入 HomeMap／Pillow，與純標準庫資源 job 的環境契約不符；Ubuntu／macOS 缺 Pillow 而失敗，未標通過。已將該 UI 測試保留在具備 UI 依賴的既有完整三平台 suite，資源 job 仍跑新增引用及舊文字 API 測試。沒有刪除測試、增加 skip 或降低必要 PR 檢查；修正另提交並重驗。

## P1／P2 官方資源 Module 生命週期批次

前批修正提交 `78ead6d` 的核心 [40425298992](https://github.com/blesses0603/WLRe_lala/actions/runs/40425298992)、資源 [40425298746](https://github.com/blesses0603/WLRe_lala/actions/runs/40425298746)、完整 [40425305656](https://github.com/blesses0603/WLRe_lala/actions/runs/40425305656) 三平台九項均成功後，繼續本批提交。沒有把首次失敗或被新提交取消的工作標通過。

新增 `test_official_resource_module.py` **17 項通過**，使用真實 Thread 與合成傳輸：核心 READY／owner、初始化不連網、結果／完成事件背壓、取消晚到成功、舊 view 撤銷、失敗診斷與恢復、合作式停止／未退出 FAILED、停止後不再寫入、啟動失敗、工具期限及清理失敗不發布報告。全部資源 workflow 命令於無 Pillow 環境通過；新模組、工具、Parser 及測試 Ruff、compileall、repository audit、diff check 通過。

完整本地先以 **1,332 項，91.034 秒，OK，跳過 2 項** 通過；新增工具清理失敗回歸後，最終完整 **1,333 項，88.239 秒，OK，跳過 2 項**（`/tmp/lala-resource-lifecycle-final.log`）。之後再強化停止與結果寫入的互斥邊界，相關 17 項重驗成功，未更動 GUI／遊戲協定。最終遠端 CI 仍需對應本批提交，不以此本地或前批結果取代。

2026-10-27T00:20:40Z，已透過 Application／OfficialResourceModule 真實核對官方場景與文字快照並成功清理，來源收據見 [生命週期批次報告](docs/rebuild/P2_RESOURCE_MODULE_REPORT.md)。GUI／舊 Runtime 尚未移植；同步解壓不能硬式中斷，停止超時須失敗。正式服 E2E／原生 EXE 打包仍未執行。

### 資源 Module 程式提交三平台驗收結果

`4d299b8` 的核心 [40426290882](https://github.com/blesses0603/WLRe_lala/actions/runs/40426290882)、資源 [40426291006](https://github.com/blesses0603/WLRe_lala/actions/runs/40426291006)、完整 [40426297999](https://github.com/blesses0603/WLRe_lala/actions/runs/40426297999) **九個工作全部成功**。完整 suite 均收集 **1,333 項**：Ubuntu 139.864 秒／跳過 2；Windows 341.080 秒／跳過 7；macOS 141.901 秒／跳過 3，另有原生 GUI preflight 8 項通過。兩個大 viewport 情境仍受 runner 螢幕限制，不把 skip 當成已實測；正式服 E2E／EXE 打包未執行。

收尾僅校正架構／契約／來源說明與移植表的過時進度、記錄本批 CI，不更動程式或測試；repository audit／diff check 通過。此文件提交仍保留相同三平台工作及完整 PR 檢查，以 PR #59 Checks 作為最終整合結果，不另以文件修改繞過檢查。

## P2 場景欄位與 GUI 唯讀核對批次

基準 `a39765f` 的核心 [40427048250](https://github.com/blesses0603/WLRe_lala/actions/runs/40427048250)、資源 [40427048180](https://github.com/blesses0603/WLRe_lala/actions/runs/40427048180)、完整 [40427054864](https://github.com/blesses0603/WLRe_lala/actions/runs/40427054864) 九項成功後開始。main 仍為 `2dd6694`，版本 0.6.1。

新增 **22 項**：`test_scene_fields` 11 項、`test_scene_data_window` 8 項、桌面 Host 2 項與模組安全錯誤碼 1 項；原 Manager 28／Module 原有 17 及舊 UI 均保留。包括資料就緒分離、不可變／租約、提交中取消、唯讀 GUI 到真實背景管線、搜尋分頁／固定欄位、來源與錯誤狀態、頁尾可見、遊戲命令佇列不變、關窗持續處理 Tk 回呼及等待所有工作。

曾以 1,354 項通過；收尾文件更新時一度覆寫 README／CHANGELOG，既有 README 稽核測試因此失敗。已從基準完整恢復兩檔，只附加本批內容，原稽核 5 項重驗通過；沒有刪測試或修改期待值。之後完整回歸另觸發 Tcl_AsyncDelete：以獨立場景視窗／未安裝 Root 清理的隔離程序確定重現，退出 -4。視窗改用既有共用 Root 清理，新增隔離回歸，背景 GC 不再接觸原生 Tcl；未把崩潰輪次標通過。

修正後開啟 PYTHONFAULTHANDLER 的完整本地 **1,355 項，95.955 秒，OK，跳過 2 項**（`/tmp/lala-scene-ui-safe-final.log`）。新程式／測試 Ruff、舊 GUI 名稱檢查、compileall、repository audit、diff check 通過；純資源 workflow 命令亦在無 GUI 依賴環境通過。GUI 測試留在完整三平台 suite，純資料／控制器測試加入資源模組 CI，不降低必要 PR 檢查。

受控官方資料於 2026-10-27T00:55:20Z 核對成功，九項欄位統計及來源見 [本批報告](docs/rebuild/P2_SCENE_GUI_REPORT.md)。本機 X11 Tk 未辨識 CJK 字型，中文字形量測為 0；本地截圖不列為完整中文字形視覺驗收。原生跨平台功能 CI、正式服 E2E、EXE 打包及人工視覺驗收分開記錄；後三者未宣稱通過。本批遠端結果以 PR #59 對應提交的核心／資源／完整三平台 Checks 為準。
