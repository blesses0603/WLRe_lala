# 全功能模組化執行與驗收紀錄（v0.6.1）

目標版本為 v0.6.2；未完成全部必要驗收前維持程式版本 v0.6.1。
本工程不合併 main、不建立 Release／Tag、不刪使用者資料。

## 分支與依賴

- main 基準：`14af2ff`（已整合 PR #56）。
- PR #57 依賴分支：`docs/modularization-roadmap-20261025`。
- 保留已回報 CI #828 成功提交：`cb9e9a77d61bae8cd7cd4dbfbdf0dfc946c79b2f`。
- 實作分支：`refactor/v061-feature-modularization`，由 PR #57 head 建立。
- 實作 PR 應先以 PR #57 分支為 base；依賴合併後再調整，不能遺失 Tk／Windows 修復。
- GitHub API 目前被執行環境政策拒絕；已保存加入 `api.github.com` 的設定草稿，尚未套用或發佈。遠端 PR／CI 狀態未宣稱通過。

## 功能盤點與共享邊界

[自動盤點](FEATURE_INVENTORY.md) 與 [機器可讀依賴圖](../architecture/inventory.json)
涵蓋所有 Python 原始碼／測試、模組定義、import、靜態資源引用。
[功能歸屬](../architecture/features.json) 決定分階段順序；不是拆檔大小配額。
網路與封包、State／事件、資源驗證／下載、原子儲存、跨功能安全規則保持共享。

## 階段紀錄

| 階段 | 範圍 | 已修改檔案／職責 | 測試與結果 | 資源遷移／風險／後續 |
| --- | --- | --- | --- | --- |
| P0 | 盤點與 CI 基礎 | architecture/features.json、tools/architecture、FEATURE_INVENTORY、功能 CI 工作流程 | 盤點工具與邊界測試；完整基準排版問題已修復並加入回歸：1021 項，1019 通過、2 跳過 | 所有舊資源保留；依官方等價與全消費者遷移證據決定移除 |

| P1 | 協力／一般副本 | features/instances 共用房間 UI；cooperative／dungeon 各自 Actions 與 Page；舊入口同物件 alias | 模組回歸 784 項通過；新增相容／斷線拒絕 7 項通過 | 保留共享封包／房間安全與 1262 副本目錄；官方來源等價缺口見資源稽核 |

## 最終驗收清單

- [ ] 22 個功能依責任完成分類與舊入口相容。
- [ ] 每階段模組回歸與 API／patch 相容驗證通過。
- [ ] 全部 Python import／打包資源與 UI smoke 測試通過。
- [ ] Windows GitHub Actions 完整驗收（未執行不標通過）。
- [ ] Ubuntu GitHub Actions 完整驗收（未執行不標通過）。
- [ ] macOS GitHub Actions 完整驗收（未執行不標通過）。
- [ ] 真實遊戲伺服器 E2E（需實際遊戲環境，與單元測試分開）。
- [ ] Windows 原生 EXE／乾淨安裝（與 build dry-run 分開）。
- [ ] 所有必要驗收後才評估 v0.6.2；目前不建議正式升版。

模組 CI 使用 `python -m tools.architecture.test_features --feature <功能>`；
共享變更與最終驗收使用 `--feature all`。既有三平台完整工作流程保留；
新增功能 CI 不取代必要合併檢查。更新盤點使用 `python -m tools.architecture.inventory`。
