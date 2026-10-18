> **最新結果（2026-10-19）**：PR #19 Commit `d72f3de` 的 [三平台原始碼 CI](https://github.com/blesses0603/WLRe_lala/actions/runs/39171233034) 與 [三種原生打包 CI](https://github.com/blesses0603/WLRe_lala/actions/runs/39171233020) 六項工作全部 success。以下以前的「待補」紀錄為歷程，已由本次通過紀錄取代；Windows/macOS 使用者實機、macOS Intel Tk GUI 與正式遊戲伺服器仍需人工驗收。不建立 v0.6.0 正式 Release。

# 第 10 項：測試、文件與版本整理

> 建立日期：2026-10-19。工作分支：`chore/phase10-final-audit-20261019`，基準 main：`a27826bc3fcabcbb72e42f600721ad90c9115cad`（PR #18 已合併）。
> 本項先完成離線審核與文件修正；GitHub Actions 額度耗盡時，不會冒稱新提交已通過最新 CI。

## 目標與安全界線

- 核對源碼／文件的實際版本，區分 **已發行 v0.5.0** 與 **v0.6.0 開發中的功能摘要**。只更新文件並保留 `wlre.__version__ = "0.5.0"`，不在沒有正式打包驗證時提早宣稱 v0.6.0 已發布。
- 清理真正重複、失效或過時的紀錄，同時保留歷史檔、相容匯入、正式遊戲資源、設定格式與測試入口。不得因檔名短或看起來像轉接模組就任意刪除。
- 不修改 EXP 效率計算、封包、登入、角色設定的程式碼，特別保留 `tests/test_exp_efficiency_regression.py` 及已驗證的第 07 項修正。
- 不重複觸發消耗昂貴 Runner 的 Windows／macOS 打包。三平台回歸及正式版打包待 GitHub Actions 額度恢復後再驗證；實機與正式伺服器依舊需人工驗收。

## 2026-10-19 初始盤點

| 類別 | 結果 |
| --- | --- |
| GitHub main 樹 | 286 個追蹤檔案，約 102.4 MB（依 Git blob size 加總，並非 ZIP 體積） |
| 相同 Git blob SHA | 僅 12 個零位元組套件 `__init__.py`，皆有建立 Python 套件的用途 |
| 完全相同的非空追蹤檔案 | 0 組，沒有需要刪除的同內容副本 |
| Markdown 文件及相對連結 | 19 份 Markdown、185 個相對路徑連結 |
| 失效相對路徑連結 | 2 處，皆在 `docs/README_v0.5.0.md`，已列入此次修正 |
| 可疑暫存資料 | 未在追蹤樹發現 `.pyc`、`.bak`、`.log`、`.sqlite`、`.pem` 等典型暫存／祕密檔 |
| 發行狀態 | GitHub Releases 上 v0.5.0 已於 2026-10-17 發布，含 Windows x64、macOS arm64、macOS x64 ZIP 與 SHA256SUMS |
| 當前程式版本 | `wlre/__init__.py` 為 `0.5.0`；README v0.6.0 是未發布的開發摘要 |

歷史報告 `docs/Portal_Review_1262.html`、`docs/README_v0.5.0.md` 與 `docs/CLEANUP.md` 是可追溯資料，不是重複執行檔。
小型相容轉接模組（例如 `wlre/services/expedition_data.py`、`expedition_teams.py`、`wlre/ui/expedition_ui.py`、`wlre/ui/minimap.py`）暫時保留，因為動態匯入、測試及舊路徑使用者無法單靠檔案長度判定不存在。

## 新增的離線驗證

```bash
python -m tools.audit_repository
python -m tools.audit_repository --strict-git
python -m unittest discover -s tests -q
python WLRE_Client.py --self-test
python -m tools.build.build_nuitka --dry-run
```

`tools.audit_repository` 唯讀，無網路、遊戲帳號或自動發版功能，會核對 Markdown 相對檔案路徑、程式版本及 Git 追蹤的非空重複 blob。
`--strict-git` 要求存在 Git index；純原始碼匯出可不用此參數。
`tests/test_repository_hygiene.py` 防止日後再引入失效連結、重複非空檔及錯誤的自動打包觸發設定。

## 已有的第 09 項證據與未完成項目

- [第 09 項三平台回歸 CI](https://github.com/blesses0603/WLRe_lala/actions/runs/39141397498)（Commit `4e3abc0`）：Windows、Linux、macOS 均 success。
- [第 09 項三平台原生打包 CI](https://github.com/blesses0603/WLRe_lala/actions/runs/39141397522)（Commit `4e3abc0`）：Windows x64、macOS Intel x64、Apple Silicon arm64 均 success，成功產出檔案。
- 第 09 項合併後，普通 PR/main 只執行 Ubuntu，跨平台回歸與完整 Nuitka 原生建置改為可選手動；發版標籤仍會執行正式建置。
- **第 10 項已取得 Ubuntu 最新完整回歸結果**：Commit `34add166` 在 [CI 39162618822](https://github.com/blesses0603/WLRe_lala/actions/runs/39162618822) 通過 423 項測試（2 項平台條件略過）；新增嚴格 Git 稽核確認 20 份 Markdown、191 個相對連結、0 斷鏈、0 非空重複檔案。Windows／macOS 三平台回歸及新原生建置仍未執行，不可混為一談。
- 尚需：在有足夠額度的環境執行第 10 項完整回歸、必要時手動三平台驗收、Windows／Mac 實機操作及正式遊戲驗證，確認穩定後再決定 v0.6.0 的版本常數、標籤與發布。

## 版本操作政策

目前正式可下載版請使用 [v0.5.0 GitHub Release](https://github.com/blesses0603/WLRe_lala/releases/tag/v0.5.0)。
README 中 v0.6.0 仍代表後續開發內容，不會因完成文件稽核就立刻創造 `v0.6.0` 標籤、觸發需要付費額度的建置或承諾已完成新的可執行檔。

## 補齊遺漏的自動化檢測（2026-10-19）

新增 `tests/test_audit_repository.py` 六組 fixture 測試：相對連結／文件錨點／外部 URL、缺檔與越界、單雙引號版本值、非空 Git blob 重複與空白套件檔例外、缺少 Git index 不得冒稱已驗證、嚴格模式和失效連結失敗退出碼。

日常 Linux CI 明確新增 `python -m compileall -q wlre tools tests WLRE_Client.py`、`python -m tools.audit_repository --strict-git`，以及 Windows Nuitka 與 macOS arm64／Intel x64 的 dry-run 打包計畫檢查。**dry-run 只驗證計畫，不是原生編譯**。

第 10 項前次 Commit `b23b804` 的 Ubuntu CI [39147669166](https://github.com/blesses0603/WLRe_lala/actions/runs/39147669166) 成功，417 tests、2 skips，含 GUI、資源自檢和 Windows dry-run。新補測需以最新 Commit 的 CI 結果另行驗收。

**仍待真實平台驗證：** `Main and PR tests` → `Run workflow` → 選第 10 項分支、`full_matrix=true` 才會執行 Windows／macOS 原始碼測試；`Native desktop packaging verification` → `Run workflow` → 選第 10 項分支才會實際編譯 Windows x64 EXE、macOS arm64／Intel x64 APP。額度不足時不自動觸發。Mac Intel 實機 GUI、Windows 真實操作及遊戲正式服仍需人工驗收。

## 稽核覆蓋範圍修正

在 Commit `84b5450` 的 Ubuntu CI [39162452731](https://github.com/blesses0603/WLRe_lala/actions/runs/39162452731)，423 項測試（2 項條件略過）成功，嚴格稽核顯示 18 份 Markdown、191 個相對連結、0 斷鏈、0 非空重複 Git blob。

核對後發現資料集另外包含兩份圖片資源歸屬聲明：`wlre/resources/assets/buttons/SOURCE.md`、`wlre/resources/assets/function-icons/SOURCE.md`。這次已將兩者加入 `tools.audit_repository.markdown_files` 的檢查清單，測試亦明確保護這兩個路徑。總計應覆蓋 20 份 Markdown；最終結果以本次新提交之 CI 為準。

## 最新驗證紀錄

2026-10-19，Commit `34add166`：[GitHub Actions 39162618822](https://github.com/blesses0603/WLRe_lala/actions/runs/39162618822)，Ubuntu job success。實際執行 423 tests、2 skips；成功完成 Linux GUI smoke、資源 `--self-test`、Python 全檔 `compileall`、`tools.audit_repository --strict-git`，與 Windows／macOS 雙架構 Nuitka dry-run。稽核明確顯示 `markdown_files=20`、`local_links_checked=191`、`broken_local_links=[]`、`nonempty_duplicate_blobs=[]`、`git_index_available=true`。

需要 Windows／macOS 真正執行與原生打包的補測仍保留未驗收，故 PR #19 保持 Draft、第 10 項尚未勾選。

## 2026-10-19 跨平台驗收解鎖

依使用者最新指示，不再以 GitHub Actions 額度作為阻擋完整檢查的理由：`Main and PR tests` 恢復 PR/main 的 Linux、Windows、macOS 三平台測試；`Native desktop packaging verification` 恢復建置相關 PR 的 Windows x64、macOS arm64 與 Intel x64 原生 Nuitka 編譯驗證，正式 Release 保持原流程。前文記錄額度不足為當時的歷史狀態，不是現在的限制。最新測試結果及人工驗收界線應以 PR #19 更新後的工作流程執行紀錄為準。

## 最終自動化驗收總結（2026-10-19）

- 第 10 項 PR #19 Commit `d72f3deffdb4c075b1a7fc6a1671009c55ad50fc`：[三平台回歸 workflow 39171233034](https://github.com/blesses0603/WLRe_lala/actions/runs/39171233034)：Ubuntu Linux、Windows 2022 x64、macOS 15 ARM64 三個 job 全部成功，涵蓋 Python 測試、GUI smoke、資源驗證和 build dry-run。
- [原生編譯與封裝 workflow 39171233020](https://github.com/blesses0603/WLRe_lala/actions/runs/39171233020)：Windows x64 EXE、macOS Apple Silicon arm64 APP、macOS Intel x64 APP 三個 job 全部成功，已上傳 `desktop-windows-x64-validation`、`desktop-macos-arm64-validation`、`desktop-macos-x64-validation` artifacts；工作流程涵蓋 Nuitka 原生編譯、編譯後自檢與可執行的 GUI smoke、ZIP 完整性與平台架構／簽章驗證。macOS Intel hosted runner 的 GUI smoke 仍依既有例外跳過，需 Mac Intel 實機確認。
- 六項自動化驗收均已完成，本項按「重構回歸、文件稽核、跨平台原生建置」範圍標記完成；不推定正式遊戲伺服器端到端行為、Windows 使用者環境與 Apple Developer ID 公證已驗證。
- 程式版號保持 `wlre.__version__=0.5.0`，`v0.6.0` 僅是 README 開發摘要。未新建 `v0.6.0` 標籤，也未觸發正式 GitHub Release。
