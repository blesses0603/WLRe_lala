# 副本／協力副本建置紀錄（官方 1262）

## 第 01 階段：入口（PR #22 已合併）

- 主頁左側「副本」主分頁，內有「主要」、「協力」次分頁，未確認進入指令不會送出。

## 第 02 階段：靜態表解析

官方 Lua 原始碼可核對 **格式**，不等於已取得二進位表 **內容**。目前提供嚴格解析：

- `DungeonData_C`：副本 ID、類型、難度／分組、地圖 ID、NPC、16 格獎勵與加倍／特殊旗標。
- `CooperateEventData_C`：協力種類與描述 ID、場次、標記、四個指定夥伴與額外獎勵。
- `StageData_C`：場景文字 ID、最低等級、最少／最多人數、時間限制與房間數。

來源：上傳的 `WLRE_Lua_1262_Decoded_Analysis(1).zip` 中 `Lua/Data/{DungeonData,CooperateEventData,StageData,AwardData}.lua`。透過 `wlre.services.instance_catalog.catalog(dungeon, cooperative, stage, names)` 提供已抽出的原始表位元組。對無法取得的表與文字不建立假資料，不自行推測名稱、開放狀態或獎勵。

## 後續實施準則

原版一般副本使用 C/S85；協力使用 C/S186。**封包格式核對、在測試模擬下正確收發**不等於已通過正式伺服器測試。涉及建立、加入、開始、領獎或付費操作時，必須以當前角色／隊伍／事件狀態及回覆為準，逾時不可盲目重送。
