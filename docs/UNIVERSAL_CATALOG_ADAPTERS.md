# LaLa 通用資料格式 Adapter（v0.6.1 開發 PR）

## 與 #53 的責任分界

- `official_resource_sync` / `official_manifest_sync`：觀測官方版本並校驗完整 Manifest。
- `official_incremental_sync`：依審核過的精確 AssetPath／BundleName 規劃必要 Bundle，驗證下載與私有快取。
- **本 PR `wlre.services.world.catalog_adapters`**：在官方內容已獨立校驗並抽取出資料表或唯讀索引之後，以**明確審核的 Schema Adapter 與逐來源 SHA-256**解析內容，回傳不可直接啟用遊戲指令的結果。

本 PR **沒有實作 UnityFS／TextAsset 原始抽取**，也沒有把遊戲檔案搬入 GitHub，更沒有自動下載全部 Bundle。原有 `runtime_1275` 保留不動，不改登入閘門。

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

下一階段需要實作並驗收：由經簽核的 Manifest 選擇來源 → UnityFS／TextAsset 抽取 → 每功能業務關聯驗證（NPC、商店、製作、場景）→ 原子寫入個人快取 → GUI 預覽／正式服協定驗證。屆時再以 `OfficialCatalogIdentity.key` 設計安全切換，不會因解析成功而自行解除登入限制。

## 離線測試

```bash
python -m unittest tests.test_catalog_adapters -v
```

測試全為合成資料，沒有使用者帳密或官方遊戲資源。
