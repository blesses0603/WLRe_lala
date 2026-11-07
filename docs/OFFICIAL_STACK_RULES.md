# 官方物品堆疊規則遷移

承接 [官方 Lua 解碼](OFFICIAL_CLIENT_LUA_DECODING.md) 與 [圖示資料庫](OFFICIAL_ITEM_IMAGE_DATABASE.md)。已移除兩端 item_stackable.json 種子；背包增量、遠征獎勵容量與儲藏判斷改由目前已啟用 Runtime 的正規化 ItemData 欄位讀取。剩餘六項種子：stage_coordinates、graph_origins、navigation_data、alchemy_catalog、combat_catalog、normal_attack_data。

## 規則來源與版本

官方 1.3.23 LuaScriptPathList 明示的 Define.lua、Attribute.lua、Function.lua 均通過官方 MD5、已確認客戶端 codec、UTF-8 與重新加密逐 byte 相等檢查。新增已審查指紋至離線研究工具，現在共九份。原文、metadata、參數不隨程式發佈。

- Define.lua 明確定義 EUseItemKind：None 0、六個裝備槽 1–6、CanUse 7、CanEat 8、Special 9、NoStack 10、EquipSacredObject 11；EAttribute.Hp/Sp 分別為 25/26。
- Function.lua 的 CheckFlag 使用從 1 開始的位元遮罩；ItemData.New 第二個 flag byte 的第 1 bit 是 isPVPTimeOver。
- ItemData.CanOverlap 完整保留六個特殊物品、裝備／聖物、兩類交通工具、Special 容器、限時／賽季物品、HP/SP 補瓶與特殊瓶 ID、修復用品次數、紋章等排除條件。沒有把單一欄位當 boolean。針對 Special 容器，IsEggItem 所有分支皆非零，因此等價排除整類；時間條件仍維持各自的 fitType 範圍。
- Native metadata 中另有不同用途的 EAttribute，未拿它替代 Lua 的同名常數。

只有原有 SHA256 鎖定的 1296 ItemData 可產生新欄位。解析器新增兩組 attributes（u16 kind、u8 effect、signed i32 value）、flags2、is_pvp_time_over 與經完整規則推導的 stackable。舊版輸出維持原狀。正規化物品快照 schema 提升為 runtime-v3-dynamic，保留 v1/v2、原始來源與失敗紀錄，不把舊快照缺少的欄位默認成可堆疊。

## 實檔交叉驗證

11,366 筆同版物品全部可判定，其中 6,116 筆可堆疊；與舊種子 11,287 筆交叉比對完全一致，零差異，另有 79 筆新物品。這只是本版實檔的回歸證據，沒有放寬未知版本的來源限制。

兩端 CurrentStackRules 是穩定的 Mapping 介面，每次讀取目前啟用版本，不永久快取舊表。伺服器明示 server_stackable 仍優先；目前版本缺資料時，既有「明確空格的一件物品」例外不變，其他不明增量要求重新同步。遠征獎勵容量未知則不送出領取操作；儲藏仍可使用當次伺服器已證實的多件堆疊／雜物櫃資料。沒有新增封包或改變操作授權。

測試以合成欄位涵蓋所有排除條件、時間／fitType／flag 邊界、第一與第二屬性差異、版本切換、伺服器證據優先及冷啟動；舊煉金、遠征、購買回執測試改為明示自身需要的合成 stack proof，避免依賴已移除的遊戲種子。並未放寬產品對未知資料的處理。

本階段保持本機提交，未推送／合併／Release，未執行手機、正式服或遠端 CI 驗收。全量比較在 validation/remaining-resources-1296/stack-rule-comparison.json。

## 驗證結果

桌面完整 1,734 項成功、略過 3；Android 184 檔全部成功，報告 1,412 項、略過 4。最後新增容量判斷固定單一版本快照，兩端另跑堆疊規則 4 項與遠征 29 項，全部成功。兩端實際 Runtime 各讀出 11,366 筆／6,116 筆可堆疊，並確認物品圖像仍可用；規範資料庫保留前兩代快照。種子由 17,825,792 降為 17,674,240 bytes。

日誌：/tmp/phase17-desktop-final.log、/tmp/phase17-android-final.log、phase17-*-snapshot.log、phase17-*-real.log。初次回歸的舊種子依賴已改為明示的本機合成測試證據，沒有把未知物品默認為可堆疊。
