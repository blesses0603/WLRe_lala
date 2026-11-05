# 官方資源解析器自動診斷

本變更以 main `7c31aa2`／桌面版 v7.1.1 為基礎。PR #66 已預留 v7.2.0，本 PR 預計使用 **v7.3.0 開發版**，避免版本衝突；合併前仍需重查 main。不合併 main、不建立 Tag／Release，不代表新版物品格式已修好。

## 更新時的行為

Launcher、`run_auto_catalog` 與 `prepare_dynamic_runtime` 會自動開啟同一輪診斷。官方版本清單、YooAsset Manifest、UnityFS／TextAsset、資料轉換及表格解析都記錄成功或失敗。下載長度、MD5／CRC 與原有版本檢查繼續執行。

取得官方表格後，診斷會逐類檢查；一類失敗仍繼續檢查其他可取得表格，結果不會傳入 Runtime。完整 Runtime 仍走原有完整解析與交叉引用驗證，一項失敗仍拒絕啟用。缺少原始來源明確標示 `not_available`，不把未執行當成通過。

| 類別 | 已接入的解析範圍 |
| --- | --- |
| 來源與解包 | ResourcePath、Package version、Lua 路徑／MD5 清單、YooAsset 2.2.5、UnityFS／TextAsset |
| 物品與商店 | ItemData、Eve NPC／互動、商店資料轉換、Catalog Schema |
| 配方 | 已審核的 Smith 33／35-byte 格式、Runtime 配方引用 |
| 場景與傳送 | Scenes、Eve 門事件、StageMap、EveDoorLinks、DoorLinkData、傳送格式識別 |
| 文字與角色 | TalkData、TextData、NpcData／NpcCareerData |
| 活動 | Adventure／AdventureLv、DailyTask、Dungeon、CooperateEvent |

共 18 個解析模組接入。這裡的「所有解析器」指目前桌面 main 的**官方資源更新解析器**，不含遊戲封包、帳號設定或 Android 倉庫。CI 掃描 services 與 tools/resources 內新增的二進位資源解析入口，避免新解析器未接診斷就通過測試。未合併分支新增的解析器需在整合時一起接入；沒有把 PR #66 尚未合併的功能列為本次完成項目。

## 診斷與格式比較

報告包含解析器與 Schema、來源 SHA-256／大小、成功筆數、已知格式選擇，以及失敗時可取得的筆數、欄位、讀取位置、要求／剩餘長度與限制值。文字清單使用行號；無法確認的位置留空，不推測。複雜事件與保留區目前可能只定位至區段或記錄，不宣稱每個保留欄位都有名稱。

下次執行會與上次成功解析比較來源、Schema、大小及筆數變化。內容、大小或筆數改變只是差異資訊，不會直接判定不相容。已知 Smith 格式沿用原有完整長度檢查，選定 33 或 35-byte 解析器；**不新增猜測格式、搜尋偏移、跳過未知位元組或自動修改程式的行為**。

失敗來源不取代該來源上次成功基準。成功基準僅表示單一解析器曾成功，不表示整套 Runtime 通過，也不會作為來源可信度、登入或交易依據。報告不保存原始資料、解碼文字、例外訊息、完整 traceback、帳密或路徑；來源雜湊也只用於差異比對。

每輪最多保留 128 筆解析觀測，超出時優先保留失敗並標示捨棄數量；報告上限 256 KiB。以暫存檔和原子替換保存。診斷無法寫入時，保留原解析結果與例外，不改變登入判斷。測試注入的來源與唯讀下載預覽不會自動建立報告；測試可明確使用 `diagnostic_session`。

## 檢視與重跑

```bash
python -m tools.diagnose_parsers
python -m tools.diagnose_parsers --sync
```

Windows 也可使用 `py -3 -m tools.diagnose_parsers`。命令顯示實際報告位置：使用者資料目錄下 `WLRE_LaLa/official_sync/parser_diagnostics/latest.json`；成功基準為同目錄 `last_success.json`。可用 `--root` 指向另一個官方快取根目錄。

`--sync` 僅走既有官方公開資源下載流程，遵守每輪 24 份／32 MiB 配額，必要 Runtime 表格優先；每日任務、副本及協力表作為額外診斷來源，缺少時不因此改變原有 Runtime 所需表格集合。下載／驗證失敗不繞過校驗。退出碼 1 表示有解析失敗，2 表示報告或涵蓋資料不足，0 才表示本輪 16 類表格皆通過解析；0 仍不代表正式服或登入驗收。

## 驗證紀錄

- 新增回歸涵蓋：第 2 筆偏移、原例外保留、失敗後繼續檢查、未知格式拒絕、已知格式選擇與差異、成功基準保留、缺檔不算成功、巢狀失敗、損壞基準、唯讀輸出與有界紀錄。
- Linux 完整單元測試 1,544 項：1,389 通過、155 跳過，沒有失敗；新增診斷測試 11 項通過。compileall、git diff --check、repository audit、資源自檢及 UnityFS 自檢通過。無顯示環境的原生 Tk 測試會跳過；本次未進行 Windows／macOS 實機、安裝包或正式伺服器登入驗收。跨平台 CI 以 PR 結果為準。
- 2026-11-05 官方 DataPackage `1296_2026_11_04_13_34_19_13`／MainPackage `1296_2026_11_04_13_36_07_72` 實檔診斷：16 類中 15 類通過解析，物品表失敗。ItemData_C 大小 3,202,056 bytes、11,366 筆、SHA-256 `5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4`；第 2 筆 `name_length` 偏移 261，無法符合既有 UTF-16 名稱長度規則。此錯誤保留，沒有以跳過 2 bytes 的方式解鎖。
- 正式資源檔與私人診斷報告沒有提交 GitHub；CI 使用合成資料重現相同的欄位偏移失敗。
