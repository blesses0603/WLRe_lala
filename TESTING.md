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
