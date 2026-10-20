# NPC 系統第一階段：場景清單與事件索引（v0.5.7）

## 官方 1262 依據

- `Lua/Data/EventData.lua` 的 `EventData:NewNpc`：`index:UInt16` 是場景 NPC 容器索引，另有 `id:UInt32`、`x/y:UInt32`、`eventCount:UInt8` 等獨立欄位。**圖鑑 NPC ID 不等於索引**。
- `Lua/Logic/EventManager.lua` `SendNpcEvent`：普通 NPC 點擊使用 `C20-1`，本文是 `index:UInt16`。
- `Lua/Controller/NPCController.lua` `OnInteractive`：檢查有事件及互動條件後才向伺服器請求，並可能先向 NPC 靠近。
- `Lua/Data/MapActionNpcData.lua` 及 `Lua/Logic/ExtraEventMgr.lua`：**特殊 NPC 使用 `C195-3`，不應將其 index 填入 C20-1**。
- `Lua/Logic/Protocols/Protocols_020.lua`：`S20-1~6` 為事件效果，`S20-8` 才是事件結束。本機尚未完整支援事件/選項解碼，不能只送 `C20-1` 就假設交談完成。

## 本版功能

- 小地圖清單拆分為「傳點」「NPC」「怪物」；保留既有傳點按鈕與雙擊觸發方式。
- NPC 列出場景參考名稱及可用座標，點選即標示地圖位置，不自動行走、換圖或觸發事件。
- 位置參考與已核對的事件 NPC 以不同標示顯示；來源未核對時不推測 `npc_index`。
- 仍保留怪物清單與小地圖原始縮放/角色位置/路徑繪製。

## 可信索引資料（尚未預裝）

若日後取得可獨立核對的 **1262 EventData NPC 清單**，可在 `wlre/resources/npc_event_index_1262.json` 放入唯讀資料，例如：

```json
{
  "version": 1262,
  "source": "EventData.NewNpc",
  "scenes": {
    "100": [
      {"index": 5, "npc_id": 321, "x": 24, "y": 25,
       "event_count": 2, "name": "範例 NPC"}
    ]
  }
}
```

**上列僅為格式示例，不是真實場景資料，不能直接匯入並當成已驗證。** 裝載時檢查來源標籤、版本、整數範圍和同場景索引唯一性。來源標籤是程式的格式限制，**不能代替獨立核對的原始 EventData 來源**；尚無官方原始資料前，請勿自行填入假索引。既有 `portals.json` 中的 `entities` 僅為位置參考，不會當成可信事件索引。

## 後續第二階段依賴

- 確認角色所在場景、NPC 真實位置／事件索引、觸發距離及可見條件。
- 建立 S20 對話文本、選項、完成／拒絕狀態；排除 S20 事件回覆被錯誤自動接續或永久上鎖。
- 已驗證這些條件後才接入普通 `C20-1`；特殊 NPC 的 `C195-3` 應另案核對，不得套用。
- 第三階段商店需要在對話正式打開商店事件後，再核對商品索引、扣款／背包同步與結果不明防重送。

## 驗收界限

本階段單元測試、UI 冒煙及跨平台 CI 可驗證清單、不傳指令與資料來源驗證，**不能宣稱 NPC 對話與商店在正式服已可使用**。本版僅開發 PR、不建立正式 Release 標籤。
