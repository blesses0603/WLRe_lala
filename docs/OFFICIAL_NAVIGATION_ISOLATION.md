# 三份舊導航資料隔離實驗

2026-11-07，本機兩端實驗完成。這是可逆的獨立預覽試驗，**不是解除正式移動防護，也不是整個 LaLa 無種子安裝已通過驗收**。沒有修改使用者電腦、既有安裝或原本的資料庫；本階段未推送。

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
