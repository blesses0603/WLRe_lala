# LaLa 電腦版｜1275 資料接入第一批（離線／唯讀）

此項目以 main v0.5.17 與遊戲資料基準 1262 為起點。**1275 新資料已能經 GitHub 程式碼被實際讀取、查詢與用於商店價格預覽；不是完整 1275 登入或交易相容性認證。**

## 檔案位置

- `wlre/services/world/preview_1275.py`：需要雙來源驗證的 1275 資料讀取器；提供 NPC、選單、商店預覽、物品、配方與場景判定。
- `wlre/services/world/doors_1275.py`：從經 SHA-256 驗證的 1275 Eve 原始 TextAsset 解碼 NewDoor。1275 **1,262 個 Eve 場景中的 3,521 個門事件**可查詢來源 index、座標與事件列表。
- `wlre/services/world/npc_shop.py`：新增可選 `item_rows` 注入點，原預設 1262 內建資料行為不變，1275 可從已驗證的 `Preview1275` 提供物品資料。商店 `buy_enabled` / `verified_prices` 仍停用。
- `tools/resources/preview_1275.py`：不連接遊戲伺服器的離線指令介面。
- `tests/test_preview_1275.py` / `tests/test_doors_1275.py`：驗證壞資料拒絕、舊版預設行為、配方欄位、唯讀限制。

## 使用方式

需取得使用者先前提取出的兩份 ZIP：

1. `WLRE_LaLa_1275_全資源差異與校驗包.zip`（160 份 DataPackage TextAsset，3 份資料索引及其固定雜湊）。
2. `WLRE_1275_Eve_NPC_索引包.zip`（1275 Eve NPC 與互動選單兩份固定 SHA-256 索引）。

從本 PR 的原始碼根目錄（需能執行 Python 3.10+）：

~~~powershell
py -m tools.resources.preview_1275 ".\WLRE_LaLa_1275_全資源差異與校驗包.zip" ".\WLRE_1275_Eve_NPC_索引包.zip" --scene 10000
py -m tools.resources.preview_1275 ".\WLRE_LaLa_1275_全資源差異與校驗包.zip" ".\WLRE_1275_Eve_NPC_索引包.zip" --item 39852 --recipe 39852
py -m tools.resources.preview_1275 ".\WLRE_LaLa_1275_全資源差異與校驗包.zip" ".\WLRE_1275_Eve_NPC_索引包.zip" --portal 10000 --door-index 1
~~~

商店查詢使用 `--shop 地圖ID:事件索引`；請從新版 Eve 索引選擇實際 `form_kind=2/3` 的記錄，不猜測商店 ID。

程式會先校驗兩個 ZIP，拒絕改動過的內容、未知版型與不完整封裝，再建立新版資料視圖。場景顯示與門事件存在性可以證明原始檔來源，但**不能推定傳送目的地、任務門檻、角色權限或正式服封包效果**。

## 資料更新與不更新的邊界

| 功能 | 已接入的 1275 來源 | 未開放的功能 |
|---|---|---|
| NPC | EventData.NewNpc，10,975 筆 | 1275 C20 實際對話觸發 |
| NPC 選項／商店 | EventData.NewInteract，1,634 組；ItemData_C 11,304 筆 | C20 選項發送、C27 實際買賣 |
| 物品 | 1275 ItemData_C 唯讀名稱、基礎價格、限售欄位 | 伺服器持有量／真實折扣推定 |
| 製作 | 1275 SmithData_C 1,032 筆，沿用 LaLa 配方欄位 | C64 製作排程與製作材料消耗 |
| 地圖傳送 | ScenesData_C 1,337 筆、Eve NewDoor 3,521 筆 | C20-8 觸碰、跨圖目的地及路線自動替換 |

副本、協力、遠征核心原始表的 SHA-256 已確認跨版完全相同，現階段不重複替換。每日任務非目前 main 的獨立功能。

## 為何目前不能解除版本封鎖？

`wlre/resources/lala_supported_resources.json` 仍標記 DataPackage/MainPackage 1262。這是 LaLa 對可登入正式服的**已測試協定基準**。讀到新版圖資與表格並不能證明 C20、C27、C64、傳送、戰鬥等封包協定在 1275 伺服器上通過 E2E。

下一階段須實際核對新版事件與目的地映射、NPC 選項/商店伺服器回覆、製作排程及異動物品規則，再執行 Windows 1275 客戶端正式服驗收，才能逐項打開版本支援。

## 回歸入口

~~~powershell
py -m unittest discover -s tests -p "test_preview_1275.py" -v
py -m unittest discover -s tests -p "test_doors_1275.py" -v
py -m unittest discover -s tests -q
py WLRE_Client.py --self-test
~~~

沒有實際執行過的原生編譯、正式服登入、交易或傳點不能標示成功。