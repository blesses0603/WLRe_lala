# LaLa 通用資料格式 Adapter（v0.6.1 開發 PR）

## 與 #53 的責任分界

- `official_resource_sync` / `official_manifest_sync`：觀測官方版本並校驗完整 Manifest。
- `official_incremental_sync`：依審核過的精確 AssetPath／BundleName 規劃必要 Bundle，驗證下載與私有快取。
- **本 PR `wlre.services.world.catalog_adapters`**：在官方內容已獨立校驗並抽取出資料表或唯讀索引之後，以**明確審核的 Schema Adapter 與逐來源 SHA-256**解析內容，回傳不可直接啟用遊戲指令的結果。

本 PR 第二階段已新增使用 UnityPy 的 UnityFS／TextAsset 唯讀解包器與 Eve v115 衍生索引；**尚未取得真實官方 Bundle 驗收**。不把遊戲檔案搬入 GitHub、不自動下載全部 Bundle；原有 `runtime_1275` 與登入閘門保持不動。

## 版本無關，不等於未知格式自動支援

官方可能同時更動 NPC、商店、製作、場景，也可能只變更一包，或在同個數字版本重新發布 Manifest。因此每次解析必須有：

1. #53 驗證產生的完整 `catalog_key`，以及各 Package 獨立的完整版本識別碼。
2. 實際來源資料的**已審核** `SourceContract`，包含功能、資料來源名稱、來源所屬 Package、完整版本、Schema ID、精確 SHA-256。
3. 擷取後、大小受限的原始內容。重新計算 SHA-256 比對，且逐筆驗證 Schema、長度、索引與總數。

僅支援明確允許的格式：

| 功能 | Schema ID | 來源形式 | 注意 |
| --- | --- | --- | --- |
| NPC | `eve-npc-json-v1` | 已驗證 Eve `EventData.NewNpc` 衍生 JSON 索引 | 唯讀位置／事件資料；不是網路事件授權 |
| 商店 | `eve-interact-json-v1` | 已驗證 Eve `EventData.NewInteract` 衍生 JSON 索引 | 選項索引不等於售價或交易允許 |
| 製作 | `smith-new-33-v1` | `SmithData_C` 資料表 | 沿用現有 `parse_smith_1275`；格式相同仍需新版來源雜湊核准 |
| 場景 | `stage-new-76-v1` | `ScenesData_C` 資料表 | 沿用現有 `parse_stages`；沒有導航 Mesh／門傳送條件 |

格式不符、欄位改動、資料損毀、版號不一致或缺少任一功能來源會停止解析；**不猜測 1275 偏移可用於未來版本**。這些 Adapter 的名稱描述檔案格式，不是把 1275 當永久版本。

## 狀態與後續

`parse_feature` 回傳 `ParsedCatalog`，但 `can_send_packets=False`、`assets_ready=False` 固定不變；`parse_selected` 必須四個功能都完成才回傳，不做磁碟寫入或原子切換。這只是**解析階段**，不是正式遊戲相容驗收。

下一階段需要在真實官方 Bundle 上驗收已新增的 UnityFS／TextAsset 解包器與 Eve v115 解析，進而完成各功能業務關聯驗證、原子儲存個人 Catalog、GUI 預覽與正式服協定驗證。屆時再以 `OfficialCatalogIdentity.key` 設計安全切換，不會因解析成功而自行解除登入限制。

## 離線測試

```bash
python -m unittest tests.test_catalog_adapters -v
```

測試全為合成資料，沒有使用者帳密或官方遊戲資源。


## 第一階段新增：官方 Manifest → Bundle 定位 → Adapter（PR #56）

入口：`wlre.services.world.official_catalog_pipeline`

1. `plan_current_catalog` 即時讀取 `ResourcePath_PC.dat` 與兩包 `.version`，從官方 CDN 驗證 `.hash`／完整 `.bytes`，並呼叫 `identity_from_verified_manifests` 產生兩包獨立來源身分。
2. `AssetBinding` 明確指定每個功能的 `AssetPath`、格式 ID、資料衍生來源名稱、所屬 Package／完整版本與預先審核的 SHA-256。**不使用名稱子字串、索引順序或模糊搜尋**。最新版 Manifest 查無精確路徑就停止。
3. `build_update_plan` 解析所需 Bundle 與全部相依，確認本機快取／跨版重用；預設僅回報下載數量。顯式 `--download` 先檢查合計檔數與位元組配額，再透過官方同步服務下載並校驗 MD5／CRC。
4. 每個 `AssetBinding` 可以使用可選的 `related_asset_paths` 指定**同一功能必須同時取得的額外精確資源**。例如商店 `EventData.NewInteract` 的事件資料與 `ItemData_C` 商品基礎資料可能位於不同 Bundle；額外路徑亦需要在最新 Manifest 內逐項找到，否則停止。其所屬 Bundle 也會加入下載配額與 extractor 可見的已驗證路徑清單。
5. `run_catalog_pipeline(..., download=True, extractor=reviewed_extractor)` 在所有必要 Bundle 的快取內容再次驗證後，將根 Bundle／相依路徑交給**由維護者審核、實際能驗證 UnityFS 結構與資產身分**的 extractor。解析出的 bytes 再交給 `parse_feature` 做來源 SHA-256 與 Schema 校驗。四種功能都正確才返回結果。
6. CLI 未指定 `--parse` 時，**僅完成定位與 Bundle 校驗，不產生解析結果**。這並不代表失敗，而是不能跳過第二階段的 UnityFS/TextAsset 解包及衍生索引產製。

無論有無 extractor，都不會寫入遊戲目錄、不自動套用新版 NPC／商店／製作／場景資料，也不會把 `assets_ready`／`can_send_packets` 設為 True。

### 命令列（需先準備已審核的私人來源對應）

在 Git 工作樹**外**放置 `bindings.json`。Schema 格式如下；`<...>` 均是示意佔位符，**不是實際官方資源路徑或雜湊**：

```json
{
  "schema_version": 1,
  "sources": [
    {
      "feature": "npc",
      "asset_path": "<官方完整精確 AssetPath>",
      "related_asset_paths": [],
      "source_name": "EventData.NewNpc",
      "schema_id": "eve-npc-json-v1",
      "expected_sha256": "<已審核之衍生索引 SHA-256>",
      "package": "DataPackage",
      "package_version": "<從官方 DataPackage.version 取得的完整修訂>"
    }
  ]
}
```

此處僅顯示單筆格式；正式檔案**必須提供 npc／shops／crafting／scenes 四筆來源**，且每筆均須以當次官方 Manifest 與可信解包來源核對。完整來源欄位請參閱 `tools/plan_official_catalog.py`。

```powershell
py -m tools.plan_official_catalog --bindings "C:\path\outside\repo\bindings.json"
py -m tools.plan_official_catalog --bindings "C:\path\outside\repo\bindings.json" --download --max-mib 64 --max-files 32
```


若 `shops` 需要另外使用 `ItemData_C`，請在該筆設定的 `related_asset_paths` 明確加入 **當次官方 Manifest 中已驗證的完整 ItemData_C AssetPath**。列表可為空，但代表無附加來源，不應據此宣稱已取得完整價格或交易能力。

沒有已審核綁定檔時**不要猜造路徑或 SHA**，這兩個指令會安全拒絕。未指定 `--parse` 時，下載僅保存官方校驗過的 Bundle 於玩家私人快取；指定 `--download --parse` 才會使用 UnityPy 解包、驗證並回傳唯讀摘要。

### 驗證

```bash
python -m unittest tests.test_catalog_adapters tests.test_official_catalog_pipeline -v
```

CI 在 Windows、Ubuntu、macOS 執行完整回歸；合成資料測試不構成正式官方 Bundle 解包與遊戲登入／傳送驗收。

## 第二階段：UnityFS／TextAsset 與 Eve v115 唯讀解包

- `wlre.services.world.unity_textasset.extract_textasset`：使用 UnityPy 解析 UnityFS／SerializedFile，強制精確 AssetPath、TextAsset 類型／名稱、原始二進位與輸入大小限制。任何格式或來源不符皆拒絕。
- `wlre.services.world.eve_v115.derive_eve_index`：依 1262 官方 Lua 與 1275 Eve 場景 v115 已知佈局，將 `Eve.bytes` 二進位衍生為 NPC／互動選單唯讀 JSON；未知場景格式拒絕，且索引輸出必須通過來源 SHA-256。
- `wlre.services.world.catalog_source_extractor.extract_catalog_source`：將上述結果接到四種現有 Adapter；製作 `SmithData_C` 與場景 `ScenesData_C` 保留原始 TextAsset 二進位。
- `tools.plan_official_catalog --download --parse`：僅在顯式要求且經官方 Bundle 完整校驗時執行解析；輸出來源筆數摘要而非官方完整遊戲資料。未安裝 UnityPy 則安全停止。

安裝選用依賴及執行（私人 bindings 必須含當前官方來源完整修訂與已審核 SHA-256）：

```powershell
py -m pip install "UnityPy>=1.23,<2"
py -m tools.plan_official_catalog --bindings "C:\path\outside\repo\bindings.json" --download --parse --max-mib 64 --max-files 32
```

經使用者提供的 1275 Manifest 實際核對的精確 AssetPath：

| 類別 | AssetPath | Bundle |
| --- | --- | --- |
| NPC／互動事件 | `Assets/ResourcesBuild/Data/Eve.bytes` | `datapackage_data_e.bundle` |
| 商品物品基礎資料 | `Assets/ResourcesBuild/Data/ItemData_C.bytes` | `datapackage_data_i.bundle` |
| 製作 | `Assets/ResourcesBuild/Data/SmithData_C.bytes` | `datapackage_data_s.bundle` |
| 場景 | `Assets/ResourcesBuild/Data/ScenesData_C.bytes` | `datapackage_data_s.bundle` |

**雜湊契約：** 製作與場景是解包後原始 TextAsset SHA-256；NPC／商店是 Eve v115 衍生 JSON 的 SHA-256。均須由可靠實際來源計算、私人留存與人工複核，不要猜填 Hash。

**目前不能宣稱完成的事：** 本次持有 1275 Manifest，沒有實際官方 `datapackage_data_e/i/s.bundle`，所以 UnityPy 在真實 Bundle 上的成功解包仍未實測。`itemdata_v1.py` 已能依已知 Lua 格式解析 ItemData_C 物品名稱、基礎價格、售價、販售限制與開放狀態；商店指定 `related_asset_paths` 時會與 Eve 選單商品 ID 對照，缺少商品或未知格式即拒絕。**但尚未使用真實 1275 ItemData_C Bundle 驗證所有欄位與筆數，也不包含伺服器折扣／即時交易價格**。場景資料仍不含導航 Mesh／傳點判定，不能自動交易或行走。所有解析仍唯讀且 `assets_ready=False`。

UnityPy 讀取第三方資料時可能使用較大量記憶體；此實作已限制輸入／輸出大小，但尚未實作跨平台 CPU／記憶體沙箱，請只讀取官方驗證來源。

```bash
python -m unittest tests.test_unity_textasset tests.test_eve_v115 tests.test_catalog_source_extractor -v
```

補充：`tests/test_itemdata_v1.py` 驗證合成商品名稱、售價、交易限制、重複 ID、Unicode 與截斷資料拒絕；`tests/test_catalog_source_extractor.py` 驗證 Eve 商品 ID 與 ItemData 資料的離線關聯。解析結果仍只供查看，沒有任何交易指令。

## 第四階段：LaLa 自動處理官方資源（免手動 bindings.json）

**一般玩家不用建立 `C:\path\outside\repo\bindings.json`。** 原路徑只是舊版手動／開發者來源契約的示範，不是真正的 Windows 檔案。PR #56 現新增零設定的 `wlre.services.world.auto_catalog.run_auto_catalog`：

1. 由官方 `ResourcePath_PC.dat`、兩包 `.version` 及各自驗證過的 Manifest 判定獨立完整版本與 64 字元十六進位的 catalog key。
2. 按目前**已知、確切**的 `Assets/ResourcesBuild/Data/{Eve,ItemData_C,SmithData_C,ScenesData_C}.bytes` AssetPath 定位必要 Bundle 與全部相依。只支援可明確對上 Manifest 的既有路徑；未來改名或格式變更時，不模糊比對、不中途默認相容。
3. 在每次背景執行的總下載上限（預設 64 MiB／32 檔，含兩個 Package）內下載／重用 Bundle，逐個核對官方大小、MD5 與 CRC；校驗失敗則拒絕解析。
4. 使用 Nuitka 已隨附的 UnityPy 解包 TextAsset，依已審核的 Eve v115、ItemData、Smith、Scenes 格式產生四項來源索引，並通過資料形狀、長度與筆數檢查。SHA-256 在經過來源驗證後自動計算，**不需玩家自己提供 Hash**。
5. 所有四項成功才以 ZIP 格式寫入使用者私有資料夾 `LOCALAPPDATA\WLRE_LaLa\official_sync\derived_catalogs\<catalog_key>\candidate.zip`。ZIP 包含四項衍生來源與 `candidate.json`，有版號、來源雜湊、筆數與明確 `approved=false`。覆寫採同資料夾暫存、讀回驗證與原子替換，不寫 GitHub 或遊戲資源目錄。
6. **Launcher** 於啟動主程式前執行資源準備：原始碼版由 `wlre.launcher`（`run_client.bat`／`.command`）呼叫；Nuitka Windows／macOS 版由 `WLRE_Client.main` 直接呼叫同一 `launcher_catalog.prepare_on_launch`。將唯讀結果寫入 `LOCALAPPDATA/WLRE_LaLa/official_sync/launcher_catalog_status.json`，不依賴 Tk 與登入畫面下載。`VersionGateController` 僅讀取該狀態供展示，每次按「重新查詢官方版本」**不會重新下載 Bundle**。

開發者若要單獨檢查自動流程（無須 --bindings）：

```powershell
py -m tools.plan_official_catalog
py -m tools.plan_official_catalog --download --parse
```

一般使用者只需開啟已完成原生打包與驗收的 LaLa，**Launcher 在主畫面出現之前**核對、下載與解析候選資料，不需手動執行 PowerShell。原始碼版 Launcher 必要時在 `.ui-env` 私人虛擬環境中安裝固定的 UnityPy，避免安裝到系統 Python。離線／超額／新格式時候選準備失敗，但登入限制仍由登入前官方版本驗證獨立決定。舊版 `--bindings 私人檔案` 只保留專家相容用途。

**重要：** 此版本尚未在官方 1275 真實 Bundle 上完成端到端解包驗收。新版候選不等同於 LaLa 實際 NPC 互動、商店購買、製作封包與導航功能的相容確認；尚需官方格式及伺服器驗收，不能直接將 `assets_ready` 改為 True。

### Launcher 與主程式的職責界線

- `wlre/launcher.py`：原始碼版啟動環境／選擇 Python、啟動資源處理子程序，再啟動 LaLa Tk GUI。
- `WLRE_Client.py`：編譯版自身即啟動器，不依賴其他 Python；進入 GUI 前呼叫同一個資源服務。`--self-test`／`--smoke-test-gui` 不接觸官方 CDN。
- `wlre/services/world/launcher_catalog.py`：單一資源準備入口、私人只讀候選收據、錯誤隔離。收據不能授權遊戲登入或封包。
- `wlre/ui/version_gate_controller.py`：官方版本相容性與登入安全閘門，以及 Launcher 收據顯示，**不執行 Bundle 下載與解包**。
- **Launcher 進度畫面（PR #56）**：原始碼版 `wlre.launcher` 會啟動 `launcher_catalog --progress`，Nuitka EXE／APP 則在同一程序呼叫 `wlre.launcher_progress.run_with_progress(prepare_on_launch)`。使用既有 Tkinter，資源作業放在獨立執行緒，進度透過 Queue 在 GUI 主執行緒顯示；完成／失敗後自動關閉，才開啟 LaLa 正式主畫面。
- 進度事件由實際業務流程發出：官方版本、DataPackage／MainPackage Manifest、Bundle 定位、同步總量、**已完成 MD5／CRC 校驗的 Bundle 筆數／總數**、NPC／商店／製作／場景解包、候選 ZIP 寫入與快取命中。校驗單檔完成才增加計數，未估算下載速度或虛構百分比；下載時如果官方回應較慢，顯示不定進度條。
- **限制**：原始碼版首次安裝 Pillow／UnityPy 的 Python 私人環境屬進度畫面出現前的準備，CLI 仍會顯示簡短提示；大量下載須等待完成，暫不提供中途略過與可恢復的使用者中斷。官方 CDN 斷線時以不具授權效果的失敗結果繼續原有版本檢查；沒有螢幕的 Linux 環境以純文字階段訊息降級。正式 EXE／APP 與實際 Bundle 仍需個別驗收。
