# WLRe:LaLa｜1262 → 1275 全面資料遷移追蹤

> 2026-10-23。此表僅追蹤「LaLa 執行時會使用的資料」；不把 GitHub CI 或資源版本相符宣稱為正式服 E2E 成功。版本 v0.6.1 開發候選，未發布。

## 來源事實

- 官方遊戲 Manifest：DataPackage `1275_2026_10_21_18_27_33_84`；MainPackage `1275_2026_10_21_18_29_38_49`，遊戲程式版本 `1.3.0`。
- 本會話使用者提供的 `DataPackage_1275.zip`、`MainPackage_1275.zip` **各只含 .bytes / .hash 的 YooAsset Manifest**；未包含實體 1275 Bundle、Sprite、動畫或導航網格。
- 執行期完整資料另依賴本人提取、固定 SHA-256 的 `1275_DataCatalog.zip` 及 `1275_EveNpcIndex.zip`。程式不回退 1262；缺漏時禁止登入。
- 1275 的 DataCatalog 整合 160 張原始 DataPackage TextAsset；不是整份 MainPackage 的所有圖像或場景模型。

## 程式實際讀取來源清單

| 功能 | 1262 舊來源 | 1275 處理狀態 | 驗收界線 |
| --- | --- | --- | --- |
| 登入官方資源檢測 | `lala_supported_resources.json` | PR #51 已設定 1275 雙 Manifest；登入前檢查本機校驗資料 | 正式服登入待實測 |
| NPC／選項／商店 | `npc_*_1262.json.gz` | PR #51 依已校驗 1275 Eve、ItemData、TalkData 載入 | NPC 事件與商店交易封包待實測 |
| 共用物品名稱 | `combat_catalog.json` 名稱 | PR #52 從 1275 ItemData 載入；缺漏只顯示 ID | 物品物理屬性、Buff 不在此項 |
| NPC TextData／戰鬥台詞 | `npc_text_1262.json.gz`、`npc_battle_talk_1262.json.gz` | PR #52 從已校驗 1275 TextData 與 NpcTalkData_C 直接解碼 | 戰鬥觸發 E2E 待實測 |
| 製作目錄 | `crafting_catalog.json` | PR #51 改為 1275 SmithData 1,032 筆 | 真實 C64 排程／扣料待實測 |
| 地圖、場景名稱 | `map_names.json` | PR #52 由 1275 ScenesData_C／TextData_C 即時建立 | 地圖渲染／移動待實測 |
| 副本／協力唯讀目錄 | `instance_catalog_1262.json` | PR #52 從驗證的 1275 Dungeon、Cooperate、Scenes、TextData 重建 | 房間／副本封包 E2E 待實測 |
| 遠征目錄及 NPC 特徵 | `expedition_catalog.json` | PR #52 從驗證的 1275 Adventure、AdventureLv、NpcData、NpcCareer、TextData 重建 | 真實遠征派遣與領獎待實測 |
| 日常任務 | 舊版無完整自動模組 | `daily_task_1275.py` 僅提供 1275 唯讀解析 | 任務狀態／領獎協定未實測，不自動完成 |
| 技能／戰鬥／裝備屬性 | `combat_catalog.json`、`normal_attack_data.json` | **已接入**：1275 SkillData 1,593 筆、ItemData 11,304 筆與 NpcData 7,561 筆 NPC 五技能槽；**仍待**：一般攻擊及正式服 E2E | 1275 物品／NPC 靜態資料已改接，不代表封包、裝備效果已全數驗收 |
| 煉金與物品特殊規則 | `alchemy_catalog.json`、`item_stackable.json`、`combat_catalog.json` | **已接入**：1275 ItemData 完整欄位解析與煉金分類／材料／佔格校驗；**仍待**：根據 1275 `CanOverlap` 重建物品堆疊及其他特殊判斷 | 現有 `item_stackable.json` 仍為1262歷史來源，不可宣告1275堆疊已完成 |
| 傳送、導航與障礙 | `portals.json`、`stage_coordinates.json`、`graph_origins.json`、`navigation_data.zip` | 1275 門事件已唯讀解析，PR #51 已停用 1262 傳點目的地；**導航快取仍待重建** | 未經新版場景／導航證據，不開放新版遠距觸發 |
| 小地圖、圖示、視覺資產 | `smallmaps.zip`、`item_icons.zip`、`item_icon_map.json`、`wlre/resources/assets/` | **待處理**：必須取得 1275 完整 MainPackage Bundle 與原始素材後逐項對照 | 只有 Manifest 無法提取新版圖片 |
| 網路封包協定 | `wlre/network/` 各解析器／`wlre/services/` 各命令 | **待處理**：現有封包主要依據 1262 Lua，沒有把新版 Manifest 當成 1275 協定保證 | 正式伺服器端到端確認前不解除風險限制 |

## 嚴格轉換原則

1. **已確認跨版來源 SHA-256 相同**，才可以重用解析邏輯；這不代表自動重用舊版的 NPC／場景 ID、文字名稱或商品清單。
2. 原始表異動時，由 1275 已驗證 TextAsset 重新讀取，不以舊資料筆數或部分樣本推測。
3. 缺少實體 1275 Bundle 時，不以 1262 素材或路線改名為 1275；維持待處理／安全禁用狀態。
4. 不公開提交官方原始遊戲完整資源；只提交解析器、校驗器、測試及必要授權的應用程式程式碼。
5. 版本切換、CI 原始碼回歸、原生打包、正式服登入及各功能 E2E 是不同驗收層級。

## 2026-10-23 本機安裝路徑變更

使用者已將遊戲位置改為：

```text
D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo
```

此路徑由使用者確認，尚未在使用者 Windows 本機實際驗證。進行資源提取前，
可先用 PowerShell 檢查 `MainPackage`／`DataPackage` 是否存在：

```powershell
$yoo = 'D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo'
if (-not ((Test-Path -LiteralPath (Join-Path $yoo 'DataPackage\BundleFiles')) -and
           (Test-Path -LiteralPath (Join-Path $yoo 'MainPackage\BundleFiles')))) {
    throw '遊戲資源根目錄不存在或缺少 MainPackage／DataPackage，請核對遊戲安裝位置。'
}
Write-Host "已確認遊戲資源目錄：$yoo"
```

這只是 **1275 提取工具的輸入路徑**，不會修改遊戲內容；既有 1262
歷史檔案來源紀錄維持不變。

## 本機取得缺少的 1275 Bundle（不修改官方遊戲）

本 PR 新增 `tools/resources/inventory_1275_bundles.py`。請先確保遊戲已更新至
1275，並在 LaLa 專案目錄執行下列 PowerShell：

~~~powershell
py -m tools.resources.inventory_1275_bundles "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --output ".\lala_1275_local_inventory.zip"
~~~

預設只輸出資料夾階層、檔案大小、SHA-256、兩份 1275 Manifest 的本機備查壓縮檔，
**不會複製實體 Bundle，不會上傳，不會覆寫遊戲**。如需要完整重建新版圖片及
導航來源，可手動加上 `--archive`，此選項會將 MainPackage／DataPackage
所有 BundleFiles 的 `__data` 一起封存，壓縮檔可能非常大。
必須先檢查本機硬碟空間並確認遊戲檔案的使用授權；不應把整包官方內容提交到公開 GitHub。

此工具僅驗證本機檔案存在、路徑、大小與雜湊，不能代替官方 Manifest 內部資源對照解析，
也不能由本機 1275 Manifest 推論 1262 內容完全一致。

## 2026-10-23 使用者 1275 本機清單完成的雙版 Manifest 差異分析

已核對上傳的 `lala_1275_local_inventory.zip`：YooAsset 2.2.5、1275 兩份 Manifest
與先前提供的 1275 官方壓縮檔位元完全一致。清單 1,758 筆（Bundle 1,754、
Manifest／hash 共 4）；所有 1,754 個本機 Bundle 的哈希目錄名稱與檔案大小均
符合 1275 Manifest，未發現孤兒或缺檔。

另以 1262 的兩份原始 Manifest 比對 BundleName + FileHash，確認：

| Package | 1262 Bundle | 1275 Bundle | 變更 | 新增 | 不變 |
| --- | ---: | ---: | ---: | ---: | ---: |
| DataPackage | 22 | 22 | 15 | 0 | 7 |
| MainPackage | 1708 | 1732 | 20 | 24 | 1688 |

- 1262 到 1275 全部需優先提取的差異 **59 個 Bundle，合計 668,394,682 bytes（637.4 MiB）**。
- 建議四批處理：`data` 15 個／7.6 MiB；`scenes` 26 個／11.6 MiB；
  `ui` 2 個／28.9 MiB；`other` 16 個／589.3 MiB。
- MainPackage 資產記錄從 21,514 增加到 21,577，**新增 63 個**，
  包含 12 個 M13216～M13227 場景與新 Sprite、CG 等。
- **來源驗證界線**：新舊 Manifest 比對及本機清單交叉驗證完成，但沒有
  在此執行環境取得 59 個實體 Bundle bytes，不表示解碼／執行期相容完成。

本 PR 的同一個 `inventory_1275_bundles.py` 已支援依選取清單分批歸檔。
下載差異分析產出的 `LaLa_1275_差異選取清單.json`，放在 LaLa 專案根目錄，
先提取 `data` 這一批：

~~~powershell
py -m tools.resources.inventory_1275_bundles "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --select ".\LaLa_1275_差異選取清單.json" --group data --output ".\LaLa_1275_Data_差異Bundle.zip"
~~~

此選擇模式會再次核對兩份 Manifest 的 SHA-256，以及選中 Bundle 的大小與
內容 SHA-256；不符則拒絕歸檔。其他群組可將 `--group data` 改為
`scenes`、`ui`、`other`，輸出另取新檔名。
只封存本人合法取得的資料供個人分析，**不要把含官方遊戲 Bundle 的 ZIP 推送至公開 GitHub**。

## DataPackage 1275 原始資料與可安裝候選包（2026-10-23 更新）

使用者追加上傳的 `LaLa_1275_Data_差異Bundle.zip` 已直接逐檔驗證：
- 15／15 個原始 DataPackage UnityFS Bundle 的檔案大小和 SHA-256 與
  1275 本機清單一致；同包雙 Manifest 與官方 Manifest 來源吻合。
- 成功從所有 Bundle 解碼 **160 張 TextAsset**，原始資料表無重複名稱，
  Unity 序列化檔資料塊均以正確邊界切割。
- 已重新解析 1275 `ItemData_C` **11,304 筆**、
  `TextData_C` **39,947 筆**、`TalkData_C` **29,890 筆**。
  `SkillData_C` 有 **1,593 筆**固定 125-byte 技能資料，
  `SmithData_C` 有 **1,032 筆**固定 33-byte 配方。
- 從相同原始 `Eve` 逐場景解析 **1,262 場／10,975 NPC／1,634 個互動選單**；
  1,262 個場景的解析邊界均剩固定 44 bytes，對應 Lua 格式。
- 已重建與 LaLa 預期欄位相容的 `1275_DataCatalog.zip` 與
  `1275_EveNpcIndex.zip`，**官方原始資料只由使用者自行保存**，
  不上傳 GitHub，也不捏造新圖示或線上互動結果。
- 為保護之前已驗證的資源包，新增兩個**固定備選 SHA-256**，
  舊版釘選仍保留；只有來源 Manifest、索引雜湊與結構驗證均通過
  才可由 `runtime_1275` 載入。

第二份經驗證的 DataCatalog `manifest.json` SHA-256：
`1522aa78e158b7daba5593d44c5dcc44373bae1be950b65e93da1ac22584da1f`。

Eve 新索引 gzip：
- `npc_event_index_1275.json.gz`：111,933 bytes，
  SHA-256 `3bdd3a70a31dce4624b4f5704f9b0df9e1b82d24343eb7aae83e1763826896b1`
- `npc_interact_1275.json.gz`：20,061 bytes，
  SHA-256 `ec76150325ce24b8d5247b040025b1a20678722245e98c720ec9a470c4b6122e`

請在檢出本 PR 修補後的專案根目錄執行：

~~~powershell
py -m wlre.services.world.runtime_1275 ".\\1275_DataCatalog.zip" ".\\1275_EveNpcIndex.zip"
~~~

這會先以只讀模式驗證兩份包；若已完成手動備份且本機資料夾尚未
安裝同名檔案，可加上 `--install` 寫入使用者專用資料夾，絕不寫回官方
遊戲安裝路徑。不要把 zip 交由舊 main v0.6.0 的驗證器使用，
因為它尚未釘選本批重新產製的 Manifest 指紋。

在本機有兩份原始包的情況，可啟用額外整合測試：

~~~powershell
$env:LALA_1275_DATA_CATALOG = (Resolve-Path ".\\1275_DataCatalog.zip").Path
$env:LALA_1275_EVE_INDEX = (Resolve-Path ".\\1275_EveNpcIndex.zip").Path
py -m unittest tests.test_1275_reextracted_archives -v
~~~

已在分析環境完成原始 ZIP 解壓、逐檔 SHA 和資料表解析驗證。
**GitHub CI 與程式整合測試結果需分別回報**，不得據此宣告
1275 正式伺服器的戰鬥、交易、傳送等 E2E 成功。

## 1275 MainPackage 場景實體 Bundle 驗證（2026-10-23）

使用者已上傳 `LaLa_1275_Scenes_差異Bundle.zip`。以同批已驗證的
`LaLa_1275_差異選取清單.json` 與官方雙 Manifest 嚴格交叉核對：

- `scenes` 群組 **26／26 個 Bundle SHA-256、大小均匹配**；全部 UnityFS
  解壓與 Unity 2021.3.45f2 序列化物件表解析成功。
- 26 Bundle 對應 **13 組場景模型及相依資源**：既有變更 `12910`，
  新增 `13216`～`13227`。
- 全部物件統計：**460 個 GameObject、460 個 Transform、35 個 Mesh、
  89 個 Texture2D**；實際包含地形、碰撞器、材質、燈光和粒子物件。
- 以真正已校驗的 1275 `ScenesData_C`（1,337 筆／固定 76-byte）
  與 `TextData_C` 核對模型 ID／文字名稱，13／13 個場景均有對應。

| 場景模型 | 1275 官方文字名稱 | ScenesData_C `is_open` |
| --- | --- | --- |
| `12910` | 大腸 | `True` |
| `13216`～`13218` | 鬥獸場通道 | `False` |
| `13219` | 狩獵場 | `False` |
| `13220` | 地牢 | `False` |
| `13221`～`13227` | 地洞迷宮 | `False` |

**安全界線**：

1. `is_open=False` 是客戶端靜態資源表的旗標，不能推論伺服器
   活動是否已開放，更不能依素材存在就對封包發送傳送或尋路指令。
2. 目前 26 個場景 Bundle 含 Unity 幾何／貼圖，但尚無足夠證據
   重建 LaLa 的 `navigation_data.zip`、`graph_origins.json`、
   `stage_coordinates.json` 等 1275 導航座標。必須保留
   `coordinates.py` 的 1275 自動導航禁止回退機制。
3. `12910` 是已存在場景的修改，但未取得 1262 對應實體 Bundle，
   尚不能宣稱場景座標、碰撞或模型沒有改變。
4. 場景提取檢查屬離線來源級驗證；Windows 版正式遊戲傳送、視覺顯示及
   官方伺服器端到端行為均尚未驗收。

實體 Unity Bundle 與完整 GameObject 清單不提交 GitHub。
使用者可保存獨立分析產物 `LaLa_1275_Scenes_場景分析與索引.zip`
（Markdown、CSV、JSON，僅索引不包含官方材質及模型 bytes）。

下一批建議提取 2 個 `ui` 類 Bundle（使用已更新的遊戲路徑）：

~~~powershell
py -m tools.resources.inventory_1275_bundles "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --select ".\LaLa_1275_差異選取清單.json" --group ui --output ".\LaLa_1275_UI_差異Bundle.zip"
~~~

本 PR 的真實資料可選整合測試另外核對 12910 `is_open=True`、
新增 12 場 `is_open=False`，避免未來誤開放新場景。

## 1275 UI 來源驗證與一次打包全部剩餘差異（2026-10-23）

使用者已提供 `LaLa_1275_UI_差異Bundle.zip`：
- 2/2 個 MainPackage UI Bundle 的長度與 SHA-256 均符合雙版差異選取清單；
  原始兩份 1275 Manifest SHA-256 一致，ZIP 無 CRC 錯誤。
- UnityFS 成功解壓兩包；一包內含 4,349 Texture2D 與 4,349 Sprite
  物件，另一包至少含材質／圖像序列化資料。
- 此為來源／素材可用性驗證，不能直接當作已替換 LaLa 的物品圖示快取，
  仍需逐項 ID／Sprite 索引核對。

此處記錄提取階段進度：當時先取得 43 個（Data 15、Scenes 26、UI 2）。
**目前其他 16 個也已由使用者提供且全數通過驗證；最新結果見下節。**

為避免逐批手動執行，清點工具擴充 `--split-mib` 選項，可在一次執行中：
1. 根據選取清單確認官方雙 Manifest SHA-256；
2. SHA-256 核對所選全部 Bundle；
3. 依單卷最大容量產生多個可獨立開啟的 `.partNN.zip`；
4. 每卷內含完整 `inventory.json`、兩份官方 Manifest，
   及 `selection_part.json` 明確列出此卷的 Bundle 路徑。
   完成前再次核對卷內原始 Bundle SHA-256，出錯刪除這次建立的分卷。

**只補剩下 16 個：**

~~~powershell
py -m tools.resources.inventory_1275_bundles "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --select ".\LaLa_1275_差異選取清單.json" --group other --split-mib 256 --output ".\LaLa_1275_剩餘全部差異.zip"
~~~

**若真的想重新擷取全部 59 個差異 Bundle（含已上傳的 43 個）：**

~~~powershell
py -m tools.resources.inventory_1275_bundles "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --select ".\LaLa_1275_差異選取清單.json" --split-mib 256 --output ".\LaLa_1275_全部差異.zip"
~~~

**如需全部 1,754 個 Bundle** 可用原有 `--archive`，但會產出約
2.63 GB 以上的 ZIP（含 Manifest），並不建議為本次差異分析使用。
分卷只是單次產生多份 ZIP，適合在有單檔大小限制的環境中一併上傳；
請不要提交官方遊戲 bytes 到公開 GitHub。操作前檢查本機可用磁碟空間，
如果 `.partNN.zip` 已存在，工具會拒絕覆寫。

## 1275 全部 59 個差異 Bundle 已收齊（2026-10-23）

使用者依 `--select ... --group other --split-mib 256` 上傳四卷
`LaLa_1275_剩餘全部差異.part01.zip`～`.part04.zip`。

- 本次分卷依序包含 **1、2、9、4 個 Bundle**，共 **16／16 個**；
  每卷的 `selection_part.json`、雙 Manifest、`inventory.json`
  一致；16 個檔案逐一以預先固定的 SHA-256 和 size 交叉比對，
  **無缺失、重複、雜湊錯誤**。
- 16 個 UnityFS 全部解壓成功，Unity SerializedFile 物件索引全部解析
  成功；合計 **299,634 個序列化物件**，其中包含 6,769 個 Texture2D、
  3,116 個 Sprite、2,415 個 Mesh、4,923 個 Material
  （物件數包含模型骨架／動畫元件，不等於不同可玩物件）。
- 實際內容為：`mainpackage_atlas`、`cg2d`、`material`、
  `model_10_npc`、`model_10_npc_static`、`model_11_npc`、
  `model_11_npc_static`、`model_animator`、`model_house`、
  `particle`、`particle_pa_dependency`、`texture_a`、
  `texture_l`、`texture_r`、`texture_s`、`timeline`。
- 加上先前 DataPackage 15、Scenes 26、UI 2，現在共
  **59／59 個差異 Bundle，668,394,682 bytes，全部取得並完成原始內容驗證**。
  本次驗證覆蓋的是雙 Manifest **1262 與 1275 之間有變動的 Bundle**，
  不包含未變動的 1,695 個 Package Bundle 重新下載作業。

### 實際資產交叉對照

對 Other 16 與 UI 2 個變更 Bundle 逐項解析名稱索引：

- `mainpackage_assets_resourcesbuild_sprite_sprite_item.bundle`
  包含 4,349 個 Texture2D 與 4,349 個 Sprite；
  `s4253`～`s4266` 及 `s9937` 這 **15 個新增物品圖示**
  在兩種 Unity 類別均有同名物件。
- `mainpackage_texture_s.bundle` 提取到 **550 個 `SmallMap2D_*` 名稱**，
  `SmallMap2D_12910` 存在；找不到
  `SmallMap2D_13216`～`SmallMap2D_13227`。僅能判斷這批新版
  Texture_S 中沒有同名資產，**不能推論其他未變動 Bundle 或遊戲全部位置都沒有**。
- 63 個 MainPackage 新增資產路徑中：**12 個場景在 Scenes 類已確認**；
  另外 **47 個非場景資產**由這批 18 Bundle 的 Unity 物件名稱找到對應；
  **4 個 Timeline .playable** 只完成 Manifest 層驗證，
  尚未對 MonoBehaviour 內部物件逐一建立名稱／路徑關聯。

使用者可保存獨立分析產物 `LaLa_1275_全差異_驗證與素材索引.zip`
（Markdown、CSV、JSON，**不含任何原始 Unity Texture/Mesh/Bundle bytes**）。
這些大型官方遊戲內容不上傳公開 GitHub。

**重要**：來源齊全 ≠ LaLa 執行期已完成 1275 切換。
`item_icons.zip`、`smallmaps.zip`、`navigation_data.zip` 等舊資料
仍需重建或安全停用；技能封包、NPC 真實交易、製作、地圖傳送、戰鬥
及 Windows 正式遊戲 E2E 均不得因靜態資源齊全就宣告通過。

## PR #52｜1275 正式共用物品、NPC 戰鬥資料接入（2026-10-23）

本輪直接修改可執行程式而非僅更改資源版本號：

- 新增 `wlre/services/items/itemdata_1275.py`，依已取得的 1262
  `Lua/Data/ItemData.lua::ItemData.New` 二進位欄位順序**完整解碼1275**
  `ItemData_C`。與 1275 DataCatalog 既有 11,304 筆商店唯讀索引
  **逐筆交叉檢查**物品名稱、價錢、限制、開放旗標等六個共同欄位。
- 戰鬥裝備、藥水回復、物品特殊狀態、屬性、`skill_link`、
  `fit_type`、圖示 ID 與煉金材料 `spares`、材質、佔格數量
  改從 **同一份完整1275來源**建構。
- `ItemData_C` 實測 11,304 筆全數解析至資料尾部，截斷／尾端
  多餘位元組皆會拒絕；8 件官方測試用物品的 `width=height=0`
  保留於物品定義，計算煉金可用空間時則保守視為 1x1。
- `NpcData_C` 依 `Lua/Data/NpcData.lua::NpcData.New` 既定欄位
  加入 NPC 原名稱與五個 `UInt16` 技能槽。使用者提供的1275原表
  確認 **7,561 筆 NPC，資料尾部無剩餘**；艾琳14230的技能
  `[25033,11172,0,0,0]`。
- `runtime_1275.ready()` 在載入已釘選的 DataCatalog/Eve ZIP 後，
  依序把新版配方、技能、完整物品／煉金、NPC 來源寫入共用字典。
  **原地更新字典**確保 UI 與已匯入該字典的戰鬥程式不保留舊物件參照；
  若任何後續索引啟用失敗，配方、技能、技能 Key、物品、NPC 及煉金
  共六個共享字典會**一併原地回復**，並拒絕登入。
- 新增 `test_itemdata_1275.py`、`test_npc_skills_1275.py` 與
  真實官方檔案的可選整合測試，驗證解析邊界、資料來源防回退、
  異常資料不應修改現有快取。

**尚未完成（不宣稱全面 1275 相容）**：1275 堆疊判定
`ItemData.CanOverlap` 涉及多種 Lua 特殊判斷，現有
`wlre/resources/item_stackable.json` 為1262來源。雖然已驗證全版
1275 `ItemData_C`，但尚未逐一重現 `CanOverlap` 的完整規則，
不得無根據地改名或推定新版物品是否可堆疊。
`item_icons.zip`／`smallmaps.zip` 的實際圖片快取仍需由原版素材合法
提取並重建；`normal_attack_data.json`、真實技能封包、
NPC 買賣、導航、戰鬥與製作仍需遊戲客戶端及伺服器 E2E 驗收。

## 同步整合 1275 堆疊、圖示、小地圖（2026-10-23）

### 正式背包堆疊判定

- `stackable_1275.py` 對照使用者提供 `Lua/Data/ItemData.lua` 的
  `ItemData.CanOverlap` 與所有呼叫之輔助判定，依 **1275 全部 11,304 筆**
  `ItemData_C` 完整欄位重建 Stackable，並原地更新
  `wlre.core.inventory_updates.STACKABLE`，現有
  背包與遠征模組的共用參照不失效。
- 特殊排除：fitType=10、裝備 fitType 1～6 或 11、交通工具 kind 39／58、
  轉蛋類 fitType=9、限時／賽季裝備、HP／SP 特殊補瓶、
  多次使用修復道具、紋章類及六個官方指定 ID。
- `runtime_1275.ready()` 會把七個共用字典
  （製作、技能、技能鍵、物品、NPC、煉金、堆疊）**一起校驗切換**，
  任一失敗就原地恢復全部，禁止局部版本混用。
- 此次使用的是 1262 版已驗證的 `CanOverlap` Lua 程式與**真正1275物品資料**；
  若官方修改了未取得的 1275 Lua，仍需以實機行為校驗，
  不能聲稱伺服器已確認所有堆疊行為。

### UI 圖示與小地圖私人快取

- 新增 `tools/resources/export_1275_visuals.py`，只讀入使用者自己的
  1275 資源 ZIP，以固定的官方 Bundle SHA-256 核對來源。
  匯出工具需要 **本機安裝 UnityPy 與 Pillow**，僅在執行命令時載入。
- `--kind icons`：從 `sprite_sprite_item` Bundle 讀取新版
  `Sprite`，按 `s<icon_id>.png` 產生 `item_icons_1275.zip`，
  包含 15 個已確認新增 Sprite 的覆蓋檢查。UI 依
  `ItemData_C.icon_id` 找新版圖示，不套用1262 `item_icon_map.json`。
- `--kind smallmaps`：從 `texture_s` Bundle 讀取新版
  `SmallMap2D_*.png`，產生 `smallmaps_1275.zip` 與對應 index。
  依新版 ScenesData 模型 ID 查找靜態圖片，
  **不解除** `coordinates.py` 的1275座標／導航安全鎖。
- 兩種輸出均保存於**使用者私人資料夾**的 `official_resources_1275`，
  不把官方圖片或 Bundle 上傳公開 GitHub；若私人快取缺漏，
  介面顯示空圖，不會拿1262圖片冒充新版。
- 圖片來源 SHA／ZIP 內容 SHA 和必要名稱檢查可在執行期核對。
  **注意：由本地產生的 manifest 無法獨立證明所有像素內容等同原始遊戲，
  仍需在真正 UnityPy 圖像匯出後逐張抽驗。**

在已切換至最新 PR #52 且檔案位於專案根目錄的 PowerShell：

~~~powershell
py -m pip install UnityPy Pillow

py -m tools.resources.export_1275_visuals --kind icons --select ".\LaLa_1275_差異選取清單.json" --archives ".\LaLa_1275_UI_差異Bundle.zip" --install

py -m tools.resources.export_1275_visuals --kind smallmaps --select ".\LaLa_1275_差異選取清單.json" --archives ".\LaLa_1275_剩餘全部差異.part01.zip" ".\LaLa_1275_剩餘全部差異.part02.zip" ".\LaLa_1275_剩餘全部差異.part03.zip" ".\LaLa_1275_剩餘全部差異.part04.zip" --install
~~~

**此匯出工具尚未在使用者的 Windows／UnityPy 實際環境執行**，
因此目前僅能標示原始 Bundle 指紋來源已確認、應用程式
讀取及驗證支援已提交，不得宣稱 4,349 個 Sprite、550 張小地圖
已成功轉出為可顯示 PNG。若遇解碼／格式差異，應以實際錯誤日誌修正。

## 1275 地圖導航重建第一階段：官方坐標、傳點拓樸與路線查詢（2026-10-24）

這一階段優先於 NPC 買賣和每日任務執行，從**使用者原始 1275 DataCatalog**
直接解碼而非重用 1262 `portals.json`／`stage_coordinates.json`／`navigation_data.zip`：

- `ScenesData_C`：**1,337 筆**，保留每張圖真正 `map_width`、
  `map_height`、`pos_x_ratio`、`pos_y_ratio`、
  `small_offset_x/y` 和官方開放旗標；其中 **330 張**靜態標記為未開放。
- `StageMapData_C`：**4,092 筆** 18-byte 標記；其中
  kind 0 / 1 / 2 / 3 / 4 / 5 數量依序為
  **252 / 1,817 / 1,860 / 137 / 22 / 4**。
- `DoorLinkData_C`：**85 筆**原始 12-byte 門連結，含起／終點場景與座標。
- `EveDoorLinks`：完整 UTF-16 逐行嚴格解碼出 **1,108 個場景段、
  2,374 條連結**；8 條涉及目前 ScenesData 未列的來源或目的地，
  在路線規劃中不使用。
- `topology_1275.py` 建立只讀場景圖。新增 BFS 跨圖途徑**參考查詢**，
  排除官方靜態未開放場景與未知連結。以官方來源確認範例
  `10000 -> 12050` 可找到單步連結。
- 主頁「傳點」欄改用1275官方連結顯示**唯讀目的地名稱**；
  所有標記的 `direct_eligible=False`、`can_send_packets=False`，
  `portal_policy` 強制拒絕1275直接觸發或自動走向門。
- `packet_to_world_xz` 與反算公式遵循 Lua `Stage.TransferPosition`，
  使用新版 StageData 的地圖高度。這只證明本機座標公式，
  **沒有證明舊 A* Graph 原點／網格，亦不是正式伺服器封包授權**。

### 可立即執行的唯讀查詢

~~~powershell
py -m tools.resources.preview_1275_routes ".\1275_DataCatalog.zip" ".\1275_EveNpcIndex.zip" --from-stage 10000 --to-stage 12050

py -m tools.resources.preview_1275_routes ".\1275_DataCatalog.zip" ".\1275_EveNpcIndex.zip" --scene 12910
~~~

### 恢復自動移動前仍需要驗證的原始導航來源

既有 1262 的 `navigation_data.zip` 含 724 張 A* 離線三角面網格，
但無法由 ScenesData 的座標／渲染 Mesh 推論1275 **可行走網格**。
目前使用者提供的59個差異 Bundle 不包含可獨立確認的新版 A*
Graph／原點資料。舊版圖不會改名成1275再直接啟用。

PR 新增唯讀原始來源提取工具：核對本機1275雙 Manifest 存在，
複製同一官方安裝版本的 `resources.assets`、`resources.resource`
並於輸出 ZIP 之前及之後核對 SHA-256。先與原始1262對應檔比較，
再確認 A* Graph 有無修改。其存在**不保證**一定含可解碼的 A*：

~~~powershell
py -m tools.resources.collect_1275_nav_source "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --check-only

py -m tools.resources.collect_1275_nav_source "D:\Program Files\wl_re\飄流幻境Re_星之方舟_Data\yoo" --output ".\LaLa_1275_導航原始來源.zip"
~~~

來源可以留在使用者本機，不提交公開 GitHub。後續仍須驗證：
1275 A* 三角面、Graph 原點、連接性、動態障礙、同位置不同高度、
玩家與伺服器位置校正、傳點 `Eve` 門索引到目的地的關聯、
地圖載入回覆與失敗重試安全條件。**這些驗證完成前，1275 自動移動及傳送仍停用**。

## 1275 Unity 全域資源實體比對（2026-10-24）

已收到 `LaLa_1275_導航原始來源.zip`，逐檔 CRC、長度、SHA-256 與
官方 1275 雙 Manifest 固定指紋核對，再與先前
`resources_1262.zip` 的原始 bytes 獨立比較：

| 檔案 | 1262 / 1275 大小 | 雙版本 SHA-256 | 結果 |
| --- | ---: | --- | --- |
| `resources.assets` | 2,387,392 | `e288bb3ea097419d2f43ca365f9a2d8448d00fe8133234148d9b9df8b0ff9b31` | 原始 bytes 完全相同 |
| `resources.resource` | 41,851,633 | `f027b06db3e838030905721ee2f87072d9b5d08795429faa2ca4121fe5ce3104` | 原始 bytes 完全相同 |

`resources.resource` 以 `FSB5` 開頭，屬音效資料格式；
`resources.assets` 含 Unity 字型、介面與共享資源。
**沒有從這批檔案解出並驗證能對應 724 張舊導航快取的 A* Graph。**
因此前節所稱的「從這兩份檔案取得新版導航原始來源」只能理解成
**全域 Unity 資源的比對**，不能據此宣告 1262
`navigation_data.zip` 與 1275 相容，更不能開放傳送。

新增 `tools/resources/audit_1275_nav_sources.py` 和
`tests/test_audit_1275_nav_sources.py`，核對雙官方 Manifest、大小、
SHA、同版本來源一致性與 FSB5 檔頭；
不論兩份檔案是否相同，回報都會明確
`astar_graphs_extracted=False`、
`navmesh_verified=False`、`auto_movement_authorized=False`。

可在保有兩份原始 ZIP 的本機重現比對：

~~~powershell
py -m tools.resources.audit_1275_nav_sources ".\resources_1262.zip" ".\LaLa_1275_導航原始來源.zip"
~~~

### 下一步需要的 A* 原始證據

優先追溯舊 `navigation_data.zip`（724 個場景快取）究竟從哪個
Scene Bundle、AstarPath/MonoBehaviour、序列化 Tile/Graph
或離線匯出工具生成，再從相應的1275場景原始檔重建。
官方 1275 的 `mainpackage_scene_12910` 及12個新場景
`13216`～`13227` 等變動場景素材已上傳，但渲染 Mesh
不能直接替代 A* 導航網格，必須檢查 Graph 原點、點邊、
跨高度與動態障礙定義。

**結論：導航來源追溯與 1275 A* Mesh 重建仍未完成**。
現有1275 Stage、門連結及座標均維持唯讀，正式服
自動移動、地圖點擊、直接傳點均保留安全鎖。


### 從官方1275變動場景真正解碼到 AstarPath Recast 設定（2026-10-24）

此次使用者上傳的新 `resources.assets`／`resources.resource` 雖然
與1262完全相同，但在先前**已提供的**
`LaLa_1275_Scenes_差異Bundle.zip` 裡有另一個真正可追蹤的來源：

- **13／13 個變動場景主 Bundle**（12910 與13216～13227），經 SHA-256
  核對後逐一解開 UnityFS 與 Unity SerializedFile v22。
- 13／13 個場景均有 `MonoScript AstarPath`，並在 MonoBehaviour
  的 Base64 字串內解到有效 ZIP。
- 每包都只有 `graph0.json`、`meta.json`；實際
  `meta.json` 內的版本 `4.3.60` **不是標準 JSON 數字**，
  工具只針對版本字串正規化後解析，
  `typeNames=["Pathfinding.RecastGraph"]`、`graphs=1` 均確認。
- `graph0.json` 含 `cellSize`、`characterRadius`、
  `walkableHeight`、`walkableClimb`、`maxSlope`、
  `forcedBoundsCenter`、`forcedBoundsSize` 等
  **真正的 Recast 掃描參數**；13場均 `rasterizeColliders=true`，
  12910 `rasterizeTerrain=false`，其餘12場為 `true`。
- **這是設定，不是已掃描的三角面／Tile/可行走節點。**
  Recast Graph 需要重建地形與碰撞器掃描輸入，不能把設定存在
  誤解成 `navigation_data.zip` 已完成1275重建。

已新增唯讀提取器 `tools/resources/extract_1275_recast_settings.py`
與合成資料單元測試；有上述13組原始場景 ZIP 時可啟用可選真實測試。
在保有原始資料的私有電腦執行：

~~~powershell
py -m pip install lz4
py -m tools.resources.extract_1275_recast_settings --scenes-zip ".\LaLa_1275_Scenes_差異Bundle.zip" --select ".\LaLa_1275_差異選取清單.json" --output ".\1275_AstarPath_13場景設定索引.json"
~~~

獨立報告 `LaLa_1275_Astar導航設定提取報告.zip`
包含13組設定及來源SHA索引，但不含原始遊戲Bundle。
下一步需要 1275 地形／碰撞器幾何輸入、Recast掃描產物及
遊戲內位置校驗，才能真正復原行走；現在維持 **禁止發送移動與C20-8傳送**。

## 1275 可行走網格來源：26個場景 Bundle 碰撞器／地形物件盤點（2026-10-24）

直接讀取使用者已提供的 `LaLa_1275_Scenes_差異Bundle.zip`，
逐一比對 `LaLa_1275_差異選取清單.json` 預先固定的每檔 SHA-256、
長度、ZIP CRC，解壓26個UnityFS、解析 Unity SerializedFile v22
物件表。**26/26成功，13組 Scene + Dependency Bundle 均齊全**。

| 掃描輸入 | Unity物件數 |
| --- | ---: |
| `Mesh` | 35 |
| `TerrainData` | 10 |
| `Terrain` | 10 |
| `MeshCollider` | 3 |
| `BoxCollider` | 3 |
| `MeshFilter` | 315 |
| `ParticleSystem` | 35 |
| 全部類別物件合計 | 2,277 |

本次新增 `tools/resources/audit_1275_scene_collision.py` 來源解析器，
嚴格核對所有主場景與Dependency Bundle均只出現一次，
輸出各場景碰撞器／地形候選來源的唯讀報表，
但**不將任一原始 Mesh 或 TerrainData 假定為可行走三角面**。
新增 `tests/test_audit_1275_scene_collision.py`：
損壞SerializedFile或缺件時拒絕，僅在測試環境提供真正原始場景 ZIP
時跑全量來源級整合測試。

~~~powershell
py -m pip install lz4
py -m tools.resources.audit_1275_scene_collision --scenes-zip ".\LaLa_1275_Scenes_差異Bundle.zip" --select ".\LaLa_1275_差異選取清單.json" --output ".\1275_場景碰撞來源盤點.json"
~~~

**重要結論**：現在已追溯出新版 Recast Scan 的地形／Collider 類別候選。
但Unity Scene存在 `MeshFilter` 不代表該物件可行走，且Recast設定
`rasterizeMeshes=false`，真正輸入取決於 `rasterizeColliders`、
`rasterizeTerrain`、對應 `Layer mask`、物件Transform與啟用狀態。
目前未完成可重現的地形高度圖解碼、Collider Mesh變換、
Recast voxelization／侵蝕／坡度／障礙判定及三角面連通性。
**1275 可行走三角網格重建：未完成；
1275 自動行走／傳送：保持停用。**
下一步應先針對有 TerrainData 的場景重建掃描輸入，
再做多高度、障礙物與原始伺服器位置回覆驗證。
原始遊戲材質與碰撞Mesh皆不得提交公開GitHub。

## 下一批所需來源

- **1275 MainPackage 差異 Bundle 已全數取得**：44／44 個已核對實體 SHA-256 與 UnityFS；後續重點是各項素材的 1275 圖片轉換、地圖座標與 LaLa 舊快取整合，不必重複蒐集差異 ZIP。
- **1275 戰鬥、技能、煉金、特殊裝備的原始表校驗**：現有 DataCatalog 可作為來源，但需開發對應的完整欄位資料轉換及新舊差異測試。
- **1275 正式遊戲封包實測**：登入、NPC、S23／S26／S27 交易、C64/S64 製作、傳送、戰鬥與各副本狀態。

## 自動化與人工驗收

```powershell
py -m unittest discover -s tests -q
py WLRE_Client.py --self-test
py WLRE_Client.py --smoke-test-gui
py -m tools.build.build_nuitka --dry-run
```

上述指令需在原始碼完整且依賴已安裝的環境執行；未經實際完成不得標示通過。正式服副作用功能不得以離線驗證代替。

## PR #52 收尾檢查（2026-10-24）

這次檢查以本 PR 的 1275 資料遷移、唯讀拓樸及 Recast 設定解析為範圍，
沒有開放尚未驗證的行走、傳送或交易，也沒有建立安裝包／Release。

已修正與新增驗證：

- 未安裝私人 1275 圖示時，補給／戰後維護設定頁改用可重複呼叫的
  `ItemIcons.close()`；關閉頁面不再對 `None` 呼叫 ZIP `close()`。
  GUI 冒煙檢查會把銷毀控制項時的 callback 例外視為失敗，
  不再只檢查畫面建立階段。
- 私人圖像 ZIP 同時驗證來源／每張 SHA-256、PNG 格式、尺寸及實際像素解碼。
  小地圖 `name` 必須與 PNG `entry` 一致，模型 ID 不可重複；
  錯誤的 Manifest／索引以一致的 `VisualResourceError` 回報。
- 1275 雙資料包複製到暫存檔後再次驗證，通過才發布到目標檔名；
  失敗清理暫存檔。安裝成功會清除 runtime、地圖名稱、副本與商店快取，
  避免安裝前的空目錄繼續遮蔽新版資料。
- Recast MonoBehaviour 與碰撞物件盤點改共用 SerializedFile v22 讀取器。
  metadata 長度以 48-byte 表頭之後為起點；物件表不得越界讀取資料區，
  並拒絕重複 path ID、錯誤 endian 及越界 payload。

驗證結果與限制：

- 完整本地測試：812 項，807 通過、5 項跳過；沒有 Tk callback 例外。
  `--self-test`、`--smoke-test-gui` 與 `tools.audit_repository --strict-git` 通過。
- PR #52 前一輪收尾時，雲端尚未取得 PR 先前使用的 1275 原始場景 ZIP、選取清單及完整資料包，
  因此新增的解析器邊界回歸使用合成資料；沒有重新宣稱 26 個真實場景已通過新版讀取器。
- Windows／macOS CI 與正式服 E2E 須另行確認；本地 Linux 結果不可替代。
- 1275 Terrain 高度圖／Collider Transform／Recast 掃描與可行走三角網格
  仍未重建，導航與直接傳送繼續停用。

## 可行走網格重建工具（2026-10-24）

新增固定 Recast v1.6.0 原始碼的編譯與真實掃描流程、Unity Collider／Terrain 私人匯出 helper、來源指紋比對與離線尋路。合成場景已驗證坡度、半徑侵蝕、淨高與跨高度不誤連；沒有取得真實 1275 場景檔，因此沒有宣稱重建官方網格或解除導航限制。完整操作與缺口見 [1275 網格重建](NAVMESH_1275_REBUILD.md)。

### 場景來源重新取得後的進度（2026-10-24）

開發階段曾以私人本機 `1275_差異/` 的重建 ZIP 與選取清單核對 26 檔及 13 份設定；ZIP 不再留在公開 PR 歷史。修復 UnityFS v8 對齊相容性後，直接由場景物件、Transform、Collider 及 Terrain 高度重建 13216～13227 共 12 份離線候選，均驗證連通區可尋路。12910 缺 `unity default resources` 中的原始 Mesh，保持阻擋。候選設定尚未證明等價於官方 Astar 掃描，動態障礙與正式服座標未驗證，導航仍不解禁。詳見 [實際重建結果](NAVMESH_1275_REBUILD.md#重建-zip-的實際結果)。

### Unity 內建 Mesh 補齊（2026-10-24）

已取得並固定 `unity default resources` 的來源 SHA，解出 12910 所指向的 Plane 原始 Mesh，完成第 13 份離線候選。解析器不再自行搜尋附近資源，僅接受已註冊來源。13 場候選均可離線尋路，仍保留官方 Astar 設定等價與正式服驗收界線；沒有啟用遊戲移動。

### 實機定位與障礙紀錄入口（2026-10-24）

新增記憶體內有界自身導航紀錄與使用者明確匯出入口，另附座標獨立參考／障礙失效檢查工具。定位與目的地通知分開，障礙失效與幾何重建分開；缺正式服證據時不解禁移動。操作見 [實機驗證紀錄](NAVMESH_1275_REBUILD.md#遊戲內座標與動態障礙驗證紀錄)。

### 已上傳實機紀錄的缺口（2026-10-24）

目前定位發生於 12170，只有一筆 S3-1，另有不影響本圖的家具快照；沒有獨立座標參考或本圖障礙變更。12170 不屬於 13 個差異場景，新增固定 Manifest 驗證的單場景 pair 提取工具，可不依賴舊差異清單取得正確來源；不將這份紀錄標示為實機驗收通過。指令見 [目前地圖來源補齊](NAVMESH_1275_REBUILD.md#目前登入地圖-12170-的來源補齊)。


### 官方啟動掃描快取的補查修正

先前「只有設定」的觀察僅涵蓋 AstarPath 的 `dataString`。最新沿 `file_cachedStartup`
取得 dependency Bundle 中的 14 份官方 TextAsset，已包含掃描後的三角面及節點資料。
14 份設定與場景相符；12170 官方快取為 214 面，目前候選為 626 面，尚不能宣稱等價。
詳見 [來源、解碼與逐項比較](OFFICIAL_NAVIGATION_CACHE_1275.md)。
