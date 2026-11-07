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
