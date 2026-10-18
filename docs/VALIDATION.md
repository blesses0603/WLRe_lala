# 驗證結果

## 2026-10-19 第 10 項跨平台最終自動化驗收

- 第 10 項 PR #19 Commit `d72f3de`：原始碼完整三平台回歸（Linux、Windows 2022、macOS arm64）在 [39171233034](https://github.com/blesses0603/WLRe_lala/actions/runs/39171233034) **全數 success**；原生 Windows x64 EXE、macOS Apple Silicon arm64 APP 與 Intel x64 APP 編譯、自檢、驗證、封裝在 [39171233020](https://github.com/blesses0603/WLRe_lala/actions/runs/39171233020) **全數 success**，並產出三個 CI artifacts。
- 本項文件及 Git 資產嚴格稽核 20 份 Markdown、191 個相對連結、0 失效連結、0 非空重複檔；完整回歸保留第 07 項 EXP 效率修復。
- 自動化驗收範圍完成。macOS Intel 真正圖形介面啟動、使用者 Windows 實機操作、正式伺服器端到端功能、Apple Developer ID 公證與 Gatekeeper 仍需獨立實測。
- 本項沒有變更 `wlre.__version__`，也沒有發布 `v0.6.0`。


## 2026-10-19 第 10 項啟動與補測：驗證狀態區分

- 第 09 項 Commit `4e3abc0`：三平台回歸 [39141397498](https://github.com/blesses0603/WLRe_lala/actions/runs/39141397498) 全成功，Windows x64 與 macOS Intel／arm64 原生打包 [39141397522](https://github.com/blesses0603/WLRe_lala/actions/runs/39141397522) 全成功；此紀錄屬該版本，不代表之後每筆提交通過 CI。
- PR #18 合併後日常 CI 只自動跑 Linux；Windows／macOS 的原始碼回歸及原生打包可手動啟動；GitHub Actions 額度不足時，新的 Runner 在開始執行測試前即失敗，不可當作程式回歸失敗。
- 第 10 項初始盤點 286 個追蹤檔，未發現非空的完全重複檔；19 份 Markdown 發現兩個失效路徑，已列入本項修正；詳見 [第 10 項稽核](PHASE10_AUDIT.md)。
- 第 10 項的新提交尚未取得跨平台 CI 完成紀錄，完整回歸、正式伺服器與使用者實機操作仍待驗證。不變更已修好的 EXP 效率邏輯。


- PR #19 Commit `b23b804` Ubuntu CI [39147669166](https://github.com/blesses0603/WLRe_lala/actions/runs/39147669166)：417 tests、2 skips，GUI 冒煙、資源自檢及 Windows Nuitka dry-run 成功。新增嚴格 Git 稽核、全檔語法與 macOS 雙架構 dry-run 後需以**新提交的 CI** 驗收，不能借用上次成功結果。

- PR #19 Commit `84b5450` Ubuntu CI [39162452731](https://github.com/blesses0603/WLRe_lala/actions/runs/39162452731)：423 項測試（2 項條件略過），全檔 Python 語法、嚴格 Git index 稽核、GUI 冒煙、資源自檢，以及 Windows/macOS ARM64／Intel Nuitka dry-run 均通過。該次嚴格稽核掃描 18 份 Markdown；最後補上資源署名 SOURCE.md 共 2 份後，應以更新後結果另行驗證。

- PR #19 Commit `34add166` 最終完整 Ubuntu CI [39162618822](https://github.com/blesses0603/WLRe_lala/actions/runs/39162618822) success：423 tests（2 skips）、Linux GUI 冒煙、資源自檢、Python compileall、Windows/macOS 雙架構 Nuitka dry-run 全通過；嚴格 Git 稽核覆蓋 20 份 Markdown／191 個相對路徑，0 斷鏈及 0 非空重複 blob。Windows/macOS 本版原生驗證仍待手動觸發。

## 2026-10-17 優化工作區

- v0.4.21 發布預檢：以假的 gh CLI 執行工作流程內的實際 Bash 步驟，驗證有效且未發布標籤可傳遞、`Ver.0.4.20`／其他錯誤格式在遠端請求前被拒絕、缺少標籤及已發布版本會提早停止。核對四項官方 Action 的指定版本皆採 Node.js 24；176 項中 174 通過、2 項原生平台略過，actionlint 與版本標籤預檢通過。

- 打包更名 `WLRe_LaLa`：Windows／macOS 皆明確設定 Nuitka output-folder-name，避免資料夾仍沿用 Python 入口名稱；檢查 EXE／App、ZIP 內容根目錄與封裝路徑同步。172 項中 170 通過、2 項原生平台略過；兩平台打包 dry-run、actionlint 及 diff 檢查通過，實際產物待新版本 Actions 編譯。

- macOS Actions：172 項中 170 通過、2 項略過（Windows DPAPI／原生 macOS ditto）。新增 Apple Silicon／Intel 原生架構與平台拒絕、macOS 專屬編譯參數／完整資源、plist 入口驗證、ditto 指令／ZIP CRC／獨立 SHA256、CRC 失敗保留舊檔，以及 GUI CLI 建立與清理測試。兩架構 dry-run、Linux 桌面 GUI 自檢、actionlint 1.7.12 及 diff 檢查通過。核對官方 runner-images 文件的 `macos-15` ARM64／`macos-15-intel` x64 標籤；原生 macOS 編譯、簽署驗證與 ditto 捷徑／執行權限測試仍待新版本 Actions 實跑，未宣稱 Mac 成品已驗證。

- v0.4.20 Windows CI 修正：將 Tk `focus_displayof()` 固定為無焦點，成功重現與 Actions 完全相同的兩項失敗；修正測試前景條件及每項分頁重設後，同一重現情境兩項均通過。完整 162 項中 161 通過、1 項 Windows DPAPI 略過；背景暫存／回到前景恢復的專用測試仍通過，正式 UI 行為未調整。版本標籤預檢、資源自檢、actionlint 及 diff 檢查通過。

- Releases 編譯改用已在使用者 Windows 成功的 `--diagnose-compiler` 方式；28 項打包／診斷／發行封裝測試與 actionlint 檢查通過。GitHub 雲端編譯與發布結果以 Actions 實際執行為準。

- 可選編譯診斷模式：162 項測試中 161 通過、1 項 Windows DPAPI 略過；驗證預設保留快取、standalone／onefile 診斷模式僅新增 `--disable-cache=ccache` 與 `--show-scons`、CLI dry-run 正確轉傳且不編譯。核對 Nuitka 4.3 的 `--show-scons` 會啟用 SCons `--debug=stacktrace`；資源自檢與 diff 檢查通過。尚未在使用者 Windows Python 3.14.8／MSVC 14.5 實測，根因仍需新的診斷紀錄確認。

- 打包 pip 自動修復：159 項測試中 158 通過、1 項 Windows DPAPI 略過；新增健康環境沿用、pip 匯入失敗後重建／再驗證、修復仍失敗即停止及新環境建立測試。資源自檢、打包 dry-run 及 diff 檢查通過；尚未在使用者 Windows Python 3.14.8 環境實際重建及編譯。

- 自動 Releases：155 項測試中 154 通過、1 項 Windows DPAPI 略過；新增標籤版本不符拒絕、完整資料夾 ZIP 內容／SHA256、缺少或空 EXE 拒絕、CRC 失敗保留舊檔並清除暫存檔測試。actionlint 1.7.7、打包 dry-run、版本預檢、資源自檢及 diff 檢查通過。尚未觸發 Actions Windows 編譯或正式 Releases 發布；首次推送版本標籤後仍需確認雲端執行結果。

- 最小化修正：驗證存在 Windows HWND 時仍使用 Tk iconify、縮小期間排隊的 Map 事件不恢復外框、還原後只切換一次外框，以及子元件事件／已關閉／已隱藏視窗的處理。151 項測試中 150 通過、1 項 Windows DPAPI 略過；資源自檢通過。此環境為 Linux，尚未實測 Windows Python 3.14 的工作列最小化與還原。

- 材料表新增桌面測試：圖示在左側而非樹狀縮排、標題列高度縮小、模擬拖動分隔線不改變欄寬，點擊仍能選取材料列。

- 新增經驗效率按鈕右側對齊、提示數量更新重建後仍保留位置，以及點擊／鍵盤切換測試。
- 驗證登入視窗不再顯示驗證勾選，登入按鈕直接啟動驗證優先流程；測試使用模擬連線，未連線正式服。
- 本次 146 項中 145 通過、1 項 Windows DPAPI 略過。

- 製作詳情固定全高驗證：工具列未侵入詳情欄，詳情與左側頁首對齊，沒有拖曳分隔或捲動條，五種材料的完整列與加入按鈕均可見，名稱欄固定窄寬。
- 自動戰鬥規則優先序說明改放在規則內容內，避免佔用補給分頁的垂直空間；重新驗證兩側補品填滿後的門檻控制項邊界。

- 製作同頁顯示與收藏按鈕調整後：143 項中 142 通過、1 項 Windows DPAPI 略過。驗證 12 項與詳情同時可見、批數更新材料需求、收藏圖示切換與獨立點選範圍；單獨製作視窗亦完成建立與關閉檢查。

- 補給頁合併後驗證 HP 左／SP 右、各 10 格填入實際補品後仍可見、所有門檻滑桿與控制項未超界、共用啟用開關與獨立百分比收集／還原，以及主頁補給入口。
- 本次 141 項測試中 140 通過、1 項 Windows DPAPI 略過；資源自檢與 diff 檢查通過。

- 帳號設定改為伺服器範圍：驗證官方同伺服器不同分流共用、不同帳號與地球／水星隔離、自訂主機不會因分流 ID 被誤合併。
- 驗證最新舊分流設定沿用、新共用設定優先、原檔保留，以及損壞舊檔不被覆寫；140 項測試中 139 通過、1 項 Windows DPAPI 略過。

- 製作項目改為每頁 12 個（4 欄×3 列）：確認全部卡片、32px 圖示與右側地圖／聊天可見；新增 12 項翻頁順序與搜尋後回到第一頁測試。
- 本次 137 項測試中 136 通過、1 項 Windows DPAPI 略過；Windows 實際版面仍待更新後確認。

- 連續煉金新增測試：模擬完整執行 7 次、24 種回覆順序、確認後不立即續送、戰鬥／補給後保留間隔，以及逾時正確指出缺少回覆且不重送。
- 本次全部 136 項測試：135 通過、1 項 Windows DPAPI 略過，資源自檢與 diff 檢查通過。節流是否改善使用者正式服的第一輪後停止問題仍待實測，沒有以單張截圖推定確切缺包原因。

- 全介面重排：主頁卡片、組隊雙欄、煉金表單／狀態分區、經驗摘要與表格，以及功能視窗的標題與操作列。
- 內容區加入襯底；標籤、按鈕與父區塊使用相同的合成背景位置，並依可見版面更新影像快取。
- 新增桌面測試：逐頁檢查可見操作控制項未超出內容區、資訊卡與標籤襯底一致、小戰場長名稱可查看完整資料且點選行為保持正確。
- Linux／虛擬桌面全部 132 項測試：131 通過、1 項 Windows DPAPI 略過；資源自檢、打包 dry-run 與 diff 檢查通過。Windows 原生外觀與正式服操作仍待實機複測。

- 本次重排：五個主分頁，右上 380×320 固定小地圖（清單不收合），右下事件紀錄／戰場陣形切換，必要隊員名單移到組隊。
- 已驗證小地圖實際尺寸、清單可見、切換後戰場與聊天可見、隱藏事件紀錄仍持續累積、必要隊員設定在組隊內未超界、一般字體 14px，以及 AI／補給設定入口仍可操作。
- 主頁、製作、功能視窗與帳號設定回歸測試通過；原生 Windows 字型與正式服操作效果仍待實機檢視。

- Linux／Xorg 虛擬桌面：147 項測試中 146 項通過，1 項 Windows 原生 DPAPI 測試略過。
- 涵蓋主頁版面、隱藏分頁切換、背景聊天與事件暫存、製作詳情與進度、帳號設定隔離、跨程序寫入及崩潰後鎖釋放。
- 新增啟動依賴鎖與安裝後驗證測試，以及重複打包快取、需求變更失效、強制更新與失敗後清除快取測試。
- 戰鬥／徘徊外框移到三個子分頁的內容區，各自保留單層框線，共同外層不再畫框；已驗證切換後內容映射與邊框像素。
- 分頁與區塊外框簡化後重跑全部測試：126 項中 125 項通過、1 項 Windows DPAPI 略過；既有主頁幾何、分頁切換、製作畫面、AI 編輯器與功能視窗尺寸檢查通過。
- 依使用者錄影調整光環繪製：固定完整圓角遮罩，色彩循環的 alpha 像素保持一致，圓角外側與按鈕中央透明，避免分段繪線及銳化縮放外溢。Linux 200 次繪製測得中位數約 0.31ms、95 百分位約 0.45ms；不代表 Windows 實際幀率，錄影中的閃跳仍待 Windows 複測。
- 小地圖新增測試：等待角色地圖、換圖自動跟隨、相同地圖不重載、缺圖不沿用舊圖，以及移除地圖控制項與核對預覽入口；自動切圖不送出移動或換圖指令。
- 新增動畫依經過時間計算、重複狀態更新不重啟動畫，以及直邊／圓角色彩等距取樣測試；更新間隔約 16ms，實際幀率取決於桌面負載。
- 驗證七彩效果改變按鈕邊線像素、保留圓角外側背景、顏色隨動畫相位改變，停用後還原原始像素；Canvas 不再繪製外圍彩框。
- 光環按鈕改為標準 ttk.Button，驗證與其他主頁按鈕的寬高、padding 及控制項類型一致；移除舊 Canvas 容器背景測試。
- 逐頁檢查主頁、組隊、煉金、製作、經驗效率，以及三個戰鬥／徘徊子分頁：外框像素確實可見，緊鄰內側保留背景插畫；使用共用單層外框樣式。
- 主頁啟動／停止指令、確認後按鈕文字與光環、隱藏動畫暫停、離線清除、AI 設定入口與按鈕邊界測試通過。
- `python WLRE_Client.py --self-test` 通過。
- `python -m tools.build.build_nuitka --dry-run` 通過；未執行 Windows EXE 編譯。
- `git diff --check` 通過。
- Windows BAT、原生 DPAPI、EXE 編譯，以及正式伺服器多帳號操作仍待 Windows 實機驗證；未宣稱 CPU 或記憶體降低百分比。
- 本次為原始碼優化，未發布新版本 ZIP 或 EXE。

## v0.4.19 原始基準

- 77 項測試：76 項通過，1 項 Windows DPAPI 測試略過。
- 原始驗證紀錄包含 ZIP 關閉後的 CRC、解壓與 SHA-256 比對；本次沒有重新取得或驗證該 ZIP。
