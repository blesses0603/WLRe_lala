# 飄流幻境 RE｜1262 → 1275 全資源更新驗收總表

## 版本、來源與界線

- 讀取本 PR 建立時 GitHub main 的程式版本為 v0.5.17。
- main 的 wlre/resources/lala_supported_resources.json 仍標記 DataPackage 與 MainPackage 官方支援基準為 1262。
- 本次 **不修改這份相容性宣告**，因為 NPC 互動、每日任務、傳送、商店和副本的線上端到端驗收尚未完成。
- 使用者提供 1262/1275 的四份 YooAsset Manifest，及 1275 FullDiff 兩個 RAR 分卷。
- 本 PR 的資料來源是另行交付的 WLRE_LaLa_1275_全資源差異與校驗包.zip，其中存放 160 份 1275 原始 TextAsset bytes、3 份已轉換的唯讀索引，及清單校驗資訊，**不提交遊戲資源至 GitHub**。
- 1262 同名二進位資料表未完整取得，故無法將 160 份表格全部宣稱為「內容已變更」，更不能一律直接替換 1262 執行期表。

## 清點與校驗

| 目標 | 覆蓋量 | 已完成 | 仍需完成 |
| --- | ---: | --- | --- |
| DataPackage 1275 | 15 個變動 Bundle | 160 張原始資料表已提取與校驗 | 與 1262 逐表資料列比較 |
| MainPackage 1275 | 44 個新增／變動 Bundle | 59 Bundle 差異中屬於 MainPackage 的 44 筆元資料已收錄 | 43 個尚未逐一解析的主資源 Bundle，以及 UI / 美術資產對照 |
| MainPackage 新增資產 | 63 筆 | 官方資源地址與 Bundle 對應清單已收錄 | 確認 LaLa 實際使用的圖示和 UI |
| NPC 對話與文字 | 2 張 | TalkData_C 29,890 筆、TextData_C 39,947 筆來源已驗證，唯讀索引已產生 | 更新執行期資料來源並實機核對 |
| 物品 | 1 張 | ItemData_C 11,304 筆來源已驗證，唯讀索引已產生 | 商店折扣、物品使用與背包交易驗收 |
| NPC 事件和商店 | Eve / UISellData | 原始 1275 資料已封存於校驗包 | 解析 EventData.NewNpc / NewInteract，核對 C20/S20 與 S27 |
| 每日任務 | DailyTaskData / Reward | 原始表已封存並驗證 | 嚴格解析欄位與角色任務狀態映射 |
| 地圖傳送 | DoorLink / Scenes / MapActionNpc | 原始表已封存並驗證 | ID、座標、場景對應、傳送安全校驗 |
| 副本、協力、遠征 | Dungeon / Cooperate / Adventure | 原始表已封存並驗證 | 重建資料索引與 UI，正式服測試 |

## 離線使用方式

在包含此 PR 的 LaLa 專案目錄下執行：

~~~powershell
py -m wlre.services.world.game_data_1275 "C:\下載路徑\WLRE_LaLa_1275_全資源差異與校驗包.zip"
py -m wlre.services.world.game_data_1275 "C:\下載路徑\WLRE_LaLa_1275_全資源差異與校驗包.zip" --table DailyTaskData_C
~~~

程式會核對整份 Manifest 固定 SHA-256、160 份原始表格和 3 份唯讀索引各自的長度與 SHA-256，並檢查清單列出的 59 個 Bundle 和 63 個新增資源。任何成員被修改／新增／刪除、重複檔案、清單版本或校驗碼不符都會拒絕。

該工具不寫入遊戲資料夾、不解壓任意 ZIP 路徑、不發送網路封包、不中斷現有 LaLa 功能、不更改已設定的官方遊戲支援基準。

## 與前一階段 PR 的關係

- PR #49 提供三份 1275 NPC 唯讀索引的驗證與安全安裝，不依賴新的全資源清單。
- 本 PR 提供 **完整 160 張資料表與 MainPackage 變動索引** 的固定校驗框架。
- 兩者的用途不同；未經正式驗收，均不得視為 1275 執行期完全相容。

## 驗收與回歸

執行：

~~~powershell
py -m unittest discover -s tests -p test_game_data_1275.py -v
~~~

另外還必須在 GitHub Actions 檢查 Linux、Windows、macOS 的完整自動測試和原生建置前檢查，並在正式服驗證所有更新功能。測試通過只證明此索引驗證器安全運作，不等於 1275 版本的 NPC 買賣和傳送功能已開放。

**PR 性質：** 純新增工具、回歸測試與技術文件，保留 main v0.5.17，不合併 main、不修改 Release Tag。
