# 官方物品圖示資料庫遷移

此階段承接 [官方 Lua 解碼證據](OFFICIAL_CLIENT_LUA_DECODING.md)，將物品圖示映射與圖像改為官方同步後的 SQLite 快照。兩端不再載入 `item_icon_map.json` 或 `item_icons.zip`，種子由九項降為七項，大小由 68,395,008 降為 17,825,792 bytes。

## 來源與匯入

- 當次版本：Data 1.3.23，DataPackage `1296_2026_11_04_13_34_19_13`、MainPackage `1296_2026_11_04_13_36_07_72`。版本配對 key 為 `b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6`。
- 官方 ItemData 11,366 筆的 iconId 與 `s%04d` 規則建立映射，使用已驗證 Lua 指定的 s1000 作缺圖 fallback；1,432 筆使用 fallback，先前 79 筆新增物品全部有原圖。
- MainPackage 精確資源路徑 `Assets/ResourcesBuild/Sprite/Sprite_Item/sNNNN.png` 共 4,352 張，當次計畫一個 25,402,412-byte Bundle。使用獨立上限 32 MiB／4 Bundle，不放寬導航下載額度。
- 每個路徑必須有且只有一個 Sprite、一個 Texture2D，Sprite 必須精確引用同一 assets file 中該 Texture 的 path ID；限制尺寸 512×512。拒絕歧義、缺少、重複及未知路徑。兩端實檔每張 RGBA SHA256 均與先前獨立 Sprite 驗證結果一致。
- `official_item_images.sqlite3` 保留版本配對、Bundle SHA256、完整官方路徑、物品映射、背包佔格欄位、PNG 與像素 SHA256。原始官方 Bundle 仍保留。BEGIN IMMEDIATE 交易在整批與來源重驗成功後才發布；新版本失敗不覆蓋舊版，損壞衍生圖像可從同版已驗證 Bundle 重建並保留歷史。
- 可信映射來自相同 Runtime 的 SHA 鎖定 ItemData；不從殘留使用者種子或其他版本補映射。新 Runtime 無圖時明確回報 item_image_status，保留先前資料庫，但不混用版本。

## 桌面與 Android

桌面保留跨視窗、有額度的 Pillow 像素快取與各視窗獨立 Tk PhotoImage。來源切換會更新已顯示的影像，冷啟動或資料不可用時顯示空白；關窗取消計時器，所有原 ZIP 關閉呼叫已改為關閉圖像消費者。相容 ICON_MAP 介面即時讀取目前官方映射，製作詳情以官方明確定義的 itemW/itemH 顯示「背包佔格」，不猜測器具幾何尺寸。

Android 只在 UI thread 建立有數量上限的 texture，分批讀取目前顯示物品，來源切換會清除舊快取並更新既有 widget；未同步時不借用舊種子。背包頁顯示官方圖示同步狀態，來源版本納入刷新鍵，避免舊圖與重複重繪。兩端皆無網路／資料庫時仍能開啟畫面，圖示為空，不影響原有封包安全閘門。

## 範圍及後續

剩餘七項：`stage_coordinates.json`、`graph_origins.json`、`navigation_data.zip`、`item_stackable.json`、`alchemy_catalog.json`、`combat_catalog.json`、`normal_attack_data.json`。不能宣稱零離線資料已完成。

堆疊規則已追到官方 `ItemData.CanOverlap` 與相依函式；另取得同版 Define.lua、Attribute.lua，經官方 MD5、相同已確認 codec、重新加密與 SHA256 留證。接著需核對 EUseItemKind／EAttribute、屬性資料與賽季 flag，完整涵蓋特殊物品、裝備、交通工具、限時、補瓶及紋章條件，才可替換堆疊種子。禁止把 fitType 或 useCount 單一欄位當作完整規則。這些 Lua 原文與金鑰不隨程式發佈。

原始／衍生實檔與種子移除前備份均在工作區 validation 中，沒有推送、合併或 Release。測試在 Linux Xvfb／Kivy 執行，不代表 Windows、macOS、手機或正式服驗收。

## 最終驗證

桌面完整 1,730 項成功（略過 3）；Android 183 檔全部成功，報告 1,408 項（略過 4）。涵蓋完整／部分匯入、來源變更、損壞衍生資料修復及歷史、未知 schema、冷啟動、缺圖 fallback、現有 Tk／Kivy 圖像隨版本更新及視窗生命週期。兩端實檔均驗證 11,366 筆映射、4,352 張逐像素 SHA、1,432 筆官方預設圖示；當次版本無缺少新增 79 筆的圖示。日誌在 /tmp/phase16-desktop-final.log、/tmp/phase16-android-final.log 及兩端 real.log；repository audit 與共用核心來源核對另行通過。未執行遠端 CI。

後續研究亦已取得並驗證 Function.lua，確定 CheckFlag 的實作；相關三份新增 Lua 均留在私人驗證目錄，不放入發佈內容。
