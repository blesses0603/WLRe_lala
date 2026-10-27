# next/：新 LaLa（階段 0）

> **這不是舊版 LaLa 的一部分。** 此資料夾只放新專案的規格與工具，**不修改任何既有檔案**，
> 也不影響 `wlre/` 的版本號（維持 v0.6.1）。新專案穩定後會搬到獨立 repo。

## 方向

| 項目 | 決定 |
|---|---|
| 平台 | 桌面與 Android 共用核心 |
| 核心語言 | Kotlin Multiplatform（舊版 Python 作為參考實作與資料包建置工具） |
| 定位 | 完整自動化輔助（戰鬥、地圖、任務…），分階段移植 |
| UI | 沿用舊版主題與設計，不使用遊戲截圖當背景 |
| 原則 | 單向分層；官方資料以官方伺服器驗證為準；驗證失敗一律拒絕（fail-closed） |

## 階段 0 進度

| 編號 | 項目 | 狀態 |
|---|---|---|
| 0-1 | 參考核心抽取清單與依賴盤點 | ✅ `EXTRACTION.md` + 可重現的 `analyze_deps.py`；清單中尚有「未量測」項目 |
| 0-2 | 無介面的參考 CLI | ⏳ 未開始（`reference-python/` 目前為空） |
| 0-3 | Golden Packet：P0（框架、登入、選角、初始化） | ✅ 46 個案例（含 9 個會話 scenario），獨立驗證器 46/46 相符 |
| 0-4 | 舊測試盤點分類 | ⏳ 未開始 |
| 0-5 | 新 repo 骨架與 CI | ⏳ 未開始（本資料夾尚無 CI 工作流程） |
| 0-6 | 官方資源探測工具 | ✅ `tools-python/probe_official.py`；已實際掃描官方 CDN（2026-10-27），規格見 `spec/behavior/official-*.md` |

### 已量測的依賴事實（舊 repo，commit `2dd6694`；詳見 `EXTRACTION.md`）

- `network/`、`core/`、`storage/`、`services/` 沒有任何引用 `ui/features` 的 import。
- 模組層級的 import 循環只有 **1 組、26 個模組，全在 `services/`**（資源管線、目錄、NPC 資料與物品／製作規則）；
  `network/`、`core/`、`storage/` 的模組都不在循環內，但套件之間是網狀依賴（例如 network→services 60 條模組邊）。
- 實際 import `protocol`、`state`、`client` 時不會載入 `tkinter`、`PIL`、`UnityPy`（它們是函式內延遲載入），
  但靜態分析顯示這三個模組的傳遞依賴會**參照**到它們（`protocol` 72 個模組、`state` 96、`client` 124）。
- 在沒有 `tkinter` 的環境執行 4 個協定／狀態測試模組：39 項中 36 通過、1 跳過、2 錯誤；
  兩個錯誤是測試本身 `import wlre.ui.gui`，不是核心程式依賴 UI。

## 目錄

```
next/
  spec/                 與語言無關的規格與 golden（見 spec/README.md）
  tools-python/         gen_golden.py（產生 golden）、analyze_deps.py（依賴盤點）、
                        probe_official.py（0-6 官方資源探測）與其離線測試
  EXTRACTION.md         0-1 抽取清單與量測事實
  reference-python/     （預留）從舊版抽出、不含 Tk 的參考核心與 CLI
```

## 誠實揭露

- 所有 golden 來自舊版 Python 實作（`reference_impl`）或人工構造（`synthetic`），**沒有**官方 Lua 逐項核對，
  也沒有實機擷取；舊版本身也標註「official live client not tested」。
- 完全沒有以真實伺服器或遊戲內操作驗證。
- 這裡沒有任何 Kotlin 程式碼。
