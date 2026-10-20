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

## 官方 1262 Eve 實際解析結果（完整資料已提交 PR）

2026-10-20 已從上傳的官方 `Eve_1262.bundle`（MD5：`81af690395d5e6a233afa9a664e2c555`）擷取 TextAsset `Eve`，依 `Data.OnLoadEventData`、`ReadSceneEvent` 及 `EventData.NewNpc` 讀取 `Ver_EveFmt=115` 的 1,256 個場景及 10,879 筆 NPC，場景偏移、資料邊界及索引唯一性檢查均無錯誤。

- 8,014 筆 NPC 的 `eventCount>0`；另 2,865 筆 `eventCount=0` 是合法的無一般事件 NPC，索引不應因而被忽略。
- 32 筆 `buyKind != 0` 僅代表商店候選，不能直接推斷這些 NPC 已能交易。
- 原始 `name` 是長度前綴的 Big5 編輯器名稱，很多筆只是 `Npc`，並非正式顯示名稱；UI 應優先用既有 NPC ID 名稱對照。
- 有部分 `eventNumber` 不等於 `mapNumber`，代表共用同一份場景事件內容，不是解析錯誤。

**完整 10,879 筆 NPC 已內建於本 PR**：`wlre/resources/npc_event_index_1262.json.gz`（gzip 無損 JSON，124,521 bytes）。LaLa 直接讀取並驗證來源 MD5、1262 版本、場景數及 NPC 數，不須使用者另行下載或手動複製。離線研究用完整 JSON／CSV／擷取腳本仍保留於獨立分析包。若壓縮資料遺失或損壞，小地圖會安全退回位置參考模式，不送出任何未核對 NPC 指令。

以下僅為可獨立使用的 `.json` 測試格式範例（非真實 NPC 紀錄）；正式內建使用對應的 `.json.gz`：

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

**上列僅為格式示例，不是真實場景資料，不能直接匯入並當成已驗證。** 裝載時檢查來源標籤、版本、整數範圍和同場景索引唯一性。來源標籤是程式的格式限制，**不能代替獨立核對的原始 EventData 來源**；已取得真實原始 Eve，但不可用自行填寫來源標籤取代實際來源核對。既有 `portals.json` 中的 `entities` 僅為位置參考，不會當成可信事件索引。

## 後續第二階段依賴

- 確認角色所在場景、NPC 真實位置／事件索引、觸發距離及可見條件。
- 建立 S20 對話文本、選項、完成／拒絕狀態；排除 S20 事件回覆被錯誤自動接續或永久上鎖。
- 已驗證這些條件後才接入普通 `C20-1`；特殊 NPC 的 `C195-3` 應另案核對，不得套用。
- 第三階段商店需要在對話正式打開商店事件後，再核對商品索引、扣款／背包同步與結果不明防重送。

## 驗收界限

本階段單元測試、UI 冒煙及跨平台 CI 可驗證清單、不傳指令與資料來源驗證，**不能宣稱 NPC 對話與商店在正式服已可使用**。本版僅開發 PR、不建立正式 Release 標籤。
