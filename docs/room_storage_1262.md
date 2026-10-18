# 1262 小屋儲藏空間：已確認的 S62 封包

## 來源與功能

來源：上傳的 WLRE_Lua_1262_Decoded_Analysis，特別是 Lua/Logic/RoomStorage.lua、Lua/Logic/Protocols/Protocols_062.lua、Lua/Data/ItemData.lua、Lua/UI/Logic/UIBag.lua。

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

## LaLa 整合範圍

- wlre/services/items/room_storage.py：嚴格的封包解碼與狀態合併。
- wlre/network/protocol.py：接收轉發 S62。
- wlre/core/state.py：儲藏室與雜物櫃獨立保存，不混用普通背包索引。
- wlre/ui/resource_view.py：超空間袋分頁的儲藏室、雜物櫃唯讀格子。
- wlre/ui/bag_grid.py：可作為唯讀儲藏室圖示檢視。
- tests/test_room_storage_1262.py：11 項合成封包測試。

## 仍待確認

解碼已按 1262 Lua 實作；尚未以實際 S62-7 / S62-57 封包在正式連線中端對端驗證。

目前不主動請求儲藏室資料，也不發送存取／擴充指令。沒有收到初始同步封包時保持等待狀態，絕不拿普通背包資料冒充儲藏室內容。
