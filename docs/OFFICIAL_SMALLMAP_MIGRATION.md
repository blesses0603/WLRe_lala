# 第九階段：官方小地圖圖像資料庫

本階段桌面與 Android 同步實作，只保留本機提交，未推送／合併／Release。`smallmaps.zip` 已從種子 active、BLOB、來源 Manifest 與必要封裝清單移除並 VACUUM；剩餘 **13 項**種子，仍不是完全無離線資料的版本。舊使用者資料庫不刪除，但預設小地圖消費者不讀其歷史 ZIP。

## 官方來源與圖像匯入

Main Manifest 的精確 `Assets/ResourcesBuild/Texture/SmallMap2D/SmallMap2D_<model>.png` 路徑決定模型 ID；拒絕未知路徑、重複模型及超過 2,048 個資產的清單。現有下載器仍檢查完整依賴及 Bundle 大小／hash／CRC，不略過循環或任何驗證。

小地圖採獨立同步預算，預設最多 **64 MiB／4 個 Bundle**，不占原核心資料 32 MiB／24 檔預算。`prepare_dynamic_runtime` 可用 `max_image_download_bytes`／`max_image_downloads` 降低上限；上限不可超出預設，設為零可禁止新圖像下載。只有 `sync=True` 執行網路下載。當次真實小地圖 Bundle 為 43,187,027 bytes，因此不能放入原 32 MiB 核心預算。

驗證 UnityFS header 後，以每個精確 AssetPath 尋找唯一 Texture2D，僅接受已核對的 1024×1024 圖像。使用 UnityPy 解碼並轉 PNG，限制單張 PNG 4 MiB、全批 PNG 96 MiB。原始 Bundle 保留於官方快取，來源 SHA-256／資產清單寫入圖像版本 provenance；快取命中仍驗證官方 Bundle，提交前再次核對來源未變。

## SQLite 與失敗處理

新增 `derived_catalogs/official_images.sqlite3`，獨立 schema version 1：

- `image_versions`：完整官方 catalog identity 與不可變來源指紋。
- `map_images`：同版模型 ID、精確資產路徑、PNG BLOB、PNG SHA-256 與 RGBA 像素 SHA-256。
- `image_history`：只有完全相同已驗證來源才能修復衍生圖像，修復前保存原紀錄。
- `image_attempts`：成功、修復與失敗的來源紀錄。

全批匯入使用 SQLite transaction，缺圖、重複、尺寸錯誤、解碼失敗、超限或來源在匯入期間改變，都回滾本次資料並保留可用舊快照。未知 DB schema 不降版。舊版本不會自動成為當次 Runtime；官方更新失敗時顯示無當次圖像，不以舊圖冒充。每次公開圖像讀取校驗 PNG／像素摘要及尺寸；資料損壞時拒絕顯示，下一次已驗證同步可安全重建。

## 兩端消費者與投影

`SmallMaps()` 現在只綁定當次 Runtime 的圖像 DB；未完成官方同步時能安全建立空物件。`image()` 提供 Pillow 圖像，`png_bytes()` 提供同一份已驗證 PNG；預設不開 ZIP，也不參照相同編號的其他地圖圖像。明確傳入歷史 archive 的檢視 API 保留，相容舊工具，但不作當次權威來源。

桌面沿用 Pillow／Tk 顯示，由 Runtime identity 及圖像 handle 更新觸發重新載入、清除舊圖／選取。Android MapPage 改從 `png_bytes()` 建立 Kivy CoreImage，停止呼叫 bundled texture('smallmaps.zip',...)；同場景版本更新與圖像失效都清除 texture、projection 及選取，無自動移動／封包。

投影仍採先前已核對的 UIMain 1024-pixel 公式，只從當次 ScenesData 取得 model、寬高、offset。保留 65535→6992 的既有 sentinel 規則與數值邊界。導航網格／graph origins 尚未遷移；只有既有 Coordinates 的同版尺寸比對通過才能保留原幾何導航能力，不用新圖片替舊網格授權。缺少可用導航資料不阻止純小地圖顯示，亦不解除移動限制。

## 官方實檔驗證

官方 1.3.23、MainPackage `1296_2026_11_04_13_36_07_72`，完整 catalog key `b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6`：

- 562 張 DB 圖像逐張經公開讀取後，其 RGBA SHA-256 全部與第八階段獨立官方 Texture2D 解碼結果一致。
- 1,337 個當次場景中，**799 個**有對應圖片，精確使用場景 model ID；三組像素點的 pixel→packet→pixel 誤差均小於 1e-8。
- **538 個**場景無對應官方圖片，不替換其他模型；有圖場景沒有發現未通過參數檢查者。
- 本次是來源、入庫、讀取及既有投影公式的數值驗證，未聲稱真實玩家位置／正式服移動／手機實機驗收。

完整獨立像素指紋與 DB 驗證摘要留在工作區 `validation/remaining-resources-1296/`，不把原圖或官方資料放入 Git／安裝包。

## 剩餘 13 項

`stage_coordinates.json`、`portals.json`、`graph_origins.json`、`navigation_data.zip`；`item_icon_map.json`、`item_icon_coverage.json`、`item_icons.zip`；`emoji_catalog.json`、`emoji_images.zip`；`item_stackable.json`、`alchemy_catalog.json`、`combat_catalog.json`、`normal_attack_data.json`。

它們的相依循環、幾何重建、圖集映射與 Lua 欄位語意缺口沿用第八階段逐項記錄，本階段沒有猜測或刪除。官方 UI PNG／程式圖示仍須另行分類。

## 本機測試結果

- 桌面最終完整 1,701 項，略過 165，無失敗；小地圖相關 42 項、實際 Tk 地圖 GUI 3 項通過。
- Android 完整隔離回歸 176 個測試檔退出碼皆為零，可計數 1,380 項、略過 4。Kivy logger 可能接管 stderr，計數不代表所有實際執行案例總數。
- Android 實際 Kivy MapPage 另以 stdout runner 驗證 1 項，涵蓋冷啟動、DB PNG 顯示、同場景版本更新及來源失效後清除；圖像 DB 最終 10 項重跑通過。
- 兩端實檔各自從公共讀取入口驗證全部 562 張像素及 799 個場景投影。169 個共用核心來源核對通過，桌面 repository audit 通過。
- DB 測試包含損壞衍生圖像修復與保存歷史、未完整／重複／錯誤尺寸拒絕、新來源失敗回滾、匯入期間來源變動、未知 DB schema、明確歷史 ZIP 與預設來源隔離；Runtime／UI 測試包含同 identity 圖像重新發布及預先刷新出口後仍能重載目前地圖。
- Android 通用 audit 的既有版本表示限制未改；本階段未執行遠端 CI、APK、手機或正式服驗收。
