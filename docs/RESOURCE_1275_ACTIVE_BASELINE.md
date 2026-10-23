# LaLa 電腦版｜官方遊戲資料 1275 預設基準

2026-10-23 基於 `main` v0.5.17，校正之前 PR #50 僅加入唯讀預覽、主程式仍沿用 1262 的問題。

## 1275 必須是正式預設來源

- `wlre/resources/lala_supported_resources.json`：MainPackage = `1275_2026_10_21_18_29_38_49`、DataPackage = `1275_2026_10_21_18_27_33_84`，官方客戶端版本 1.3.0。
- `NPCIndex()`、`NPCInteractIndex()`、`load_catalog()`、`item_catalog()` 等無參數入口，在 1275 基準下必須使用經固定 SHA-256 與結構驗證的 1275 來源，**不會因缺檔就回退 1262**。
- 官方 1275 資源已校驗且版本識別相符後，`crafting.RECIPES` 由新版本 1,032 筆配方原地替換，使 UI 已持有的匯入引用一併更新；`open_used` 要依新版 ItemData_C 實際欄位核對。
- `Portals()` 不再讀取 1262 傳送目的地清單；1275 Eve NewDoor 已解析，但目的地與傳送條件尚未取得正式服證據，因此不送 C20-8。
- 無新版資料包、損毀或校驗不符時，登入版本閘門應保留阻擋；不會為了顯示支援新版就使用舊版 NPC 事件編號。

## 為什麼不直接將遊戲原始資源提交到公開 GitHub？

LaLa 使用由玩家本人提取的官方資料。這類二進位檔／衍生完整遊戲表格不適合當作公開原始碼直接提交，因此程式支援把來源安全安裝到使用者自己的應用資料夾，且不修改目前官方 1275 安裝內容。

使用者已取得：

- `1275_DataCatalog.zip`（原始 160 份資料表和 3 份唯讀索引）
- `1275_EveNpcIndex.zip`（1275 NPC 與互動索引）

在此 PR 的 Python 專案根目錄：

~~~powershell
py -m wlre.services.world.runtime_1275 ".\1275_DataCatalog.zip" ".\1275_EveNpcIndex.zip"
py -m wlre.services.world.runtime_1275 ".\1275_DataCatalog.zip" ".\1275_EveNpcIndex.zip" --install
~~~

第一行僅驗證；第二行才安裝到本機 `%LOCALAPPDATA%\WLRE_LaLa\official_resources_1275\`（Windows）。不會動 1275 官方遊戲安裝路徑，不會覆寫既有同名資源包，也不會刪除 1262 舊資源。

## 已確認與尚待驗收

- 1275 的官方 Manifest 與筆數、NPC Eve、商品 ID、製作配方、地圖門事件皆經離線來源檢查；新版登入版號與資料來源的切換需以 CI 完成狀態為準。
- 這次是 **1275 資料基準切換**，不代表 S20／S27／S64、正式服副本與戰鬥的完整 E2E 驗證已完成。
- **NPC 實際互動、交易、遠距換圖及製作排程** 等有副作用的操作不可從資料表解析成功推斷為協定相容；維持原先每項服務的伺服器結果防護。
- 1275 來源不齊時禁用登入，而不是改成 1262 或只看 1275 版號就放行。
