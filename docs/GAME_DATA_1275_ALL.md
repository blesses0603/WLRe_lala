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


## 第二項完成：1275 Eve NPC / Interact 完整唯讀解碼（新增）

依使用者上傳的 1262 Lua `Lua/Logic/Data.lua`、`Lua/Data/EventData.lua` 和 1275 原始 `Eve.bytes`，實際逐場景解析並核對段落界線與每場固定 44 bytes 頁尾，**1,262/1,262 場景全部成功**。

- `Eve.bytes` 原始 SHA-256：`f5fc56b1d6cf7c00dd20b2f35c04b4cbc60c92ccdb6085fbe465c7e6526745ad`。
- 1275：**1,262 個事件場景、10,975 個 NPC、1,634 組互動選單（一般 1,569、武器商店 19、道具商店 46）**。
- 1262 已知索引：1,256 場景、10,879 個 NPC、1,622 組互動選單（一般 1,557、商店合計 65）。
- 另提供 `WLRE_1275_Eve_NPC_索引包.zip`，內有唯讀 `npc_event_index_1275.json.gz` 與 `npc_interact_1275.json.gz`。
- 程式 `wlre/services/world/npc_1275_eve.py` 僅允許來源 SHA-256、壓縮內容 SHA-256、場景數、紀錄數、索引唯一性與欄位格式均核對過的資料，拒絕任意替換。
- 這只是資料來源級驗證，**沒有把 LaLa 的 1262 C20 NPC 互動決策轉成 1275，也沒有解除 NPC 交易封鎖**，必須先驗證伺服器狀態與關鍵事件索引的逐筆差異。

離線 Python 範例（指向另外交付的 NPC Eve ZIP，不會安裝或送出封包）：

~~~python
from wlre.services.world.npc_1275_eve import read_verified_zip, scene_npcs
verified = read_verified_zip("WLRE_1275_Eve_NPC_索引包.zip")
print(len(scene_npcs(verified, 10001)))
~~~

測試：

~~~powershell
py -m unittest discover -s tests -p test_npc_1275_eve.py -v
~~~


## 1262→1275 實際重跑比對（2026-10-23）

本次從使用者上傳的 **兩份 1262 RAR Manifest** 和 **兩份 1275 ZIP Manifest** 重新解出二進位，以相同的 YooAsset 2.2.5 格式獨立解析比對：

| 類型 | 資源新增 | 資源移除 | Bundle 新增 | Bundle 移除 | 原 Bundle 變動 | Bundle 依賴變動 |
|---|---:|---:|---:|---:|---:|---:|
| DataPackage | 0 | 0 | 0 | 0 | 15 | 0 |
| MainPackage | 63 | 0 | 24 | 0 | 20 | 0 |

新版真實資料交叉校驗（非宣稱 1262 相同）：
- Eve NPC 10,975 筆、互動選單 1,634 組，其中 65 組商店共 **309 個商品位置／215 種商品 ID**，1275 ItemData_C 缺漏 **0**。
- 1275 `DailyTaskData_C` 依官方 `DailyTaskData.lua`、`AwardData.lua` 完整解析 **48 個群組、420 筆任務**；群組引用與 `TextData_C` 任務名稱引用缺漏均為 **0**。
- 1275 `NpcTalkData_C` SHA-256 `9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8`，與 LaLa 已核對的 1262 原始表相同。
- 1275 的物品 ID 32297、10044、10002 經確認符合 main 既有 1262 regression samples；**不能由此推定其餘 ID 不變**。
- `resources.assets` 和 `resources.resource` 的 SHA-256 跨版本完全相同。
- 使用者的 1262 DataPackage、MainPackage 壓縮包僅包含 Manifest，**沒有 1262 的 160 張原始 TextAsset**。因此這 160 張仍沒有逐筆比較結果（既不是通過也不是失敗）；不能把 1275 筆數差直接當成新增 ID。

此階段新增 `wlre/services/world/daily_task_1275.py` 作為每日任務**唯讀**的嚴格解析器，並新增截斷、無效更新週期、重複群組測試；不會改動任務流程或送出封包。


## 2026-10-23 LaLa 電腦端限定：全部現行功能依賴核對

此節不分析遊戲全體素材，只追蹤 **LaLa main v0.5.17 真正讀取的來源**。主程式版本及 `wlre/resources/lala_supported_resources.json` 繼續維持已驗證的 1262，不以新增 1275 稽核結果解除登入封鎖。

### 來源 SHA-256 逐表比較（1262 來源由 main 內建 catalog 記錄）

**兩版原始 TextAsset SHA-256 完全一致**：

- `DungeonData_C`：`4743f7703403c556f635a630775d318052306f879d3ee3dbb29626ca9b5f56b9`
- `CooperateEventData_C`：`4adb067093d3961436065c1244bdf621e870ce0e320fbe4153f031ae6a37406e`
- `AdventureData_C`：`e240dbc011fe213f2a5d907b9d02281ab2417b764caecd2fd222f99faedb59e8`
- `AdventureLvData_C`：`98b8359741f2e67fe7a15214c6a6b1c6495977a00d6c666beed9d129f4d520d4`
- `NpcTalkData_C`：`9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8`

**來源 SHA-256 異動，不能直接宣告執行期相容**：`ScenesData_C`、`NpcData_C`、`NpcCareerData_C`、`TextData_C`、`TalkData_C`、`ItemData_C`、`SmithData_C`。

### 1275 實際使用的欄位解析與交叉引用

以 main 的嚴格二進位讀取格式從使用者提供的 1275 TextAsset 重新執行：

| 目標 | 1275 確認筆數 | 與 LaLa 1262 內建版本 |
|---|---:|---|
| 副本 DungeonData_C | 30 | 原始內容完全一致，可保留原副本主資料 |
| 協力 CooperateEventData_C | 2 | 原始內容完全一致，可保留原協力活動主資料 |
| 遠征 AdventureData_C | 260 | 原始內容完全一致 |
| 遠征等級 AdventureLvData_C | 10 | 原始內容完全一致 |
| NPC 角色 NpcData_C | 7,561 | 1262 內建遠征 NPC 索引 7,543，實際內容異動 |
| ScenesData_C | 1,337 | 1262 是 1,336，實際內容異動 |
| 物品 ItemData_C | 11,304 | 1262 NPC 物品索引 11,287，實際內容異動 |
| NPC 事件（Eve） | 10,975 | 1262 索引 10,879，實際內容異動 |
| NPC 互動選單（Eve） | 1,634 | 1262 索引 1,622，實際內容異動 |
| 製作 SmithData_C | 1,032 | 1262 內建 1,030，實際內容異動 |

從 **LaLa main 的 `crafting_catalog.json` 1,030 個既有配方 ID** 與新版 SmithData_C 做集合比較：**沒有移除配方 ID，新增加 39852「藍莓優格壁紙」、39854「藍莓優格地磚」兩筆**。注意此為 ID 集合比對，舊配方的工具、材料、工時及順序仍可能有變動，不能只看 ID 得出完全相同的結論。

1275 交叉引用驗證結果：65 組商店／309 商品位置／215 種物品 ID 均能在新版 ItemData 找到；一般 NPC 選項的 TalkData 參照缺漏 0；30 筆副本的場景 ID 缺漏 0；遠征的名稱與說明文字 ID 缺漏 0。

### 對 LaLa 的實際修改需求判定

| 功能 | 結論 |
|---|---|
| 登入前官方版本閘門 | **必須保留** 1262 支援基準；未經正式驗收不可改成 1275 |
| 副本／協力核心資料 | 原始表完全相同；原資料不必強制重建，仍需核對場景／文字相依 |
| 遠征任務、等級 | 原始表完全相同；原資料不必重建，仍需核對 NPC 職業、名稱、物品引用 |
| NPC／互動／商店 | 新版資料已提取但來源異動；維持伺服器安全限制，未完成協定 E2E 不開放交易 |
| 地圖／傳送 | 場景來源異動；必須重新核對既有路線與新版出口／座標映射 |
| 製作／煉金／物品 | 新增兩個配方 ID；原有配方欄位、物品內容及裝備限制仍須驗證 |
| 戰鬥／技能 | 原始資料可檢查，但缺正式服封包／技能行為驗證，不推定協定相容 |
| UI／圖示 | MainPackage 差異不表示 LaLa 內建圖片必須替換；只更新實際使用的素材 |
| 每日任務 | 1275 資料已解析，但目前 main 未找到獨立每日任務功能，非本次桌面版必要替換項 |

### 離線回歸與剩餘界線

離線驗證工具獨立執行 **20 項測試均通過**（真實官方來源檢查與負面情境），並輸出功能影響矩陣、資源來源比對、製作配方新增 ID 與 CSV。上述 20 項是在分析環境執行，並非 GitHub CI 全套或正式遊戲實機驗收。

不得將原始 Bundle Hash 改變自動當作其中每張表都改；亦不能把離線結果當成 Windows/macOS EXE、正式伺服器互動或 1275 LaLa 發版的驗收證明。
