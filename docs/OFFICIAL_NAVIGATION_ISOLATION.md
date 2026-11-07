# 三份舊導航資料隔離實驗

2026-11-07，本機兩端實驗完成。這是可逆的獨立預覽試驗，**不是解除正式移動防護，也不是整個 LaLa 無種子安裝已通過驗收**。沒有修改使用者電腦、既有安裝或原本的資料庫；最初隔離結果在本機保存；擴大測試另依授權更新草稿 PR。

## 實作

`tools/isolated_navigation_trial.py` 只接受全新的工作目錄，從目前 repo 複製 tracked 程式／資產，不複製 `.git`、使用者資料或帳密。Android 未追蹤但經獨立驗證的 seed 另外複製。原始檔案不搬移。

副本中的 `resource_catalog_seed.sqlite3` 目前僅含 `navigation_data.zip`、`graph_origins.json`、`stage_coordinates.json`，整個副本 seed 移至 `quarantine/`；不修改其 BLOB，也不把三份資料解包成備援。原始／隔離 seed SHA-256 為 `ddca8cb85211e6554f86bf45ad879a2ef5b4c021e14c5f3bd7e3c1db15a7d323`。

子程序使用獨立 LOCALAPPDATA、KIVY_HOME、程式路徑與導航資料庫。診斷 audit hook 拒絕讀取原 repo、隔離區及舊導航檔，離線模式拒絕 socket 連線；線上模式僅允許官方 HTTPS request 與既有環境代理傳輸。這是受控診斷護欄，不是針對惡意 Python 的作業系統安全沙箱。未移除或略過產品版本／checksum／正式移動權限檢查。

## 實際結果

桌面 Python 3.12 與 Android Python 3.11 host 各完成一次全新線上實驗；Android host 不等於手機。來源為 `wlreftpsrc.chinesegamer.net`，下載前後核對同版官方資訊，版本仍為已驗證 1296（Data 1.3.23／exe 1.3.0）。identity/stages 是先前校驗的同版快照；本次未重新抽取所有核心資料表。

每端下載兩個一般地圖模型 10001、12050 所需的四個 Bundle，合計 10,196,269 bytes。沿用每模型最多兩檔／32 MiB 的上限，核對 Manifest、Bundle、外部 CAB/path ID、cache SHA-256，再原子匯入全新的 navigation.sqlite3。

| 案例 | 結果 |
| --- | --- |
| 預覽子程序首次啟動、無導航 DB | 明確拒絕，未用舊幾何 |
| 官方下載 → 校驗 → 建庫 → 一般地圖預覽 | 10001、12050 均成功；完整 XYZ 與禁止移動標記保留 |
| 注入 Bundle 傳輸失敗 | 拒絕並記錄失敗，先前可用快照不變 |
| 注入版本觀測／離線失敗 | 拒絕並保留可用快照 |
| 新版 identity 查舊版 DB | 無可用結果，不跨版本回退 |
| 觀測版本與請求版本不同 | 在下載前拒絕；此項為受控測試輸入，不代表官方真的發生更新 |
| 移開實驗 DB、建立新 Repository | 明確拒絕；復位後可再次載入 |
| 實際預覽點列送入原有 Movement.start | 原有權限閘門拒絕，未啟動，tick 回傳零封包；沒有遊戲連線 |
| 額外呼叫三份舊資料讀取入口 | 全部缺檔拒絕；正常預覽階段舊資料存取次數為零 |
| 正常完整種子自檢 | 缺 seed 時仍拒絕；沒有為實驗改鬆產品安裝／包裝契約 |
| 還原 | 從 quarantine 複製回實驗副本，checksum 與 verify_seed 通過；隔離備份保留，不覆蓋已存在目標 |

本次相關安全與還原回歸兩端各 26 項通過。原來兩個 repo 的 seed checksum 不變。

本機證據：
- `/workspace/validation/isolation-desktop-online-final/report.json`
- `/workspace/validation/isolation-android-online-02/report.json`
- 各目錄的 `isolation.json` 記錄原始程式提交、工具 hash、快照 hash。
- `/workspace/validation/isolation-desktop-final` 是已實際還原的離線控制副本；兩個線上副本仍維持隔離。

## 重跑與還原

需要依賴已安裝的 repo、現有已驗證 seed、同版 identity/stages 快照，且目標目錄不存在。下列為開發環境命令，不是給使用者登入中的安裝直接執行：

```sh
WLRE_OFFICIAL_RESOURCE_HOST=wlreftpsrc.chinesegamer.net python -B -m tools.isolated_navigation_trial \
  --workspace /path/to/new-isolated-trial --snapshot /path/to/verified-snapshot --download
python -B -m tools.isolated_navigation_trial --workspace /path/to/new-isolated-trial --restore
```

無網路重跑可改用 `--cache-dir /path/to/reviewed-extracted-caches` 取代 `--download`；報告會明確標示沒有新下載。還原只動作於實驗副本，拒絕 checksum 不符與覆蓋既有目標。

## 還不能做什麼

- 尚未完成沒有種子的整個 GUI 首次啟動、所有官方表自動擷取、全地圖覆蓋，以及 Windows／Android 裝置測試。兩個模型短距離預覽不能代替這些驗收。
- 非水平點列不等於角色已貼地、避障或安全通行；執行期 modifier／碰撞／到達語意仍有既有缺口。
- 隔離舊資料不能當作新資料的移動授權證據。現有條件不足以讓此試驗直接操作真實角色；正式移動仍禁止。下一步可在隔離安裝中驗收顯示、同步、版本失效與不送包行為；實際角色測試需要另外取得必要證據與有限範圍測試方案，不能只切開關略過防護。

既有 PR 保持草稿，不合併、不發布；這份實驗本身不是完整正式驗收。

## 全清單與完整程式入口擴大測試

新增 `--all-maps`：先核對同版官方 Main Manifest，再分類全部非小屋場景；
只下載已經過格式驗證的模型，整次測試 Bundle 上限為 64 MiB，保留原有
每模型 2 檔／32 MiB 上限。未確認格式的模型不猜測、不自動匯入。

兩端獨立從官方下載的結果完全一致：

| 分類 | 模型 | 場景 |
| --- | ---: | ---: |
| 已驗證格式、完成本次下載／校驗／建庫 | 17 | 46 |
| Manifest 有候選資源，但格式尚未驗證 | 753 | 1,077 |
| 缺少唯一可確認的官方場景資產 | 202 | 210 |
| 非小屋總數 | 972 | 1,333 |

另 4 個小屋相關場景排除；不是一般地圖缺漏。17 模型 Bundle 合計
44,296,157 bytes。對全部 46 個已建庫場景，各抽取陸／海／空的鄰接節點
查詢，共 138 項：93 項可產生預覽、45 項沒有該模式允許通行的節點而
安全停止。沒有用單點路徑假裝完整路徑通過，但這仍是鄰接抽樣，不是
任意起終點、全障礙與全地圖實際移動已驗證。

證據是 `isolation-allmaps-desktop/report.json` 與
`isolation-allmaps-android/report.json`，位於 `/workspace/validation/`；
`coverage.models` 列出每個模型與其所有場景 ID，`coverage.samples` 列出
模式、可用／停止原因及 XYZ。兩端 coverage 完全一致。

`tools/check_isolated_application.py` 使用既有隔離副本、全新 app-cold
私人目錄與虛擬顯示器，執行真正程式入口，而非只匯入預覽類別。
它不繞過登入或移動閘門；桌面測試只以 UI fixture 顯示主畫面，不登入。

首次桌面實驗重現首頁 HomeMap 立即開啟 navigation_data.zip 導致整個
App 初始化失敗。已修正為需要舊幾何時才讀取；舊導航視窗在開 Toplevel
之前先驗證來源。當三份舊資料缺失，導航按鈕改開獨立官方預覽；損壞
資料仍顯示錯誤，不當成缺檔悄悄換源。正式 Movement 防護不變。

停用自動資料同步的無網路冷啟動結果：桌面真正入口顯示主畫面、開啟
官方預覽，尚無 Runtime 時明確要求同步；GitHub／官方版本 metadata
查詢被實驗攔下，沒有網路連線。Android 真正 LaLaApp host 入口能建立
登入畫面、官方驗證 widgets 與預覽視窗，session 數為零；原生 Android
Service／Keystore／手機生命週期仍未驗證。對應證據為
`isolation-cold-desktop/cold-start.json`、`isolation-cold-android/cold-start.json`。

```sh
# 在先前隔離指令後增加 --all-maps，即進行全清單分類及已驗證模型下載。
python -B -m tools.check_isolated_application --workspace /path/to/isolated-trial --platform desktop
# Android host 使用 --platform android；需可用顯示器。
# --online 僅用於另外的乾淨副本，讓原本啟動同步流程照常執行。
```

不能重用已存在的 app-cold 目錄來聲稱冷啟動。套件完整性 self-test 仍
要求正式 seed，未放寬發佈契約；這階段沒有移除正式打包資料。


### 真正桌面線上冷啟動與最終回歸

在另一個全新副本／空 app-cold 目錄，啟用原本 `WLRE_Client.main` 的
launcher 官方同步，沒有注入假 Runtime 或略過版本檢查。實際觀測到
server_list_ready、runtime_identity_verified、runtime_bundle_ready、
raw_rebuild_ready 與 official_catalog_stored。回執為 verified_official、
data_compatibility=compatible，寫入五個 SQLite：官方 catalog、規範
inventory、emoji、smallmap images、item images。原有下載配額未變。
程式原本的官方 cgdl HTTPS metadata 來源也允許，最終沒有被測試護欄
攔下的 request。

主畫面可顯示；測試在 UI 開啟後短時間結束，未等待／強制完成登入前的
正式 Runtime 啟用。觀測時 current_runtime 為空，官方預覽明確要求
完成同步，並未偷偷使用舊資料。回執仍為 assets_ready=false、
protocol_compatibility=unverified、can_send_packets=false。因此可確認
「無種子啟動並擷取／校驗／入庫」，不能宣稱「正式角色功能全部就緒」。
完整原始回執與啟動階段位於
`/workspace/validation/isolation-cold-desktop-online-final/cold-start.json`。

最終本機完整回歸：桌面 1,892 項，OK、3 skipped；Android host
1,575 項，OK、4 skipped。本次使用可用虛擬顯示器與 IPC，不能把之前
環境中跳過的結果冒充這次實機測試；仍未執行手機／APK／遊戲正式服。

桌面原 PR #72 已由使用者合併，這些追加成果使用新獨立分支
`codex/seedless-navigation-preview`，不再推送已合併 PR 的分支。Android
仍更新原草稿 #71，source lock 對應新的桌面提交。均不合併、不發布。

### 單視窗啟動整合備註

以上線上冷啟動數據屬於原 PR #74 head `4c645501`。合入單視窗啟動後，桌面驗收工具已改為監測實際準備入口，等待資源準備及官方檢查完成；線上任一階段失敗會明確回報。本次僅補跑離線回歸，沒有重做線上下載或官方服驗收；既有歷史數據不代表新整合版的線上結果。Android 流程未更動。

## 562 張小地圖換源補完（桌面獨立草稿，2026-11-07）

以 main `cdd8ed2`（7.3.1）完成獨立驗證，後依使用者指示整合至每日助手 PR #76 最新 head `71284e69`；不修改 Android 或使用者安裝。逐一核對全部 562 個小地圖模型、799 個對應場景，不再只停在 Manifest 候選。開始與結束均重新核對官方 Main/Data 的版本與 hash，仍為 Data 1.3.23、MainPackage 1296。

- 1,123 個唯一完整 Bundle，719,973,958 bytes，逐檔驗證長度、MD5、CRC；來源為官方 HTTPS，既有 17 個模型的已驗證 Bundle 可重用，但仍重新驗證。
- 562 個模型均完成實際 CAB/path ID 指標解析及 A* 4.3.60 格式檢查。
- **558 個模型／795 個場景**可使用官方資料庫預覽，固定 SHA-256 已納入程式。原 17 個非房屋支援增加 541 個；註冊表另保留原有 3 個房屋相關 pin，但一般導航仍拒絕房屋。
- **4 個模型／4 個場景**（12366、12507、12512、12662）因 XZ 投影退化仍安全阻擋。未刪三角形或重新編號以勉強通過，也未納入支援名單。
- 558 模型各抽樣陸／海／空：1,160 項相鄰節點預覽，514 項沒有可用相鄰節點對而安全停止。沒有把單節點查詢算成路徑成功；這不是任意起終點、動態障礙或實際移動驗收。

特殊共享來源不再靠檔名猜測：10082 的正式場景指向自身 dependency 內名為 `11082` 的 TextAsset；15012 的正式場景指向 Manifest 明確宣告的 `15011_dependency` 內名為 `15011` 的 TextAsset。兩者均實際核對精確 CAB/path ID，保留每模型兩檔／32 MiB 限額，並以個別快取 SHA-256 固定內容；未知別名仍拒絕。

完整逐模型證據見 [官方 1296 稽核清單](official_navigation_1296_audit.json)，含小地圖名、場景、Bundle 校驗資訊、CAB/path ID、快取 hash、三角形數與三模式結果。官方原始 Bundle／快取不提交倉庫。`tools.review_navigation_candidates` 可用可信 Manifest SHA-256 與本地完整 Bundle 重做唯讀格式檢查；它不修改支援表、不匯入資料庫、不授權移動。原隔離實驗 `--all-maps` 的整次 64 MiB 上限未放寬，不能用它一次下載現在全部支援模型；一般 UI 仍逐模型同步。

### 正常入口、歷史相容與首次啟動

依使用者後續要求，一般導航按鈕只開官方預覽，歷史種子入口已移除。首頁官方小地圖座標不再嘗試 Coordinates／舊 origins，也不載入舊 Repository 網格；官方資料缺少時顯示未同步並停止。沒有刪除或修改任何使用者 seed／資料庫。

預覽帶入首頁選中場景；若不是角色當前場景，起終點留空，避免套用其他場景座標。介面顯示同版場景→模型→小地圖對應，圖片未同步或版本不符時明示，不宣稱圖像／導航疊圖已驗收。原資料比對顯示舊 seed 只有548模型的靜態三要件齊全，14個仍有資料缺漏或場景差異，不能當作官方幾何備援。

沒有導航 DB 時要求明確同步；版本更動、未知快取、格式不符、下載失敗與損壞均 fail closed。這次在獨立空 DB 對558模型執行真實匯入、重新載入與錯誤版本拒絕；完整程式無種子 GUI 冷啟動仍以此前歷史驗收為準，本輪沒有重做、不把非GUI測試當成新實機結果。正式套件 seed 自檢契約未改。

所有結果仍為預覽，`can_send_packets=false`。房屋僅進入／離開；未驗證路徑不控制角色。不合併、不發布。

本輪最終本機回歸：2,074項，OK、202 skipped（主要為無DISPLAY的GUI相關測試）；語法編譯、strict-git倉庫檢查、seed self-test與UnityFS native codec self-test通過。沒有執行使用者桌面GUI；跨平台CI與草稿PR狀態另行列示，不冒充Windows/macOS實機驗收。

### PR #76 官方來源限定整合

依使用者指示整合到既有每日助手 PR #76，不建立新 PR。一般桌面入口、小地圖投影及 CLI 的 map/nav 查詢改用目前官方 Runtime 與同版衍生 DB；缺資料不回退三份舊離線導航檔。官方小地圖不再以舊網格標示可移動；未同步的預覽需明確同步選定模型。實際 Movement／Roaming 尚無正式驗收來源，預設在讀歷史資料之前安全拒絕，不以換源為理由解除移動閘門。明確傳入測試依賴的單元測試契約保留。

歷史解碼程式／原始隨附資料留存供稽核，未刪除；不再提供普通UI的歷史入口。整個產品的安裝seed自檢契約仍保留，與導航執行期不讀seed是不同驗證範圍，不能宣稱整個產品所有功能都已移除離線資源。

最新真正隔離副本已移開 seed，audit hook 禁讀 seed、三份舊導航檔、原始 checkout 與 quarantine。使用本次官方校驗的 cache 與 ScenesData 快照，在空DB匯入558模型，逐795場景跑三模式，共2,385項：1,636項相鄰路徑預覽、749項無相鄰可通行節點而安全停止；558次異版本載入均拒絕。正常階段舊資料讀取0次，最後故意讀隔離seed的護欄控制也確實拒絕。預設實際移動／徘徊不讀seed且拒絕啟動、0封包。此為無GUI隔離驗證，不是完整GUI首次啟動或正式服驗收；[結果及實測程式hash](official_navigation_seedless_pr76.json)。

整合每日助手與最後官方來源限定後，完整本機回歸2,100項，OK、209 skipped；compileall、strict-git audit、seed／UnityFS自檢及Windows／macOS arm64／x64 build dry-run通過。三平台CI以PR最新提交為準，舊head成功不代替這次結果。
