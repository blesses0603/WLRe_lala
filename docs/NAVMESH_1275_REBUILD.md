# 1275 可行走網格重建

這一階段新增了真正的 Recast 掃描器，能由碰撞三角面進行 voxelization、
坡度／淨高篩選、角色半徑侵蝕、region、contour、polygon 與 detail mesh 建立。
目前已使用重建的 1275 場景 ZIP 產出 **13 個真實來源的離線候選網格**，並驗證各候選的連通區可尋路。
模型 12910 已接入使用者補上的 Unity 內建 Mesh 來源；尚未驗證官方 Astar 設定等價或正式服移動。
所有輸出均為候選資料，`can_send_packets=false`；既有正式服移動與直接傳送限制維持。


最新檢查已沿 AstarPath 外部引用取得 14 份官方啟動掃描快取；先前只檢查內嵌設定 ZIP，漏查快取引用。
官方快取與重建候選存在差異；1275 預設預覽來源已改為固定 SHA 的官方快取，重建候選僅保留作比較。
安裝方式與限制詳見 [官方快取逐項對照](OFFICIAL_NAVIGATION_CACHE_1275.md)。

## 來源與工具

| 工具 | 責任 |
|---|---|
| [build_recast.py](../tools/navigation/build_recast.py) | 由固定 Recast v1.6.0 原始碼編譯 scanner |
| [recast_scan.cpp](../tools/navigation/recast_scan.cpp) | 真正的 Recast voxel／可行走多邊形與細部三角面重建 |
| [LaLaCollisionExport.cs](../tools/navigation/unity/LaLaCollisionExport.cs) | 私人 Unity 2021.3 專案中載入來源 SHA 相符的場景 pair，匯出啟用的 Collider／Terrain |
| [scan.py](../tools/navigation/scan.py) | 輸入驗證、來源指紋比對、掃描與候選資料輸出 |
| [unity_bundle_geometry.py](../tools/navigation/unity_bundle_geometry.py) | 直接解析 SHA 已核對的 UnityFS v8 場景、Transform、Terrain 與 Collider，逐場產出候選及阻擋報告 |
| [query.py](../tools/navigation/query.py) | 只讀離線尋路，以 Unity world 公尺輸入與輸出 |

Recast 使用 upstream v1.6.0 的 peeled commit
`6dc1667f580357e8a2154c28b7867bea7e8ad3a7`，未將第三方原始碼或編譯產物納入倉庫。
編譯器需支援 GCC 相容的 C++17 參數（例如 GCC／Clang）。本輪在 Linux 實際編譯；
Windows／Unity Editor 匯出腳本尚未實機驗證。

```bash
git clone --branch v1.6.0 https://github.com/recastnavigation/recastnavigation.git /tmp/recast-1.6.0
git -C /tmp/recast-1.6.0 checkout 6dc1667f580357e8a2154c28b7867bea7e8ad3a7
python -m tools.navigation.build_recast --source /tmp/recast-1.6.0 --output /tmp/lala-recast-scan
```

建置器會拒絕錯誤 commit 或已修改的 Recast 原始碼；不會覆寫既有 scanner。
本工具只編譯離線掃描器，沒有打包或發布 LaLa 安裝程式。

## 先驗證工具可重現

下列範例是 **合成平面，不是遊戲場景**。範例中的 agent、voxel 與 bounds 數值
不能直接當成官方 1275 Recast 設定。

```bash
python -m tools.navigation.scan --geometry tools/navigation/examples/plane.json --settings tools/navigation/examples/settings.json --backend /tmp/lala-recast-scan --output /tmp/plane-candidate.json
python -m tools.navigation.query --mesh /tmp/plane-candidate.json --start 2 2 --end 8 8
```

輸出包含 Unity world-space 三角面、掃描參數、輸入／scanner SHA-256、來源資訊。
既有離線 mesh reader 以毫米 Int3 重建共邊連通性；查詢器再換回公尺。
這不代表已確認遊戲封包座標、Astar 原始 node flags、off-mesh links 或動態障礙。

## 匯出真實場景的幾何

需要使用者的 `LaLa_1275_Scenes_差異Bundle.zip`、`LaLa_1275_差異選取清單.json`
與由官方來源提取的 Recast 設定索引。這些私人來源應由玩家自行放在未追蹤的本機 `1275_差異/` 目錄，公開 GitHub 不保存原始 Bundle；
歷次離線驗證曾確認 26 個 Bundle 的大小／SHA、ZIP CRC 與 13 份 Graph 設定。

1. 在私人 Unity 2021.3 專案放入 `Assets/Editor/LaLaCollisionExport.cs`。
   不要修改正式遊戲安裝目錄。使用相符的 Unity／目標平台載入遊戲 Bundle。
2. 先執行 `extract_1275_recast_settings` 與 `audit_1275_scene_collision` 驗證原始 ZIP。
   記下指定模型的 scene、dependency Bundle SHA-256，及 `embedded_zip_sha256`。
3. 在 Unity 的 `LaLa / Export loaded scene collision geometry` 視窗，填入模型與三個 SHA；
   Graph settings SHA 欄使用上一步的 **embedded ZIP SHA**。
   進入私人空專案的 Play Mode，以按鈕選擇並載入已驗證的 dependency 與 scene Bundle。
4. 按官方 Graph 指定的 layer bitmask、`rasterizeColliders`、`rasterizeTerrain` 設定匯出。
   僅包含目前 active scene 中啟用且 active-in-hierarchy 的物件；排除 trigger。
5. MeshCollider 使用完整 local-to-world Transform；反射 Transform 會翻轉繞序。
   BoxCollider 依中心與大小建模。Terrain 透過 Unity `GetHeights`／`GetHoles` 取得高度及洞，
   不猜測原始高度圖的量化倍率。Terrain 的旋轉／縮放、convex hull、未知 Collider、
   無法讀取的 Mesh 或超過預算的資料會拒絕匯出，不會默默略過。

這個 Editor helper 不宣稱與官方 Astar collider tessellation 或動態 NavMeshCut 完全等價。
若出現缺依賴、缺腳本或無法讀取場景，應補齊原始來源與 Unity 環境後驗證，不能以一個
空場景或渲染模型替代。遊戲原始 Mesh、Terrain 高度與衍生遊戲網格都留在私人資料夾。

## 掃描設定與來源比對

`settings.json` 的所有值必須明確提供；長度與高度使用公尺，slope 使用度，
region area 使用 voxel cell 面積，detail sample distance/error 使用公尺。
`max_edge_length` 由公尺換算為水平 voxel 數。請依官方 Astar 4.3.60 實作核對換算；
例如 `cell_height`、region 面積與 detail sampling **不會靠猜測由 JSON 欄位自動補值**。
本輪沒有證明 upstream Recast v1.6.0 與官方 Astar 掃描產物逐位元等價。

```bash
python -m tools.navigation.scan --geometry /private/12910_geometry.json --settings /private/12910_scan_settings.json --scenes-zip /private/LaLa_1275_Scenes_差異Bundle.zip --select /private/LaLa_1275_差異選取清單.json --backend /tmp/lala-recast-scan --output /private/12910_candidate.json
```

指定原始 ZIP 與選取清單時，會重新核對全部場景 pair、Graph ZIP 與匯出記錄的 SHA。
`source_files_verified` 僅代表原檔指紋相符；不能當作幾何匯出、官方設定換算或實機驗收已完成。

目前掃描器使用單塊 watershed region；水平 grid 上限為 1,600 萬 cells，
超過此預算會拒絕，尚未實作可驗證的多 tile 邊界接縫與全場景拼接。
不同高度使用不同 spans，不會把 XZ 重疊樓層直接合併。

## 驗證入口與尚缺驗收

```bash
WLRE_RECAST_SCANNER=/tmp/lala-recast-scan python -m unittest discover -s tests -p test_recast_scan.py -v
```

測試實際呼叫原生 Recast，涵蓋平面可達、邊界侵蝕、半徑／窄廊、過高台階、
坡度、淨高、反向繞序與上下樓層分離，以及來源 SHA 不符拒絕。
未設定 scanner 時，原生整合案例會標示跳過，不會偽裝已驗證。
Linux CI 已新增固定 commit 的建置步驟並設定 scanner 路徑，避免日後只跑到 Python 輸入檢查；
工作流程仍待 GitHub Actions 執行確認；本地結果不代替 CI 結果。

真正啟用 1275 導航前仍需：

- 對 13 個真實模型完成幾何匯出與官方掃描參數等價驗證。
- 驗證 tile 接縫、動態 NavMeshCut、off-mesh links 與原 node flags。
- 以地圖已知點、各樓層與伺服器位置回覆確認 world／封包座標。
- 通過障礙、陡坡、狹窄通道、門口與跨高度的正式服驗收。

因此本輪已重建 13 個真實來源候選；官方掃描等價、完整障礙與正式服座標仍待驗證。

### 本輪驗證結果

完整 Linux 回歸執行 823 項：818 通過、5 項跳過；其後新增的低台階連通案例連同網格測試共 12 項均通過。資源自檢、GUI 冒煙檢查與倉庫／文件稽核通過。原生 Recast binary 已實際編譯並以命令列產出合成平面候選網格與尋路結果；Unity Editor helper 尚未編譯或實機執行。本輪未產生遊戲安裝包。


## 重建 ZIP 的實際結果

新版來源是 UnityFS **v8**，舊解析器固定只接受 v6。現在已依格式版本處理 header 16-byte 對齊，
並用全部 26 檔原始來源驗證，沒有將版本不符直接忽略。

`unity_bundle_geometry` 使用 UnityPy 解開主場景及 dependency，排除 prefab 定義的重複物件，
核對 Graph layer mask、啟用旗標、trigger 與完整父子 Transform。Terrain 的 32766 量化倍率
會與序列化 `m_MinMaxPatchHeights` 的上下界交叉驗證；非空 holes 或不明編碼會拒絕。
取樣步距使用 Graph 的 `terrainSampleSize=3` 並保留末端邊界。

```bash
python -m pip install UnityPy==1.25.4 lz4
python -m tools.navigation.unity_bundle_geometry --scenes-zip "1275_差異/LaLa_1275_Scenes_差異Bundle_重建.zip" --select "1275_差異/LaLa_1275_差異選取清單.json" --backend /tmp/lala-recast-scan --cell-height 0.05 --output /private/1275-candidates
```

必須明確提供候選 voxel height。0.05m、region area=0、detail sampling 是這次 upstream Recast
候選配置，**不宣稱已證明與官方 Astar 4.3.60 相同**。結果會保留這項限制與 `can_send_packets=false`。

| 模型 | 候選三角形數 | 結果 |
|---|---:|---|
| 12910 | 2 | 已由 SHA 已核對的內建 Plane Mesh 建立，並通過離線尋路 |
| 13216 | 14 | 已建立並通過離線連通區尋路 |
| 13217 | 30 | 已建立並通過離線連通區尋路 |
| 13218 | 83 | 已建立並通過離線連通區尋路 |
| 13219 | 1,053 | 已建立並通過離線連通區尋路 |
| 13220 | 62 | 已建立並通過離線連通區尋路 |
| 13221～13227 | 各 30 | 已建立並通過離線連通區尋路 |

候選與幾何資料保存在私人輸出目錄，未加入程式碼提交。12910 已由本輪補上的 `unity default resources` 解碼取得原始 Plane Mesh（121 頂點、200 三角面），不是依 path ID 猜成 Plane 或 Cube。
場景中沒有找到靜態 NavMeshCut 元件，仍不能推定執行時障礙不存在。

### 取得重建 ZIP 後的完整驗證

使用 UnityPy 1.25.4、原生 Recast scanner 與真正 1275 場景／選取清單跑完整回歸：832 項，829 通過、3 項跳過。26 個 Bundle 的解析及 13 份設定整合案例已實際執行；新增端到端案例重建 12 份候選並逐一驗證連通區尋路，對 12910 明確驗證缺依賴而非假造網格。資源自檢、GUI 啟動與文件稽核通過。原始幾何及候選仍僅保存在私人輸出目錄；本輪程式由 PR #52 分支維護。


## Unity 內建資源補齊後（2026-10-24）

已取得使用者上傳的 `1275_差異/unity default resources`，4,832,808 bytes，
SHA-256 `026e6d1d96dc2e28c72ece25f2419469d649a95e25b6929bc5cfc95bca529f8e`。
檔案內 Unity 版本字串為 `2021.3.43f1`，場景 Bundle 則是 `2021.3.45f2`；
候選資料會如實保留來源版本，不將來源解碼成功當成引擎／正式服相容證明。

```bash
python -m tools.navigation.unity_bundle_geometry --scenes-zip "1275_差異/LaLa_1275_Scenes_差異Bundle_重建.zip" --select "1275_差異/LaLa_1275_差異選取清單.json" --builtin-resources "1275_差異/unity default resources" --backend /tmp/lala-recast-scan --cell-height 0.05 --output /private/1275-all-candidates
```

內建資源 SHA 必須與本次已檢查來源相符。UnityPy 的外部依賴解析已限制為明確註冊的檔案，
不會遞迴搜尋工作目錄並自動混入其他版本的 `unity default resources`。
不提供該參數時，12910 仍會因缺少已驗證依賴而阻擋；提供後 13 場全部產出候選，0 場阻擋。

測試包含 13 場實際重建、各場連通區離線尋路及非流形共邊檢查；
官方 Astar 設定換算、動態障礙、封包座標與正式服驗收仍未完成，故不啟用遊戲移動。

### 13 場完整來源驗證結果

補上內建資源並限制依賴來源後，完整回歸共 834 項：831 通過、3 項跳過。真實來源測試包含無 builtin 時保留阻擋，以及提供固定 SHA builtin 後 13 場均重建與可尋路。額外逐一驗證所有候選的每個連通區皆可離線尋路，候選與驗證報告已整理為私人 ZIP（不含原始 Bundle 或輸入地形 Mesh）。正式服導航與官方 Astar 等價仍維持未驗證，本輪程式由 PR #52 分支維護。

## 遊戲內座標與動態障礙驗證紀錄

13 個候選網格可尋路，尚不代表官方 Astar 設定、封包座標或遊戲內動態障礙已驗證。
新增的 `navigation_evidence` 只在記憶體被動保存最多 256 筆自身定位與導航事件；
不包含帳密、角色 ID／名稱、聊天或封包原文。切換角色會清空，沒有自動上傳或持續寫檔。

登入角色後，在主視窗按「登入／選角」，再按 **匯出導航驗證**，儲存
`navigation_evidence_1275.json`。導航離線視窗亦有匯出入口。
檔案包含伺服器 S3-1／S7-1／S12-1 定位、C6-1 本機目的地要求、S6-1 目的地通知，
以及已辨識的障礙變更、導航修訂與 stale 狀態。

```bash
python -m tools.navigation.verify_evidence navigation_evidence_1275.json --output navigation_evidence_report.json
```

- C6-1 與 S6-1 都不是抵達確認，不能作為定位參考點。
- 同一地圖至少三個不共線的伺服器定位，還要有獨立量測的 Unity world XZ 參考，
  才能檢查縮放、軸向與 offset 是否一致。不能把公式換出的世界座標再填回來當證據。
- `reference_points` 由驗收者填入獨立觀測並交叉核對；工具只回報一致性，
  不會信任一個手動填寫的 `verified=true` 或因此開放移動。
- 每個參考點格式如下，`sequence` 對應匯出檔內該筆 `position_fix`；
  `world_xz` 應替換為真實獨立量測的公尺座標。

```json
{
  "sequence": 123,
  "reference_source": "independent_game_world_reference",
  "world_xz": [12.34, 56.78]
}
```

障礙驗收會檢查目前地圖的幾何變更是否讓導航修訂增加且標為 stale。
只有 stale 旗標、沒有新修訂，不能視為本次失效已處理。對未知尺寸／未解析幾何，
工具明確回報需要重建，不會把「停止舊路徑」當成「新障礙網格已重建」。
已知可忽略的非本圖房屋事件不計入本圖障礙變更。

沒有收到障礙變更也不代表沒有障礙；現有解碼範圍不能代表所有1275 runtime NavMeshCut。
取得真實資料後仍需確認障礙前路線、障礙加入後改路／停止、障礙移除後重建與樓層分離。
本輪尚未進行正式服實機驗收，所有報告維持 `can_send_packets=false`。

### 導航驗證紀錄功能回歸

加入被動記錄、匯出入口及參考／障礙失效檢查後，完整回歸 846 項：843 通過、3 項跳過。資源自檢、GUI 冒煙與文件稽核通過。正式服實機驗收仍未執行，需由登入後實際匯出的資料核對，不以此測試數量替代。

## 目前登入地圖 12170 的來源補齊

已檢查使用者上傳的 `navigation_evidence_1275.json`：

- 一筆 S3-1 登入定位，地圖／模型皆為 12170；沒有獨立世界座標參考點。
- 一筆 `furniture_snapshot` 屬房屋事件，`affects_current_map=false`，不是這張地圖的障礙變更。
- 12170 不在先前的 13 個差異模型中；本次另上傳的導航來源已補齊這張地圖。

新工具 [collect_navigation_scene.py](../tools/resources/collect_navigation_scene.py) 直接完整解碼已固定 SHA 的
1275 MainPackage Manifest（1,732 個 Bundle），依模型名稱定位 scene／dependency；
不是搜尋字串後猜檔案偏移，也不需要先前的差異清單。
原始序列化格式對照 YooAsset `2.2.5-preview` commit
`df77df485447f1f0426b218dceb915fb44ec6cfc` 的 ManifestTools／BufferReader。

```powershell
py -m tools.resources.collect_navigation_scene "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --model 12170 --output ".\LaLa_1275_M12170_導航來源.zip"
```

兩個場景本體共 868,481 bytes（約 848 KiB），ZIP 另附原始 MainPackage Manifest
及 `scene_selection.json`。工具檢查固定 Manifest SHA、檔案大小、官方 FileHash（MD5）、
YooAsset 格式的 little-endian CRC bytes，並記錄本體 SHA-256。
拒絕覆寫輸出及寫回遊戲資料目錄；沒有下載、上傳或修改原始安裝檔。

取得 ZIP 後可直接重建，不需再另外提供選取清單：

```bash
python -m tools.navigation.unity_bundle_geometry --scenes-zip /private/LaLa_1275_M12170_導航來源.zip --builtin-resources "1275_差異/unity default resources" --backend /tmp/lala-recast-scan --cell-height 0.05 --output /private/M12170-candidates
```

自含 ZIP 的讀取器會再以內附且 SHA 已固定的官方 Manifest 核對 pair 對應及本體。
這一份只包含指定 scene pair；若實際碰撞 Mesh 另引用其他依賴，仍會明確阻擋，
不把 Manifest 中列出的全部材質／UI 依賴盲目打包。

```bash
python -m tools.navigation.verify_evidence navigation_evidence_1275.json --candidate-dir /private/M12170-candidates
```

報告包含 `scene_candidate_coverage`、`candidate_surface_checks`，以及被忽略的非本圖幾何事件數量，
避免把一個未涵蓋的地圖誤當成已有可驗證的網格。原始紀錄沒有錯誤，
只是尚不足以證明目前地圖的座標與動態障礙已完成驗收。

### 12170 實際來源驗證結果

使用上傳的 `LaLa_1275_M12170_導航來源.zip`，通過內附固定 Manifest 與 pair 指紋核對，
以 UnityPy 1.25.4 和原生 Recast scanner 重建成功：58,482 個地形輸入三角形，
產出 626 個候選三角形，0 個非流形邊，沒有缺依賴阻擋。

登入定位 `(6000, 3303)` 依現有公式換算為 Unity XZ `(60.0, 31.3)` 公尺，
落在候選面 419，表面高度約 2.09 公尺。該點所在連通區有 275 面，
至其中遠端面的離線路徑約 110.88 公尺、59 個路徑點。
這是公式預測與靜態候選表面的相容檢查，不能代替獨立座標參考或伺服器抵達證明。

實際 12170 來源重建及登入點回歸案例由 `LALA_1275_CURRENT_SCENE_ZIP` 啟用；
候選與原始幾何保留在私人輸出目錄，不放入程式碼提交。
目前仍缺至少三個非共線的獨立世界座標參考，以及本圖動態障礙的失效／重建與實際繞行證據。
`live_movement_verified` 和 `can_send_packets` 維持 false，未開放 1275 自動行走。

本輪完整回歸 857 項：854 通過、3 項跳過；包含原有 13 場景及新增 12170 真實來源重建。
文件連結稽核與 `git diff --check` 通過。尚未執行遊戲內自動行走驗收。

## 程式端與離線驗收入口

`tools.navigation.acceptance` 逐一核對候選與幾何的雜湊、來源 Manifest／場景指紋、
官方參數映射、所有連通區的代表路徑，以及被動定位紀錄。
幾何或參數被修改、版本錯誤、可送封包旗標錯誤會拒絕；不覆寫既有報告。

```bash
python -m pip install -r requirements-navigation.txt
python -m tools.navigation.acceptance --geometry /private/M12170-candidates/12170_geometry.json --candidate /private/M12170-candidates/12170_candidate.json --evidence navigation_evidence_1275.json --scenes-zip "1275_差異/LaLa_1275_M12170_導航來源.zip" --output /private/M12170-offline-acceptance.json
```

12170 的官方參數映射為：角色高度 2 公尺、半徑 0.5 公尺、可跨高度 0.5 公尺、
最大坡度 30 度。候選對應參數一致；626 個面分為兩個連通區，各區代表路徑可求解。
這不保證兩區彼此可達，也不能證明所有可走表面都與官方掃描一致。
報告會單列未驗證的高度體素、區域面積、細節採樣及 Astar／Recast 演算法差異，
不把「參數一致」標為「掃描等價」。

原生 Recast 回歸另執行障礙加入／移除：從可直行的地面加入有高度的 BoxCollider，
重新掃描後必須改走較長繞路，移除後再次掃描須恢復原路徑。
這驗證離線重建的幾何效果，沒有接上未知的遊戲障礙封包或自動清除執行期 stale。

行走狀態機回歸覆蓋：角色／場景切換、戰鬥、事件阻擋、導航版本改變、障礙失效、
活動開始、隊伍跟隨、伺服器定位校正、主迴圈延遲，以及本機走完與伺服器定位的區分。
途中活動或隊伍改變現在會在下一次送出移動封包前停止。
只有 S3／S7／S12 定位符合目標才可確認位置，S6 目的地通知與本機路徑走完不算抵達。

公開 GitHub Actions 不再攜帶官方遊戲資源，只執行合成幾何、原生 Recast 及純 Python 防回退測試。
13 場景與 12170 的真實 Bundle 整合測試改由玩家在私人環境提供 `LALA_1275_*` 來源變數後執行；
缺少私有來源時，這些專屬整合案例會標示跳過，不能視為已重新驗證。Windows／macOS 仍執行純 Python 行走保護與驗收格式測試。

### 仍需實際資料才能關閉的驗收項目

| 項目 | 所需證據 |
| --- | --- |
| 官方掃描等價與幾何匯出精度 | 同版本官方引擎的掃描輸出／對照，核對輪廓、連通性與幾何位置 |
| 遊戲座標 | 同一地圖至少三個非共線的獨立世界座標參考，對應伺服器定位序號 |
| 執行期障礙 | 本圖真實障礙變更，舊路徑失效後的重建與繞行紀錄 |
| 伺服器行走 | 實際移動、校正、抵達及切圖紀錄；不能只用目的地通知 |

這些項目在離線報告中維持待驗。沒有遊戲連線或官方對照輸出時，
不虛構證據，不開放 1275 自動行走。本輪依使用者選擇先完成程式端與離線驗證。

本輪離線彙整：14 個模型、2,080 個候選面、19 個連通區，所有連通區代表路徑可求解。
完整回歸 868 項：865 通過、3 跳過；資源自檢、文件稽核與差異格式檢查通過。
這是本機驗證結果；尚未觀測推送後的 GitHub CI 執行結果。
