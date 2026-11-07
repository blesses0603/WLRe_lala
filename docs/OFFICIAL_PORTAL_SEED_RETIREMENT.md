# 第十階段：移除已退役的傳點種子

本階段只在本機，未推送、合併或建立 Release。種子由 13 項減為 12 項，並非零離線資料版本。

## 完成內容

逐一搜尋兩端 `portals.json` 讀取位置，確認預設 `Portals()` 已由當次官方 Runtime 建立清單，1262 與冷啟動分支皆不讀舊種子。NPC／怪物 sidebar 的正常資料已於第五階段改用當次 NPC Runtime；保留的舊物件測試只是歷史相容性，不需要隨附原始 JSON。特殊出口的座標、事件、目的地及封包授權仍沿用原驗證，未擴張可操作範圍。

兩端已刪除種子 active 與 BLOB 表中的 `portals.json`、VACUUM，移除來源及必要打包清單項目，並加入 retired 清單，禁止打包殘留同名檔案。種子從 71,331,840 bytes 降至 68,841,472 bytes。既有使用者 DB 的歷史內容不刪除，預設入口不會讀它。

取消 `Portals('')` 隱性載入 bundled database 的舊分支；明確傳入有效歷史 JSON 路徑仍可讀取。預設來源失敗時回傳空清單及 `core_runtime_unavailable`，不拿舊清單補上。

現有 Bundle 校驗、來源一致性、規範 SQLite snapshot／失敗回滾流程沿用。這次移除已不再需要的舊資料，未新增或推測傳點二進位格式。

## 驗證

- 桌面傳點、種子、來源安全及規範 DB 相關測試：173 項通過，略過 7。
- Android 同範圍：91 項通過，無略過。新增兩端共用三項測試涵蓋冷啟動不讀歷史 DB、明確歷史檔案相容、空路徑不回退。
- 桌面 repository audit 通過。本次修改範圍小，沒有重跑全套；上一階段完整回歸結果見小地圖文件。
- 官方 Data 1.3.23、當次 catalog key `b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6`：兩端公共 `Portals()` 入口均從已驗證 Runtime 產生 1,262 個場景、3,741 個傳點標記；metadata status 為 `destination_links_loaded`。既有規則判定 2,922 筆 direct eligible，這只是原程式的資料驗證結果，不代表正式服觸發驗收。
- 實檔檢查將 `load_bundled_json` 設成一旦呼叫即失敗，未觸發。使用已驗證官方 Bundle 快取，仍查核前後官方版本，未登入遊戲或送封包。沒有遠端 CI、APK、手機或正式服測試。

## 剩餘 12 項與下一步

以下是現有實檔與消費者證據的盤點，不把候選來源視為已完成解析。沒有因缺少證據刪除功能。

| 項目 | 已知來源／未完成工作 |
| --- | --- |
| stage_coordinates.json | 當次 ScenesData 已解析；Coordinates 仍需歷史 geometry 相容檢查與 offset_y。需與同版導航幾何一同驗證，不能直接替換以放行舊網格。 |
| graph_origins.json | 需同版 Scene/NavMesh bounds、vertex 與 packet↔Int3 全量轉換證據。 |
| navigation_data.zip | Main 有 775 個 Scene；M10001 相依計畫遇到 model_10_npc ↔ model_10_npc_static 循環，需先確認 YooAsset 2.2.10（Manifest 2.2.5）原始碼語意，再解碼／驗證幾何與路由。 |
| item_icon_map.json | 已確認 Sprite_Item/s1000.png 存在；缺同版 Item ID→sprite 全量欄位證據，不能按檔名猜。 |
| item_icon_coverage.json | 應由成功匯入的當次 mapping／images 重算，不能沿用舊 coverage。 |
| item_icons.zip | 需完整相依計畫、Sprite 裁切／旋轉／圖集映射及兩端圖像消費者遷移；第九階段圖像 DB 可參考，但不能直接假設與小地圖同格式。 |
| emoji_catalog.json | 已取得校驗的 500-byte EmojiData_C；尚缺完整 token 行序、icon ID、mark／show 條件證據。 |
| emoji_images.zip | 已確認 SpriteAtlas_Emoji；atlas ↔ sprite_bricktreasure 循環被現有 planner 拒絕。先核對相依語意，再做 atlas 解碼，不跳過相依或改用 SC 圖集。 |
| item_stackable.json | 現有 Item parser 未提供經核對的 CanOverlap；需要同版欄位及完整測試向量。 |
| alchemy_catalog.json | 缺 spares／材料分類／kind／special／restrict 的同版語意與跨表驗證，AlchemyTalk 不能代替。 |
| combat_catalog.json | Skill／SkillMotion／Npc／Item 原表存在，但技能、角色、元素權重等 adapter 不完整。 |
| normal_attack_data.json | 武器、NPC、捕捉網欄位與公式仍需獨立證據和測試向量，不能猜偏移。 |

可先推進 YooAsset 對應版本原始碼調查，確認相依欄位是資產閉包還是 Bundle 邊；用實際 Manifest 案例驗證後再修改 planner。這是尚未完成的工程調查，不是認證阻擋或官方沒有提供資產。六份已驗證 Lua 仍缺可靠同版封裝解碼證據，保留原檔，不套用其他遊戲解碼器。官方 UI PNG／應用圖示仍需另列分類，不在 12 項計數內。
