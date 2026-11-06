# 第十四階段：剩餘九項的來源與分批遷移判定

> 最新：已完成官方 Lua 解碼，以及圖示、堆疊與煉金換源，剩餘五項種子。見 [煉金遷移](OFFICIAL_ALCHEMY_METADATA.md) 與其引用的前階段紀錄；以下是解碼前的歷史盤點。

本階段只調查官方已驗證資料、程式消費者並記錄結果，沒有修改產品資料流、移除種子或推送。仍剩九項；不是無離線資料完成版。

## 4,352 張 Sprite 的索引不能直接當成物品映射

從官方 1.3.23／MainPackage `1296_2026_11_04_13_36_07_72` 的已驗證 Manifest 逐筆盤點：

- 4,352 筆資產的 address 全都等於 PNG basename，例如 `s1000`；每筆的 GUID 空字串、tags 空陣列。
- Manifest asset 欄位只有 address、path、guid、tags、bundle_id 及解析後 bundle_name，沒有 item ID 欄位。
- 第十三階段已完成逐張 Sprite→Texture PPtr、assets_file、尺寸與像素驗證；這證實圖像來源和裁切物件，沒有建立 item ID→icon ID 語意。
- 舊 mapping 的 11,287 個 item ID 對應 5,305 個不同 icon 名稱，其中 1,197 個 icon 被多個物品共用。例如歷史 item 10000 對應 s7026，不能採 item ID 拼接檔名。
- 當次 ItemData_C 有 11,366 個 item ID；79 個新增 ID 無舊 mapping。即使重疊的舊 ID 也需要同版 icon 欄位驗證，不把舊對照表與新圖片混用後宣稱同版。

私有盤點記錄：`validation/remaining-resources-1296/item-index-semantics.json`。沒有將完整官方資產清單寫入 Git。

## 本次額外取得的真實表格

從當次已驗證 DataPackage `1296_2026_11_04_13_34_19_13` 以精確 AssetPath 取得以下 TextAsset。完整計畫為三個 Bundle，已存在可用校驗快取，新增下載 0 bytes；仍驗證 Bundle 與前後官方版本。原始資料保存於工作區，不加入安裝包。

| 表格 | Bytes | SHA-256 |
| --- | ---: | --- |
| ItemloadData_C | 260 | ed8e8b69674d197e2c7159d3b6f5f1dd4f8ca2919dcafe5110c5bf24b6d5f1e4 |
| ItemData_SC_C | 3,202,050 | 1ca6386dfe9d370ae46ef1d5a9cad5fdb7959ffcb1838473934e7fbfdfe49647 |
| AlchemyTalkData_C | 10,628 | 1217944647ba94bb717c4cce677c7913b68ad9822a4b4cb9b4f3d6cd5d370846 |
| SkillData_C | 199,629 | ed6383251b4f0fb9f7d9eb85c99346a268b99bdded839f6957f083c4b7f0545c |
| SkillMotionData | 1,530,594 | b604ba3bc837cbf6f3ce1dd43f193a71653f3a6b4b926e50a9b8e1fb083060b2 |

這五份標記為 `not_interpreted`，不從檔名猜測 ItemloadData 是映射、SC 是可互換語言版本、AlchemyTalk 是材料分類，也不把 binary prefix 當已確認筆數。對應證據為 `remaining-tables-audit.json`，原始 bytes 同目錄。先前 ItemData.lua／SkillData.lua／SkillMotionData.lua 等六份官方 Lua 仍為未識別封裝，MD5 驗證僅證明來源，不能證明欄位解碼。

## 消費者與安全分批界線

| 剩餘項目 | 實際依賴與目前不能安全替換的原因 |
| --- | --- |
| item_icon_map.json | 桌面 ItemIcons、crafting_browser 的 ICON_MAP；Android assets 的 item mapping。缺同版 iconId／尺寸／fallback 語意；只搬已知 Sprite 不能解決 mapping，先搬重疊 ID 也缺同版等價證據。 |
| item_icons.zip | 桌面跨視窗 Pillow cache／window-local Tk cache；Android bounded textures。可建立下一階段通用 Sprite DB，但消費者要切換仍依賴上列同版映射，不能用仍未知的映射宣稱完成遷移。 |
| item_stackable.json | inventory_updates.add_item 決定併格、空格與 200 上限，優先使用伺服器明示 server_stackable；未知物品只接受明確空格的一件物品，其餘要求重新同步。直接刪除舊表會減少現有可處理增量，不視為完成。需同版 CanOverlap 及新增物品測試向量。 |
| alchemy_catalog.json | material_problem/category 讀 spares[0]，另依 CAT 的 kind、special、restrict 決定是否可自動消耗與材料分類。只遷移名稱／價格不能替代這些欄位；缺失會關閉現有功能。 |
| combat_catalog.json | items/catalog.CAT 為多個戰鬥與物品功能提供技能、角色、物品及元素資料；需要完整跨表 adapter，SkillData／SkillMotion 存在不等於欄位已證實。 |
| normal_attack_data.json | battle/combat 用武器類型、NPC NormalAttackKind、身體類型和捕捉網參數選擇技能；不可用現有已驗證的價格／名稱欄位代替。 |
| stage_coordinates.json | Coordinates.mapping 比對當次 scene 的 model、寬高、offset，卻仍需舊導航的 offset_y；obstacle_scope 也用舊場景集合決定屋內障礙作用範圍。只換 scene ID 集合不能證明新版 FurSysSceneNum 或舊 geometry 相容。 |
| graph_origins.json | Coordinates 的 packet XY↔Int3 XZ 轉換，與 geometry bounds、vertex、offset_y 成組；沒有可獨立移除的來源。 |
| navigation_data.zip | Mesh/Repository 的已解碼導航幾何；同版 Scene 樣本仍需 88 Bundle／830,825,656 bytes，超出現有額度且無可靠同版 geometry decoder。維持額度，不跳過依賴。 |

可操作的下一步：取得同版可讀 `Lua/Data/ItemData.lua` 或等價且可獨立核對的官方表格欄位說明／測試向量，先確定 iconId、sizeL/sizeW、CanOverlap 與 spares，再對 11,366 筆全量驗證。已有的 Sprite 圖像及精確引用證據可直接供後續 DB 匯入驗收使用。若提供封裝解碼器，必須能對這一版實檔產生可驗證結果，不能套用其他遊戲格式或猜金鑰。

本階段沒有足夠證據再安全移除其中任何一項，因此全部保留。沒有重跑未改動的產品測試；前一階段 Android 完整 180 檔成功及後續兩端 39 項相關測試結果仍成立。本階段檢查文件／工作區一致性，未執行遠端 CI、APK、手機或正式服驗收。
