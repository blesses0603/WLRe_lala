# 第六階段：官方地圖名稱與副本實檔核對

本機分支接續第五階段，未推送。`map_names.json` 已從種子 active／BLOB 表、來源 Manifest 與封裝必要清單移除並 VACUUM；目前仍有 **16 項**種子，不是零離線資料版本。

## 地圖名稱遷移

兩端 `map_names` 從已驗證官方 Runtime 的 `ScenesData_C`／`TextData_C` 規範 SQLite 結果產生名稱，不再讀舊 seed。來源失效時使用明確未知標籤與數字 ID，不沿用舊名稱，也不把標籤當作導航／封包授權。

同一模型可能被多個名稱不同的場景共用：只在候選名稱唯一時顯示模型名稱，否則顯示「多個場景共用模型(ID)」。不採用排序第一筆等推測。缺少文字的場景保留未知狀態。

名稱快取綁定同一個已驗證 Runtime 物件，更新時重新產生；公開 `data()` 回傳拷貝。導航 Repository 的顯示名稱改為讀取當下來源，桌面已開啟的導航視窗會依 catalog token 更新下拉選項與標籤，維持原數字 ID；失敗時清空已失效的名稱選項。現有導航幾何、投影與移動限制未放寬。

2026-11-05 以真實官方 `1.3.23`／1296 Runtime 經公共讀取入口驗證：**1,322 個有名稱的地圖、831 個唯一名稱模型、144 個名稱有歧義的共用模型**。沿用既有 Bundle 驗證及規範 SQLite；此測試以 scoped injection 提供真實 Runtime，未登入遊戲。

## 副本下一批來源已驗證，尚未移除種子

從當次官方版本與 Manifest 定位 Bundle，依既有下載工具校驗 checksum、精確 TextAsset 路徑與相依 Bundle，再用既有嚴格 parser 讀取；前後版本核心欄位一致：

| 資產 | Bytes | SHA-256 | 解析結果 |
| --- | ---: | --- | --- |
| DungeonData_C.bytes | 4876 | 9dd32361f8e0c6006f7eff4d695e7b3e8debce1753a4fcca5d10a1b565987788 | 29 筆、23 個單獨 ID、29 個 `(id, para_kind)` 組合 |
| CooperateEventData_C.bytes | 70 | 4adb067093d3961436065c1244bdf621e870ce0e320fbe4153f031ae6a37406e | 2 筆、2 個唯一 ID |

29 筆副本引用的場景及名稱均可在同批 Runtime 找到；但協力紀錄有 `npc_id=0` 的分支，不能要求每筆都直接對應事件 ID，或憑空補關聯。

舊 `instance_catalog_1262.json` 有 30 筆，消費者還包含創房參數、variant、獎勵 slot 與人數限制。下一步須：

1. 建立同批 Dungeon／Cooperate／Scenes／Text（及必要獎勵物品）的規範 adapter，明確保存複合識別碼及缺失／未知狀態。
2. 桌面可參照 optional-table 的 Bundle→SQLite 流程；Android 尚未具備同等的 optional feature 通用載入層，需共用實作與測試。
3. 更新兩端副本清單、選擇、創房前驗證與更新失敗處理，測試舊 ID 消失、同 ID 多 variant、容量／獎勵關聯、舊選擇失效；不能只替換名稱就繼續用舊創房資料。
4. 上述通過後才移除副本種子。原始檔與核對結果保存在 `/workspace/validation/current-instances/`，沒有加入安裝包。

## 尚未解決的 16 項

- `instance_catalog_1262.json`：實檔解析已證實，規範 adapter、消費者及創房回歸尚未完成。
- `stage_coordinates.json`、`portals.json`：已有部分同版表，還需全量座標／出口消費者與特殊場景驗證。
- `graph_origins.json`、`navigation_data.zip`：缺完整場景幾何重建與原點／投影驗證。
- `smallmaps.zip`：有官方資產清單，還需圖像解碼入庫、映射及投影驗證。
- `item_icon_map.json`、`item_icon_coverage.json`、`item_icons.zip`：缺同版全量圖集映射、裁切／旋轉處理與 UI 資料庫讀取。
- `emoji_catalog.json`、`emoji_images.zip`：缺可靠 Emoji 表語意與圖集對應。
- `item_stackable.json`、`alchemy_catalog.json`、`combat_catalog.json`、`normal_attack_data.json`：尚缺完整欄位語意與跨表 adapter；Lua 二進位格式仍無可靠解碼證據。
- `npc_battle_talk_1262.json.gz`：NpcTalk 群組格式與同版文字關聯未完成驗證。

官方 UI PNG 與程式圖示仍需另行分類，不計入上述 16 項。未做實機／APK、正式服或完整功能驗收；後續只保留本機提交，發布需先桌面種子提交再 Android source lock。

## 測試結果

- NPC 第五階段完成後獨立重跑 Android：172 檔、1,356 項通過，略過 4 項，無失敗。
- 本階段桌面完整回歸：1,678 項通過，略過 163；另新增的實際 Tk 導航視窗測試 1 項通過，確認名稱更新、未知狀態及數字 ID 保留。導航相關非 GUI 行為 8 項、冷啟動／GUI 3 項通過。
- 本階段 Android 完整隔離回歸：173 檔、1,359 項通過，略過 4，無失敗；166 個共用核心檔案核對通過。
- Android 通用 repository audit 的既有版本表示限制尚未修改，未宣稱該檢查通過。本階段沒有遠端 CI、APK 或手機結果。
