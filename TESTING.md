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

## 尚未驗收

- 新核心／新功能移植：以各批測試與 CI 另行追加，不引用舊 main 成功取代。
- 正式伺服器 E2E：未執行；沒有使用帳密或未知封包。
- Windows 原生 EXE／乾淨安裝、macOS 原生 APP：未打包；build dry-run 僅驗證建置計畫。
- 新版官方 Bundle 全面解析、場景及動態網格位置：未由本次 Manifest 探測證明。
- 效能／長時間執行／網路重連／完整關閉：P7 必須另有量測及結果。
