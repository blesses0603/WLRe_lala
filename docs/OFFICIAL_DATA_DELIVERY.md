# 官方資料與安全預覽交付狀態

核對日期：2026-11-07。這是可審查的本機整合成果，**不是全面無離線資料版本，也不是可正式移動的新導航版本**。兩端工作分支均為 `codex/official-bootstrap-migration`；本次檢查基於桌面 `4720480`、Android `eed4a6b`，再加上本文件及 Android 測試能力探測修正。沒有推送、合併或發布。

## 可交付範圍與入口

- 官方資料同步、驗證、版本化規範 SQLite 及各類 consumer 已在同一分支整合；解析／匯入失敗不得把未驗證版本標為可用。未知格式拒絕，不承諾未知格式自動修復。各類來源、欄位與驗證詳見 `OFFICIAL_*_MIGRATION.md`、`OFFICIAL_*_DATABASE.md` 和 [規範資料庫](NORMALIZED_RESOURCE_DATABASE.md)。
- 桌面地圖視窗 →「官方資料庫預覽」：`wlre/ui/navigation_gui.py`、`official_navigation_preview.py`。
- Android 一般頁 →「官方導航預覽」：`android_app/pages/general.py`、`android_app/navigation_preview_ui.py`（Android repo）。兩端共用 `navigation_preview_job.py`，可從資料庫預覽、或明確選擇同步單一模型後預覽；單模型最多 2 個檔案／32 MiB。
- 預覽使用目前已同步 Runtime；版本、角色、場景或障礙 revision 改變會使結果失效。結果禁止送包。平面平滑遇到非平面資料拒絕，M12050 原生三維研究管線尚未當作產品移動演算法。
- 不登入、不連遊戲伺服器的批次比對入口是 `tools.review_navigation_shadow_samples`，指定歷史 identity/stages 快照與預先驗證的本機資料庫。`tools.compare_navigation_shadow` 和 `tools.preview_official_navigation` 會查 CDN metadata，不能稱為完全離線入口。
- 正式 `Movement.start` 必須同時具備 `can_send_packets=True` 與 `live_movement_verified=True`。目前新預覽與舊 Coordinates 路徑均不具備此權限：**一般地圖自動移動不能視為可用**。這不是可由 UI 開關略過的限制。小屋範圍只保留進出，不擴展室內尋路。

可整合為安全預覽候選版本；正式導航啟用與刪種子應另設驗收門檻，不能隨本次資料功能一起放行。

## 這次實際驗證

| 檢查 | 結果與限制 |
| --- | --- |
| 桌面完整 unittest discover | 1,886 項，OK，169 skipped；無圖形 display／xvfb，跳過不算 UI 驗收 |
| Android 完整 unittest discover | 1,568 項，OK，94 skipped；Python host，不是 Android 裝置 |
| Android 第一次完整執行 | 3 failures、1 error、90 skipped，皆在 Unix socket bind 被 sandbox 拒絕後失敗；保留原始記錄 |
| Android 修正 | 測試能力探測由僅建立 socket 改為實際 bind/listen；四項明確 skip，沒有修改產品 IPC 或豁免可用環境中的測試 |
| 兩端共用核心 | 188 檔 parity 通過 |
| 規範資源庫唯讀檢查 | 19 snapshots，全部 verified_checksum；只證明現有快照校驗，不是重新下載或最新版本聲明 |
| 1296 歷史導航樣本 | 17 模型、51 模式列、292 次成功、10 次經獨立連通檢查確認無路徑 |
| 新舊比較 | 35 組：8 可比較、27 不完整，不能稱 35 組等價；26 組舊 metadata 不符，另 1 組無路徑 |
| 同官方幾何控制 | 上述 27 組中 26 組新演算法可達並檢查成本、1 組無路徑；舊無標籤演算法 12 組採用了不允許通行節點／邊，不應讓新演算法模仿 |
| M12050 完整原生管線 | 前一提交兩端各 16 案例一致：13 完成、3 拒絕；分段 XYZ 全通過，未分段 11 案例有表面偏離。詳見 [導航證據 Phase 72](OFFICIAL_NAVIGATION_DATABASE.md) |

本機證據位於 `/workspace/validation/`：`delivery-desktop-tests.log`、`delivery-android-tests.log`（原失敗）、`delivery-android-final-tests.log`、`delivery-resource-database.json`、`delivery-shadow.json`、`phase72-desktop.json`、`phase72-android.json`。這些是本次工作環境路徑，不是假定使用者電腦已有檔案。

## 可重跑方式

從各自 repo 根目錄，以已安裝依賴的 Python 執行；資料根目錄使用獨立測試目錄，勿指向登入中的 LaLa。

```sh
WLRE_DISABLE_AUTO_CATALOG=1 PYTHONPATH=tests:. python -B -m unittest discover -s tests
# Android host：KIVY_HOME 指向可寫的獨立目錄；有 display 的環境另外跑 UI。
KIVY_HOME=/tmp/lala-test-kivy WLRE_DISABLE_AUTO_CATALOG=1 PYTHONPATH=tests:. python -B -m unittest discover -s tests
python tools/android_parity_audit.py  # 僅 Android repo
python -m tools.check_resource_database --database /path/to/resource_inventory.sqlite3
python -m tools.review_navigation_shadow_samples --snapshot /path/to/snapshot --output /path/to/report.json
```

最後一項需要同版 `current-identity.json`、`current-stages.json` 與資料根目錄中的已校驗 `navigation.sqlite3`，不是空資料根目錄即可執行。缺檔或版本不符應失敗，不以舊版填補。Windows 需按 PowerShell 語法設定環境變數；上列 shell 指令不是 Windows 安裝包。

## 三個不同的後續門檻

### 移除最後三份資料

目前 seed SQLite 仍含 `graph_origins.json`（23,651 bytes）、`navigation_data.zip`（10,204,892 bytes）、`stage_coordinates.json`（1,785,772 bytes）。

1. 一般地圖所需模型與座標映射的版本覆蓋，必須足以替代所有正式消費者；17 模型抽樣不是全遊戲覆蓋。
2. 正式玩家搜尋／modifier 設定、終點限制與三維路徑須有可重現證據；修正終點不能當成原目標抵達。
3. 必須驗證角色碰撞尺寸、動態障礙、貼地，以及陸／海／空實際行為；目前 sky tag 測試不代表飛行物理驗收。
4. 消費者換源後，測試零種子冷啟動、無網路／下載中斷／損壞／版本變更／回滾，並確認小屋進出與一般地圖不受影響。
5. 上述通過後才能移除 BLOB、打包引用與 source lock；不得先刪檔再以功能停用當作完成。

### 更新兩端草稿 PR

- 已知第一階段桌面 PR #72、Android PR #71；本次沒有查詢遠端，不能聲稱目前 PR／CI 狀態。相對先前已知發佈提交 `4aeab000`／`dd2d5a9`，驗證基線各有 69 個後續本機提交，另含這次整理；不是單一小修補。
- 需要授權推送後續範圍，先重新讀取遠端 HEAD／PR 狀態及衝突，再檢查完整差異、依賴與 seed lock。桌面先、Android lock 指向對應桌面來源。
- 草稿標題建議「官方資料庫換源與不送包導航預覽」。描述必須包含三個保留種子、一般自動移動尚不可用、測試 skipped／IPC 限制及未做實機驗收，不能標示全面完成。
- 推送後才有對該提交的 CI：桌面多平台、Android host／APK 建置及相關 native 工作流程。先前第一階段綠燈不涵蓋這些提交。

### 實際角色測試

- 先建立可重現的隔離 Windows／Android 測試版本，核對程式提交、官方版本、資料庫來源與裝置安裝；本次沒有新安裝包，也沒有遠端操作使用者電腦。
- 先測兩端顯示、同步、斷線、版本失效、前背景切換及小屋進出；預覽階段確認沒有移動指令。
- 官方客戶端可視畫面比對能驗證路線與停點的外部行為，但錄影不能揭露所有執行期參數或精確 vectorPath；目前沒有已驗證的完整執行期匯出方式。
- 新導航實際送包要另有具體、有限範圍的測試設計、必要證據與操作授權；明確起終點、步行／海／空模式、距離上限、即時停止與版本失效處理。不要求帳密，不繞過現有防護。
