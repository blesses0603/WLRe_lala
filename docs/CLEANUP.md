# v0.4.18 清理紀錄

> 本頁為 v0.4.18 的歷史清理紀錄，不代表最新目錄；2026-10-19 第 10 項的最新重複檔、文件及版本核對請見 [第 10 項稽核](PHASE10_AUDIT.md)。

以 v0.4.17 Reorganized Fixed 為基底，檢查全部 Python 檔案、模組引用、資源檔名引用、BAT 入口與打包規則。

## 移除

- 15 處分區後未使用的 pathlib.Path 匯入，以及測試中未使用的 base64 匯入，共 16 處。
- CraftingBrowser.page_size：程式未讀取，實際版面由既有邏輯控制。
- App.right_panel、App.battle_frame、App.battle_tabs、HomeMap.map_combo：只賦值未讀取；保留實際元件建立與事件綁定。
- wlre/resources/portal_review.json：2,419,488 bytes，未被程式載入；目前逐圖核對使用 portals.json 內的 audit，完整報告仍使用 docs/Portal_Review_1262.html。
- docs/FILE_MOVES.json：重複的歷史搬移對照；STRUCTURE.md 同時移除重複對照段。
- README 過期批次說明，改寫為目前版本操作說明。

## 保留與原因

- 全部程式模組：均可由 GUI、CLI、建置或維護入口到達。
- 所有 __init__.py：套件及版本入口。
- item_icon_coverage.json：現有圖庫一致性測試仍使用。
- 地圖 HTML 報告、表情收集工具、導航 CLI：各有實際入口。
- State.unimplemented_count：封包診斷計數，避免變更狀態結構。
- 導航 nonmanifold_edges：網格診斷；模糊邊仍不連接。
- theme._glass_chrome：保留視窗元件生命週期。
- 自檢原本的 GUI 載入保留，增加 gui.main 可呼叫檢查。

## 判定範圍

Ruff F 規則、Vulture 候選人工核對、AST 模組可達性／無條件跳轉後死碼掃描。
靜態分析無法證明所有動態行為；不刪除 Tk 回呼、測試發現入口或伺服器協定分支。
未連線正式服，也未變更帳密格式或自動戰鬥規則。
