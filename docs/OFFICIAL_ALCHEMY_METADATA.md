# 官方煉金材料資料遷移

兩端煉金資料已改由當次已啟用 Runtime 的正規化 ItemData 讀取，移除 alchemy_catalog.json 種子，剩五項：stage_coordinates、graph_origins、navigation_data、combat_catalog、normal_attack_data。沒有把新版 spares 與舊 combat_catalog 的 kind／special／restrict 混用。

## 官方證據與語意

在原九份已驗證 Lua 基礎上，另取得同版 UIAlchemy.lua、UIAlchemyModule.lua、Bag.lua；官方路徑清單 MD5、內容 SHA256、解碼後 SHA256 與重新加密均驗證。研究工具現在鎖定十二份來源，原文與 codec 參數不隨程式發佈。

UIAlchemy 材料篩選使用 ItemData.CanAlchemy、kind、specialAbility、spares[1]；ItemData.lua 明確定義四種披風排除、夥伴裝備材質 73、寵物、煉金書、設計圖與食譜。LaLa 仍保留鎖定／強化／鑲嵌物品的保守排除、材料組合限制、每輪結果與扣料／入包確認，沒有新增自動操作。

Bag.GetNowUseNum 呼叫 ItemBox:GetCount，逐已占用格位計數；不將 itemW×itemH 當作占用容量。保留 LaLa 原有至少五個空格政策，改以當次伺服器背包占用格位計算。桌面製作詳情的尺寸欄改標「物品欄尺寸」，不暗示其乘積等於容量。

一次 prepare 取得單一版本的材料快照，每輪送出前重新驗證。若資料版本在連續煉金期間變更，等待既有回執處理後停止後續送出，要求重新選材，避免原本的操作類別沿用到不同版本。冷啟動／欄位缺少時顯示未同步，不借用舊種子。

## 全量實檔與回歸

兩端均從同版資料庫讀出 11,366 筆完整物品欄位。符合既有安全政策的分類：一般 4,749、夥伴 64、寵物 48、煉金書 4、設計圖 42、食譜 86。對照舊 11,257 筆煉金資料，有 26 筆官方 spares[1] 已改為 73，依同版官方規則成為可用夥伴裝備材料；沒有為了符合舊值改寫官方資料。詳細差異保存在 validation/remaining-resources-1296/alchemy-current-comparison.json。

最終桌面完整 1,738 項成功（略過 3）；Android 185 檔全部成功，報告 1,416 項（略過 4）。新增合成測試涵蓋冷啟動／部分欄位、全部材料分類與排除、容量邊界、同版快照、版本變更後停止下一輪。既有回執與 UI 測試明示兩筆合成材料，不再依賴隨附遊戲種子；資源契約測試改檢查仍需隨附的導航資料。兩端實檔、repository audit、來源一致性另行驗證。

仍只留本機提交，未推送、合併或 Release。未做正式服、Windows／macOS 或 Android 實機驗收。戰鬥／普攻尚需完整官方跨表與消費者換源；導航的既有下載額度與幾何格式限制未放寬。
