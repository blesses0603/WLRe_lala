# 小屋儲藏空間：1262 Lua 存取與製作整合

## 來源與功能

來源：上傳的 WLRE_Lua_1262_Decoded_Analysis，特別是 Lua/UI/Logic/UIRoomStorage.lua、Lua/Logic/RoomStorage.lua、Lua/Logic/Room.lua、Lua/Logic/Protocols/Protocols_062.lua、Lua/Logic/Protocols/Protocols_064.lua、Lua/Data/ItemData.lua。

本次使用者提供的 ZIP SHA-256：`3e53db47ea22294207bfbc230322dbcc0429e4a4c94c7f67aacc924e18d77fce`。UIRoomStorage.lua：`727aee9ba64876d14e13431f7d77bab4a77581450d78742d0c40b43cd4947f88`；Room.lua：`d9bde0076eb5b75f9acc26ee312fae87d08d30d0d3100dfa0425e388fd6ab738`。

超空間袋是原版 UI 進入小屋儲藏室的入口：Game_Const.Mark_CarryOnBank 為 1291，解鎖道具 ID 為 34977。使用後可能不再持有道具，因此不能僅憑背包持有數量判斷是否已解鎖。

## S62-7 初始儲藏室物品

- 第一欄 u8 count，代表本次收到的物品筆數。
- 每筆：u8 index（儲藏室格位），接著 64-byte ItemSaveData。
- Lua：RoomStorage.RevIniGarageItem → ItemSaveData:New(index, packet, false)。
- 64-byte ItemSaveData 欄位位移（相對物品起點）：
  - 0: u16 itemId，2: u8 count，3: u8 damage，4: u8 serialVer，5: u32 serialNo
  - 9: u32 durable，13: u32 firing，17: u16 magicSparId
  - 19: f64 availableTime，27: f64 limitedTime
  - 35: u8 beatLevel，36: u8 differ，37: u16 modeling，39: u16 getItemId
  - 41: u8 saddleBeatLevel，42: u16 enhanceLevel，44: u32 designId
  - 48: 四組 (u8 kind, u16 value) 插件，共 12 bytes
  - 60: u8 lock flags，61: u8 starSoulKind，62: u8 starSoulLevel，63: u8 showMessage

本地以合成物品記錄確認 LaLa 既有 item_save 可完整讀取 64 bytes。

## 其他已解析的伺服器封包

| 封包 | 資料結構 | 用途 |
| --- | --- | --- |
| 62-11 | u8 index + 64-byte ItemSaveData | 儲藏室新增物品 |
| 62-13 | u8 index + u8 reduceCount | 儲藏室刪除物品 |
| 62-57 kind=1 | u8 kind + u8 sendKind；sendKind=1 時另有 u16 count，接續每筆 [u16 index, u16 itemId, u16 count] | 雜物櫃初始或新增物品 |
| 62-57 kind=2 | u8 kind + u16 index + u16 count | 雜物櫃刪除物品 |
| 62-71 | u8 result | 存入成功 1／取出成功 2 |
| 62-72 | u8 garageSpace + u16 materialSpace + u16 stackLimit | 兩種儲存空間容量 |
| 62-73 | u8 value | 儲藏室容量更新 |
| 62-74 | u16 value | 雜物櫃容量更新 |
| 62-75 | u16 value | 雜物櫃堆疊上限更新 |
| 62-25 kind=1 | u8 kind + u8 errorCode | 儲藏操作錯誤 |

注意：相同的 sub 編號可能在不同封包方向有不同意義，例如 C→S 62-74 是擴充儲藏室請求，而 S→C 62-74 是雜物櫃容量更新，不能混淆。

## C→S 存取請求

`UIRoomStorage.SendSaveItem`、`SendWithdrawItemFromStorage` 定義：

| 動作 | 封包 | 負載 |
| --- | --- | --- |
| 背包存入儲藏室 | C62-18 | u8 rows + [u8 bagIndex, u8 count] |
| 儲藏室取出到背包 | C62-19 | u8 rows + [u8 garageIndex, u8 count] |
| 背包存入雜物櫃 | C62-52 | u8 1 + u8 rows + [u8 bagIndex, u8 count] |
| 雜物櫃取出到背包 | C62-52 | u8 2 + u8 rows + [u16 cupboardIndex, u8 count] |

雜物櫃單格數量可超過 255；取出時按 Lua 分成每筆最多 200 個、同一索引可重複，單次最多 255 筆。操作前驗證完整同步、格位身分、數量、保留登記、容量與堆疊上限。雜物櫃只接受已確認可堆疊物品；本次不搬動鎖定、限時及帶額外屬性的材料。S62 雜物櫃資料可證明同一會話中新物品 ID 可堆疊，供後續背包增量解析；不修改全域靜態資料。

`RoomStorageTransfer` 等待對應 S62-71 成功回覆、來源扣除和目的庫存增加三項齊全，允許任意到達順序。其間以共用 reservations 保留來源格位，並與製作、煉金、補給、遠征等消耗操作互斥。逾時、斷線或部分移動後出錯均保留結果不明狀態，禁止自動重送，重新登入重建同步。

## 製作直接取用雜物櫃

`Room.CheckSmithMaterial` 與 `Room.SmithProduct` 定義先背包、再雜物櫃的材料分配。C64-1 背包材料列後接 `u16 cupboardRows + [u16 index, u16 count] + u8 furnitureRows`。目前 `furnitureRows=0`，不消耗已擺家具；現行 recipe ID 格式與舊 product ID 格式共用此雜物櫃尾段。

製作依各容器獨立格號保留材料，扣除已被其他流程保留的數量；送出後等待排程確認、背包及雜物櫃扣料全部完成。兩容器相同格號不會混用；任一保留失敗會回復整批。材料不足且雜物櫃尚未完整同步時不推算可用庫存。

## LaLa 整合與驗證

- `wlre/services/items/room_storage.py` 解碼並合併 S62 權威狀態；`room_storage_transfer.py` 負責存取請求、保留與確認。
- 超空間袋頁提供儲藏室／雜物櫃取出，實際包包頁提供兩種存入；選物後在原視窗底部的內嵌面板輸入數量並確認，不建立系統模態視窗或鎖住滑鼠／鍵盤。支援 Enter 確認、Escape 取消及「最多」；確認時重讀最新快照與版本，來源格位身分變更則拒絕操作。
- 儲藏室與雜物櫃固定每頁 6 欄 × 4 列，共 24 格，依空間縮放圖示並保留選取位置；一般背包維持響應式格位。
- 製作材料表分列背包／雜物櫃／需求，隨 `room_storage.revision` 更新；加入排程確認顯示兩處各自消耗數量。
- 未收到初始同步時不顯示不完整增量資料，不以背包內容代替儲藏庫存。未加入付費擴充與主動查詢。
- `tests/test_room_storage_transfer.py` 驗證四種請求、分段取出、回覆順序、容量、互斥、逾時、斷線與真實 UI 操作入口。`tests/test_storage_transfer_form.py` 另以實際主題與視窗測試鍵盤輸入、滑鼠確認、取消、焦點、重複點擊與內嵌面板下的 6×4 格位。
- `tests/test_crafting_cupboard_execution.py` 驗證兩版製作格式、混合／純雜物櫃取料、多格與大數量、保留回復及扣料確認；既有儲藏解碼、製作與 GUI 測試保留。

協定來源與合成封包回歸已核對；正式伺服器的存取、製作及不同場景操作條件仍需實際連線驗收。
