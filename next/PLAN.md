# 新 LaLa 建構計畫（交接文件）

> 給接手的 Claude Code 與人類開發者。本文件記錄**已決定**的方向、階段計畫、目前進度與硬性限制。
> 未實際執行的項目一律標示「尚未執行」。與舊版 LaLa（`wlre/`，v0.6.1）無關的事不要動。

## 1. 專案定位（已決定）

- 《飄流幻境 Re》輔助工具的**全新獨立專案**（重新定義範圍），不是舊版 LaLa 的重構。
- 桌面與 Android **共用核心**；完整自動化輔助（戰鬥、地圖、任務…），分階段移植。
- UI 沿用舊版主題：深藍科技風、彈性較大的背包格子、精簡物品資訊；**不使用遊戲截圖當背景**。
- 資料以**官方伺服器為準**，驗證失敗一律拒絕（fail-closed）；官方 Lua 與 1262／1275 資料是判斷正確性的依據。

## 2. 技術路線（已決定）

| 項目 | 決定 |
|---|---|
| 核心與 UI | Kotlin Multiplatform（使用者有 Java 經驗；程式碼與註解要樸素、繁體中文） |
| 舊版 Python | 作為**參考實作**與**資料包建置工具**（UnityPy 只存在於 Python 端） |
| 規格 | 與語言無關的 spec + golden JSON，Kotlin 對著資料驗收，不憑記憶重推協定 |
| 架構 | 單向分層；單一協程擁有狀態；事件處理器註冊接入，核心不反向呼叫 services |

## 3. 階段計畫

### 階段 0：規格先行（目前階段；不寫 Kotlin、不做 UI）

| 編號 | 項目 | 狀態 |
|---|---|---|
| 0-1 | 抽取清單與依賴盤點 | ✅ `EXTRACTION.md`、`tools-python/analyze_deps.py` |
| 0-2 | 無介面參考 CLI（`reference-python/`） | ⏳ 未開始 |
| 0-3 | P0 golden（框架、登入、選角、初始化） | ✅ 46 案例，獨立驗證 46/46 |
| 0-4 | 舊測試盤點分類（1,198 項；哪些可轉 golden） | ⏳ 未開始 |
| 0-5 | 新 repo 骨架與 CI（Windows／Ubuntu／macOS） | ⏳ 未開始 |
| 0-6 | **官方資源探測工具**（見第 5 節） | ✅ `tools-python/probe_official.py`＋離線測試 25 項；2026-10-27 已實際掃描官方 CDN；規格見 `spec/behavior/official-*.md`。AssetBundle／Lua／Voice 完整列表尚未執行 |

### 後續階段（概要，細節待階段 0 完成後定）

1. 階段 1：Kotlin 核心（wire、解碼、會話）對 golden 全數通過。
2. 階段 2：資料包（Python 端由官方資源產生，Kotlin 只讀資料包）。
3. 階段 3：桌面 UI；階段 4：Android UI 與背景服務。
4. 階段 5：逐項移植自動化（戰鬥、地圖、任務…），每項先有規格與 golden。

## 4. 已知事實（舊 repo `blesses0603/WLRe_lala`，commit `2dd6694`）

- 封包：`C4 C6 | length:u16le | main:u8 | sub:u8 | payload`，整個 frame 以單一位元組 XOR（預設 0xAD）。
- 登入 C63-7（ASCII 帳密，非 ASCII 拒絕）、選角 C63-2、心跳 S1-23→C63-5、世界就緒 C12-1＋C3-2 只送一次。
- 模組層級 import 循環只有 **1 組、26 個模組，全在 `services/`**；`network/core/storage` 不在環內。
- 兩個舊版怪癖已記錄於 `spec/behavior/p0-login-and-session.md`，新版保留或修正都要有意識決定。
- 所有 golden 目前只有 `reference_impl`／`synthetic`，**沒有**官方 Lua 核對或實機擷取。

## 5. 官方資源來源（0-6 的依據）

- 入口 `https://wlreftp.chinesegamer.net/WLN/TW/` 對應的實際主機是 `wlreftpsrc.chinesegamer.net`。**必須跟隨轉址，不可寫死。**
  2026-10-27 實測：網址含結尾 `/` 時直接回 200；不含 `/` 時回 **301**（原本記載的 302 未觀察到）。
- 根目錄（2026-10-27 觀察）：版本資料夾 `1.0.0`、`1.3.20`、`1.3.21`，`Voice/`，`DownloadUrl_{PC,ANDROID,IOS}.txt`，
  `ResourcePath_{PC,ANDROID,IOS}.dat`（約 124～164 bytes；2026-10-27 已確認**不是二進位**，是帶多餘尾逗號的 JSON 版本對照表，
  見 `spec/behavior/official-resource-path.md`），`web.config`（列表可見，GET 回 404）。
- `1.3.21/`：公告文字與圖片、`LuaScripts/`（`Lua/` 與 `LuaScriptPathList.txt`）、`ResourcesPC/`（`AssetBundle/`、`Config.txt`、`ServerList.txt`、`VerifyServer.txt`）、`ResourcesAndroid/`、`ResourcesIOS/`。
- 規劃中的同步流程（**推測，尚未驗證**）：啟動時讀 `ResourcePath_*.dat` 或最新版資料夾 → 與本機 manifest 比對 → 只下載差異。
- 開發這段的環境需要能連官方伺服器。先前記載雲端沙箱連不上（代理回 403）；**2026-10-27 的雲端工作階段可以連上**，
  0-6 的掃描就是在雲端執行。之後的環境不一定都能連，連不上時改由本機執行。

### 0-6 具體工作

1. 判讀 `ResourcePath_PC.dat` 格式，寫成規格（`spec/behavior/`）。
2. 讀 `LuaScriptPathList.txt`、`Config.txt`、`ServerList.txt`、`VerifyServer.txt`，**只把欄位格式寫成規格**。
3. 寫 `tools-python/probe_official.py`：列目錄、記錄每檔大小與 SHA-256、輸出 `manifest.json`，並與上一版 manifest 做差異比對。
4. 下載內容只放本機快取（如 `~/.lala-cache/`，已列入 `.gitignore`）。
5. 把 manifest 的**檔名、大小、雜湊**回報給使用者，作為升級 golden 到 `official_lua` 的起點。

## 6. 硬性限制（來自使用者的專案指示）

- 一律使用台灣繁體中文回覆與撰寫文件；技術名詞可保留英文。
- 不捏造資訊、測試結果、執行紀錄；只有實際成功的操作才能標示完成；沒跑的標「尚未執行」。
- **官方原始資源（Bundle、原始 TextAsset、Lua 原檔）不得進入公開 repo 或 PR。**
- 帳號、密碼、Token、API Key、**伺服器位址清單（`ServerList.txt` 內容）**不得寫入程式碼、Log、文件或 GitHub。
- 只做 GET 與目錄列表，並限速（每秒不超過約 2 個請求）。
- 只在 `next/` 新增檔案，不修改 `wlre/`；版本維持 v0.6.1（純文件／檢測不升版）。
- 使用獨立分支與 PR；**未經明確授權不得合併 main、刪除分支、建立 Release Tag。**
- PR 標題格式：`[vX.Y.Z] 具體修改重點`（繁中，不用「更新」「修正」等模糊字眼）；桌面版與 Android 版版本號各自獨立。
- Commit 結尾加上 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` 與 `Claude-Session: <URL>`；PR 說明結尾加 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`。
- 回報格式：已完成、修改內容與影響、測試結果（已執行／未執行）、未完成與風險、下一步。

## 7. 驗證指令

```
python3 -I next/tools-python/gen_golden.py   # 在舊 repo 根目錄；會覆寫 golden/
python3 -I next/spec/verify_golden.py         # 獨立驗證，全部相符回傳 0
python3 -I next/tools-python/analyze_deps.py  # 依賴盤點
python3 -I -m unittest discover -s next/tools-python -p 'test_*.py'   # 0-6 離線測試（不連網）
python3 -I next/tools-python/probe_official.py scan --base-url <第 5 節的入口網址>   # 連官方 CDN，輸出到 ~/.lala-cache/official/
```

## 8. 尚未涵蓋、不能假設的事

- `SessionLogic.command` 拒絕規則、`flush_events`／`advance_services` 定時行為。
- `decode()` 子解碼器 `or` 串接是否有 `(main, sub)` 重疊。
- `coordination.py`、`reservations.py`、`connection_health.py` 的行為規格；`battle_unit` golden。
- 完整 1,198 項舊測試（雲端環境無 `tkinter`，尚未跑）。
- 26 個循環模組中哪些是執行期核心規則、哪些只是資料來源。
- 另一個 Claude Code 工作階段的分支 `claude/refactor-ophtp9` 做了什麼（本 repo 看不到，需使用者提供 log／diff）。
