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

## 尚未驗收

- 新核心／新功能移植：以各批測試與 CI 另行追加，不引用舊 main 成功取代。
- 正式伺服器 E2E：未執行；沒有使用帳密或未知封包。
- Windows 原生 EXE／乾淨安裝、macOS 原生 APP：未打包；build dry-run 僅驗證建置計畫。
- 新版官方 Bundle 全面解析、場景及動態網格位置：未由本次 Manifest 探測證明。
- 效能／長時間執行／網路重連／完整關閉：P7 必須另有量測及結果。
