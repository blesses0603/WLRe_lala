# 1275 官方 A* 啟動掃描快取對照

已從使用者上傳、通過來源指紋核對的 14 組場景／dependency Bundle，沿 AstarPath 的
`data.file_cachedStartup` 引用取得官方 TextAsset。全部 `cacheStartup=1`、`scanOnStartup=0`。
此處是官方隨場景提供的啟動掃描快照；目前沒有遊戲運行中重新掃描的擷取。

先前僅檢查 `data.dataString`，其內只有設定 ZIP，因此漏查外部快取引用。
外部快取另外包含 `graph0_extra.binary`、`graph0_references.binary`、
`graph_references.binary`、`node_link2.binary`、`graph0.json` 與 `meta.json`。

## 已完成的逐項核對

- 場景與 dependency 的 SHA-256、AstarPath 所屬 CAB／path ID，以及快取 TextAsset 的完整引用。
- ZIP CRC、完整項目清單、Astar 4.3.60／RecastGraph 版本與圖形種類。
- 單 tile 的邊界、兩組 Int3 頂點、三角形索引、每個節點重複儲存的索引及 metadata。
- 二進位完整消耗至 EOF，拒絕截斷、額外位元組、越界索引、未知 ZIP 項目或多 tile 格式。
- 快取設定與場景內嵌設定：14／14 相符。
- 目前候選與官方快取的面數、毫米量化後相同三角面數，以及兩組原始頂點各自的投影／高度差。

| 模型 | 官方快取面數 | 候選面數 | 快取與場景設定 |
| --- | ---: | ---: | --- |
| 12170 | 214 | 626 | 相符 |
| 12910 | 676 | 2 | 相符 |
| 13216 | 81 | 14 | 相符 |
| 13217 | 146 | 30 | 相符 |
| 13218 | 360 | 83 | 相符 |
| 13219 | 420 | 1053 | 相符 |
| 13220 | 375 | 62 | 相符 |
| 13221 | 212 | 30 | 相符 |
| 13222 | 267 | 30 | 相符 |
| 13223 | 232 | 30 | 相符 |
| 13224 | 85 | 30 | 相符 |
| 13225 | 188 | 30 | 相符 |
| 13226 | 250 | 30 | 相符 |
| 13227 | 144 | 30 | 相符 |

## 12170 結果

官方快取有 214 面、129 頂點，目前候選有 626 面。毫米量化後，兩組官方原始頂點
各自與候選比較，完全相同的三角面數均為 0；官方 214 個面中心中，201 個的 XZ 投影落在候選內。
這些數字代表幾何差異，面數差異本身不能判定可走區域是否等價。

保留序列化的 `vertices_a_int3` 與 `vertices_b_int3` 原始名稱。兩組的座標框架語意
尚未由官方 Managed 實作核定，報告分別列出差異，沒有自行選其中一組宣稱為已驗證世界座標。
節點 metadata 與完整連線 binary 均保留；目前比較器使用幾何投影，尚未解碼官方節點連線語意。

12170 的新解析結果也與儲存庫中歷史版本的同圖解碼結果完全相符，作為序列化格式回歸。
本次每份輸出仍各自由 1275 原始 Bundle 重新取得並附來源指紋。

## 重跑方式

以下 `1275_差異/` 路徑須由使用者在**私人本機**自行準備，GitHub 分支只保留選取清單 JSON，不公開保存 Unity Bundle、`unity default resources` 或原始官方快取。

```bash
python -m pip install -r requirements-navigation.txt
python -m tools.navigation.official_cache --scenes-zip "1275_差異/LaLa_1275_M12170_導航來源.zip" --candidate-dir /private/M12170-candidates --output /private/1275-official-cache-12170
python -m tools.navigation.official_cache --scenes-zip "1275_差異/LaLa_1275_Scenes_差異Bundle_重建.zip" --select "1275_差異/LaLa_1275_差異選取清單.json" --candidate-dir /private/1275-rebuilt-navmesh-verified --output /private/1275-official-cache-13
```

輸出每模型的官方原始快取 ZIP、解碼 JSON 及總報告；目的資料夾必須不存在。
原始快取和網格只留在私人輸出目錄，不加入程式碼提交。
來源需要使用者已有的場景檔，不會下載遊戲、修改遊戲或擷取進程記憶體。

## 仍需核定

取得官方 Managed A* 實作後，可繼續核對頂點座標框架、節點旗標及連線的序列化語意。
實際遊戲中掃描／動態障礙更新後的圖仍需另外擷取。
本次已取得官方隨場景出貨的掃描快取，但重建候選與快取有差異，
`official_runtime_graph_captured=false`、`can_send_packets=false` 維持，不開放 1275 自動行走。

驗證結果：14 份官方快取共 3,650 面，設定皆與所屬場景一致。
完整回歸 874 項：871 通過、3 跳過；文件稽核與差異格式檢查通過。

## 1275 預設來源已改為官方快取

`Repository()` 在 1275 基準下，只載入使用者資料目錄的
`official_resources_1275/1275_OfficialNavigation.zip`。
14 份原始快取的 SHA-256、大小、來源 Bundle 指紋與面數固定在
[official_navigation_1275.json](../wlre/resources/official_navigation_1275.json)。
缺少、損壞或未涵蓋的模型會顯示原因；不讀取 1262 的 `navigation_data.zip`，
也不把 upstream Recast 重建候選替代為官方資料。

純 Python 執行期解析器移至
[official_cache_format.py](../wlre/services/world/official_cache_format.py)，
[official_navigation.py](../wlre/services/world/official_navigation.py)
負責封裝校驗、私人安裝與讀取；桌面程式不需要 UnityPy。
UnityPy 只在從原始 Unity Bundle 提取快取時使用。

先依前述命令提取 1+13 份官方原始快取，再封裝：

```bash
python -m tools.navigation.package_official --source-dir /private/1275-official-cache-12170 --source-dir /private/1275-official-cache-13 --output /private/1275_OfficialNavigation.zip --install
```

`--install` 可省略，以便把私人封裝交給另一台電腦使用。
在另一台電腦的「全場景導航」視窗按「匯入官方快取」，選擇此封裝即可安裝並更新目錄。
安裝器先校驗全部 14 個模型，再以原子方式發布；拒絕覆寫已安裝檔案。
封裝只包含固定 SHA 的原始官方快取與清單，候選 JSON 不能冒充官方資料。
原始幾何不加入程式碼提交；git 更新程式後，使用者電腦仍須匯入一次私人快取封裝。

預覽與 CLI 目錄會標示來源版本；路徑與表面查詢會附官方來源指紋。
12170 現在預設顯示官方 214 面。僅使用原始 B 頂點作離線共享邊幾何查詢，
不會因更換來源而自行認定封包座標、官方節點旗標、連線語意或動態障礙已驗證。
自動行走的座標入口仍阻擋 1275，所有預覽路徑維持 `can_send_packets=false`。

來源切換後完整回歸 881 項：878 通過、3 跳過；官方快取實際封裝／安裝、
14 模型載入、12170 介面顯示 214 面、封包模式停用與資源自檢均通過。
