# 官方 1275 小地圖缺口核對（PR #57）

2026-10-26 使用 `output_1275.zip`（官方 1275 的 `ScenesData_C`、圖片及對應清單）與
LaLa 既有 `smallmaps.zip`／`stage_coordinates.json` 唯讀交叉核對。

## 已確認的缺口

| 項目 | 結果 | 修正方式 |
| --- | --- | --- |
| `SmallMap2D` 圖片數 | 舊檔 550／1275 官方 550；名稱差異 0 | 不新增重複圖片 |
| 圖片內容 | 550 張 WebP／PNG 解碼為 RGBA 後逐張像素一致 | 可沿用現有圖片位元資料 |
| 場景總數 | 1275 為 1,337；舊表為 1,836 | 依新版正式 Runtime 分開處理 |
| 1275 新增而舊表缺少 | `15138`（噴氣孔洞穴一） | `ScenesData_C` 的 `model_id=11139` 動態指向現有圖片 |
| 尺寸或偏移差異 | 12 個場景（`13216`–`13227`） | 改由已驗證 1275 場景表提供參數 |
| 12 個變動場景的圖片 | 官方 1275 和 LaLa 都未提供對應 `SmallMap2D` 圖片 | 不套錯圖、不開啟點擊導航 |
| 僅在舊表的場景 | 500 個 | 舊版資料仍保留，不誤當成 1275 場景 |

12 個有變更但沒有原始小地圖圖片的場景包含鬥獸場通道、狩獵場、地牢與地洞迷宮。
其原始欄位舊值常為 `65535`／偏移 0；官方 1275 有正式尺寸及偏移，但**有尺寸不代表有可顯示的圖片**。

另外，`SmallMap2D_12050` 雖然存在，但官方場景 `12050`（威靈村）的
`model_id` 實際是 `15129`。`SmallMap2D_12050` 不能當作場景 ID 相同就直接套用；
本次也新增這個容易誤配的回歸測試。

## LaLa 採用方式

- `parse_stages` 不再丟棄官方 `model_id`；正式 1275 Runtime 同時提供完整場景尺寸與偏移。
- `SmallMaps` 在 1275 基準時以已校驗 Runtime 的 `scene_id → model_id` 查圖、以
  `map_width/map_height/small_offset_x/small_offset_y` 投影，不使用舊 `stage_coordinates.json`
  猜場景或把 1262 來源當新版權威座標。
- 1275 圖片即使與舊版像素完全相同，也**不等於舊版導航網格已通過 1275 協定驗收**。
  舊路徑的顯示／小地圖雙擊移動保持停用；傳點仍按既有獨立交叉核對及伺服器回覆處理。
- `output_1275.zip` 是本次**對照樣本**，不是要匯入 LaLa 的新資產包；
  不增加 UI 匯入按鈕，不上傳官方圖片到公共 GitHub。

## 重新檢查

```powershell
py -m tools.audit_minimap_1275 "C:\路徑\output_1275.zip"
py -m tools.audit_minimap_1275 "C:\路徑\output_1275.zip" --pixel-audit
```

工具只產生報告、不變更程式或遊戲檔案。實機畫面、官方傳點事件、伺服器換圖與
新版導航圖仍須分別驗收。1275 圖像／場景一致，不構成自動換圖封包的額外授權。


## 1275 傳送點座標／目的地補齊（PR #57 後續）

使用者提供的 `output_1275.zip` 另含官方 `EveDoorLinks.bytes`、
`StageMapData_C.bytes`、`ScenesData_C.bytes`，重新逐筆解析：

| 檢查 | 1275 對照數量 |
| --- | ---: |
| EveDoorLinks 原始連線 | 2,374 |
| 原場景 XY 有場景倍率可換算 | 2,366 |
| 目的地落點 XY 有場景倍率可換算 | 2,367 |
| 缺少同索引 Kind 2 標記的連線 | 525 |
| 重複同索引 Kind 2 標記 | 3 |
| 目的地不在 ScenesData_C | 7 |
| 來源場景不在 ScenesData_C | 8 |

以前 LaLa 的 `verified_portal_destinations()` 只接受
`Eve.NewDoor + StageMapData_C + EveDoorLinks` 三表同場景同索引，
因此缺標記的連線即使官方有寫出原座標及目的地，也無法作為唯讀資訊。

現在另外建立 **`portal_evidence_1275.read_only_portal_evidence()`**：

1. 保留每筆 EveDoorLinks 的 **(scene, one-based link ordinal)**、來源網格 XY、
   原場景換算後 XY、目的場景 ID、目的地落點網格 XY、目的場景換算後 XY。
2. 缺 StageMap 記錄、缺 Eve.NewDoor 事件、倍率不足、未知場景等均保留
   明確原因；**不猜測座標，不拿 1262 結果補 1275**。
3. LaLa 可唯讀顯示有正式場景幾何的連線；沒有對應 Eve.NewDoor 的
   連線會標記為 `1275-ref`，**不得呼叫 C20-8**。
4. 正式可試傳條件仍完全依舊有嚴格的 `verified_portal_destinations()`
   及 `verified_portal_positions()`，不因新增唯讀資料提升權限。

官方 1275 Manifest 另外包含 `DoorLinkData_C`，但上述
`output_1275.zip` **未提供該表實際 TextAsset**，不能聲稱已解析其真實筆數。
已新增按官方同版 Manifest / Bundle hash 取得的可選解碼流程；
其 12-byte 紀錄是場景路線，不包含可直接發送的門事件索引。
核心 Runtime 不會因其缺失而失效。

使用者來源 ZIP 的對照統計，不能取代正式 Bundle hash 重新驗證。
本次修復沒有上傳正式遊戲圖片、官方二進位原始資產，也不修改原始遊戲。
門事件傳送及伺服器回覆仍須實機端到端驗收。
