# PR #79：Desktop 介面移植與驗收

> 本文為最初介面批次的歷史紀錄。最新登入流程見 [桌面登入](DESKTOP_LOGIN_INTEGRATION.md)，全畫面／子視窗完成度以 [Python 對照盤點](DESKTOP_PYTHON_PARITY.md) 為準；不能從下方舊表推定全介面已完成。

## 範圍與基準

基準是 `main` 的 Python 桌面版 **7.3.1**（`0f8bf6a99a70070cea1aeec60a0d6ca93dbc581a`），C# 起點為 PR #79 的 `a08c719466ff591254fe22608737c926c24dbd09`。保留現有共用核心、Android 生命週期與 Python 程式。

本次使用者明確調整：**背包與特技各自獨立視窗，原「包包」名稱改為「背包」**。其餘介面還原既有桌面配置。

| 介面 | Python 來源（wlre/ui/） | Desktop 實作與版面 |
|---|---|---|
| 登入／選角 | `login_controller.py` | `Views/LoginWindow.cs`：伺服器／分流、帳號密碼、帳號清單、版本狀態、角色選取 |
| 主畫面 | `dashboard_builder.py`、`dashboard_layout.py`、`overview_ui.py`、`chat_ui.py` | `Views/DashboardWindow.cs`：1280×800、左 870／右 380、10 張卡片、圓形入口、聊天 |
| 背包 | `resource_view.py`、`bag_grid.py` | `Views/InventoryWindow.cs`：1040×700、6×4 格、搜尋、分頁、底部詳情、超空間袋 |
| 特技 | `resource_view.py` | `Views/SkillsWindow.cs`：獨立視窗、搜尋／選取、角色／夥伴 8 欄特技表、詳情與施放入口 |
| 戰鬥 | `battle_view.py` | `Views/BattleView.cs`：右下戰場陣形、16 格封包位置、HP 與選取邊框 |
| 地圖 | `home_map.py`、`official_navigation_preview.py` | `Views/MapView.cs`、`NavigationWindow.cs`：380×320 小地圖、傳點／NPC／怪物、導航表單 |
| 遠征 | `expedition/panel.py`、`controls.py` 等 | `Views/ExpeditionWindow.cs`：1080×650、時間／好友度／成功率、4:3:3 三欄 |
| 設定 | `auto_battle_ui.py`、`auto_battle/*`、`recovery_ui.py`、`maintenance_ui.py` | `Views/SettingsWindow.cs`：1080×720、角色／夥伴規則、補給、修理／整理、停止條件 |

背景沿用 `exp_background.png`，先 fit 到原 1280×800 畫布，較小視窗取中央區塊；主畫面／對話框分別疊 46%／60% 深藍遮色。功能圖示與按鈕沿用原 PNG，按鈕保留左右端點、中間伸縮。較小工作區採整體等比縮小，保留控件相對位置。

不同 UI framework 的字型度量、焦點與平台渲染有差異；本次驗證版面、素材與操作語意，沒有聲稱跨平台逐像素完全一致。

## 行為與整合邊界

| 已有本機行為 | 尚未接通的遊戲／資源行為 |
|---|---|
| 顯式開啟未連線桌面介面、視窗切換與關閉 | 正式登入、角色進入世界與 TCP transport |
| 背包搜尋、6×4 分頁、依格位選取；特技獨立搜尋／選取 | 補給、物品存取、特技施放 |
| 顯示 Core 不可變快照與明確空狀態 | 同版道具／技能圖片、成本與效果目錄啟用 |
| 戰場角色／目標選取、觀測位置與 HP | 真正戰鬥送出、自動戰鬥及徘徊執行 |
| 導航表單驗證、位置文字與缺資料提示 | 地圖圖片、傳點／NPC 列表、下載、路線與移動 |
| 遠征清單與本機設定草稿 | 自動派遣、好友度恢復與領獎 |
| 設定草稿編輯、JSON 匯入／匯出與保存 | 正式技能／補品資格核對、Core automation 設定套入 |
| 原離線封包檢查器 | 帳密安全儲存、真實聊天與其他未列入本次範圍功能 |

沒有資料時顯示「等待同步」或空清單；未知數值不是零，缺圖不以舊地圖或虛構物品補滿。`Ready`、`world_ready` 或資源旗標都不能把 `CanSendGameCommands` 改為 true。

## 資料與生命週期

1. `DesktopSession` 接收 immutable `ServiceStateSnapshot` 與同份 publication 的 `DesktopLabels`。`ReadView()` 原子取得兩者與 generation。
2. 同世代只接受遞增 sequence；重複、過期、前帳號或 Dispose 後的更新被拒絕。
3. 換身分清除快照、標籤、背包／特技搜尋與選取、戰場目標及登入密碼。
4. 視窗關閉解除事件訂閱；嵌入地圖／戰場 attach／detach 成對訂閱與解除。背景通知經 UI dispatcher 才變更控件。
5. 設定持有獨立草稿，取消只丟棄；`SaveBattle`／`SaveExpedition` 在同一鎖內核對 generation 與身分後寫檔。
6. JSON 上限 128 KiB、UTF-8 嚴格解碼、拒絕重複／未知欄位、檢查列數與範圍。暫存後原子 replace，Unix 設定檔 0600。
7. 儲存範圍是 C# 桌面預覽設定，不覆寫 Python 帳號檔，不保存密碼、Token 或遊戲快照，不啟動 AI／遠征。
8. 遠征在同一會話關閉時保留視窗草稿；換帳後重開會移除舊視窗並讀取新身分設定，不能沿用失效草稿。

## 驗收步驟

1. 啟動 Desktop，確認先看到登入／選角；登入與選角送出未啟用。按「檢視桌面介面」才開啟未連線主畫面。
2. 核對 1280×800 主視窗分欄、圖示、10 張卡片與聊天。一般啟動不得自行出現測試角色。
3. 同時開啟「背包」「特技」；其中一個搜尋或關閉不影響另一個。背包只有實際背包／超空間袋。
4. UI 自測以合成快照驗證跨頁、名稱／ID 搜尋、詳情更新、格位換物品與會話重設；失效後不保留錯誤選取。
5. 戰場核對 4×4 位置、HP、邊框。點選只改顯示；新場次或單位替換移除舊目標。
6. 導航測空值、NaN／無限、範圍外座標及合法格式；合法格式不能使缺資料變成成功路線。
7. 遠征／AI 設定測修改後取消、重開、保存及換身分後保存。取消無變更，保存有正確範圍，換帳拒絕。
8. 重複開關功能視窗後關閉主程式，確認全部結束；Windows／macOS 另驗字型、縮放、最小化與拖曳。

## 驗證紀錄

本輪在 Linux、.NET SDK 10.0.403、Avalonia 12.1.5 上實際執行：

| 驗證 | 實際結果 | 範圍 |
|---|---|---|
| Desktop Release 編譯 | 通過，0 警告／0 錯誤 | 全部新增 Desktop 程式與既有 Core 引用 |
| `--self-test` | 原離線封包檢查 9 項＋桌面模型 54 項通過 | 設定結構、重複／未知欄位、儲存、過期 publication 與會話切換 |
| `--ui-self-test --screenshots …` | 147 項檢查通過 | Xvfb 原生 Avalonia 視窗；包含 32 項 PNG 非空／解碼尺寸檢查 |
| 實際視窗截圖 | 16／16 張可解碼，已檢視版面 | 登入、主畫面、戰場／地圖、背包與儲藏、獨立特技、導航、遠征及設定五頁 |
| 相關 Core 回歸 | 6,322 項通過、0 失敗、0 略過 | Inventory、BattleEvent、WorldEvent、ExpeditionReceive、SessionEvent 測試群 |
| Android 生命週期回歸 | 59 項通過、0 失敗、0 略過 | 純 .NET lifecycle 測試，並非 Android 裝置／APK 安裝驗收 |
| Python 文件／倉庫檢查 | 5 項通過 | 發行摘要順序、版本限制、Markdown 連結、重複檔及既有回歸入口 |
| `git diff --check` | 通過 | 無補丁空白錯誤 |

Core 回歸重現指令：

```bash
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter 'FullyQualifiedName~Inventory|FullyQualifiedName~BattleEvent|FullyQualifiedName~WorldEvent|FullyQualifiedName~ExpeditionReceive|FullyQualifiedName~SessionEvent'
dotnet test dotnet/Lala.Android.Lifecycle.Tests/Lala.Android.Lifecycle.Tests.csproj -c Release
```

原生 UI 測試驗證背包與特技能同時存在、搜尋互不影響、格位重用清除舊選取、戰場目標失效、導航輸入、設定取消／保存、換帳清除，以及遠征隱藏後換帳重建視窗。合成快照明確標示「介面測試」；一般啟動不會載入這些資料。截圖先在記憶體編碼、檢查非空並實際解碼尺寸，通過後才寫檔。

提交後 CI 曾檢出 README 的 Desktop 新增說明擠到發行摘要之前，違反既有文件段落契約。已將說明移到 v7.3.1 發行摘要後，保留原摘要及測試，並實際重跑 `python -m unittest discover -s tests -p test_repository_hygiene.py -v`，5 項通過。

Windows／macOS GUI、安裝包、真實登入及正式伺服器遊戲操作尚未驗收。PR 沿用既有預計版本 **v8.0.20**；本輪未另行加版，Python 桌面 **v7.3.1** 與 Android **v0.2.0** 不變。PR 保持 Draft，不合併 main、不建立正式 Release／Tag。
