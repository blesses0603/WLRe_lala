# 官方戰鬥目錄資料庫

桌面及 Android 不再讀取 combat_catalog.json。技能、技能索引、物品效果／裝備附帶技能、NPC 技能、角色起始技能及屬性權重，從同版官方來源驗證後匯入 SQLite，再由目前啟用的 Runtime 讀取。剩餘隨附遊戲資料只有 stage_coordinates.json、graph_origins.json、navigation_data.zip，尚未達成完全零離線資料。

## 官方來源與解碼

Data 1.3.23 的 SkillData_C SHA256 為 ed6383251b4f0fb9f7d9eb85c99346a268b99bdded839f6957f083c4b7f0545c。SkillData.New 定義每筆 125 bytes，驗證記錄數、唯一 ID、完整消耗；未審核指紋不套用布局。NpcData_C、ItemData_C 沿用已驗證 1296 指紋。ItemData 額外的 skillLink 只在戰鬥解析明確要求時返回，既有 items 快照格式不變。

官方 LuaScriptPathList.txt 指出 Lua/Common/Define.lua 與 Lua/Controller/FightUnit.lua。前者包含角色性別、初始衣服與技能，後者包含 elementAttackTimes 矩陣及其 GetElementAttackTimes 消費邏輯。只抽取已審核全文指紋內的資料欄位，不執行 Lua、不使用 eval，也不以程式常數內嵌遊戲矩陣或角色表。

解碼參數來自官方網站公開連結的 https://cgdl.chinesegamer.net/apk/wlre.apk 中 global-metadata.dat。使用已核對 APK 大小、If-Range ETag、精確 HTTP 206／Content-Range 與 ZIP CRC，僅擷取該成員；未下載或執行整個客戶端。中繼資料必須符合已審核 SHA256，Lua 同時符合官方 MD5、來源 SHA256、解碼 SHA256 與重加密一致性。參數、Lua、APK 和二進位遊戲內容不隨程式發佈。

首次來源同步有獨立 8 MiB／16 請求上限；中繼資料解壓上限 16 MiB、Lua 每份 2 MiB、清單 512 KiB。技能 Bundle 仍使用既有核心剩餘額度，未提高導航或核心下載限制。HTTPS 不接受轉址；Android 使用既有明確 CA 處理器。快取只保存驗證過的輸入；被拒的下載保留在 rejected 區，失敗不替換最後可用的版本清單。最後同步狀態獨立記錄；失敗的更新不會靠讀取舊快取冒充成功，重試通過才解除該狀態。

## 匯入與消費者

同版快照包含官方文字表、NPC／ItemData／SkillData、兩份 Lua 原始密文、版本清單及中繼資料，沿用 normalized_resources 的來源雜湊、原子交易、衍生資料校驗／修復及舊版本保留。公開角色矩陣不單獨成為跨版本備援。官方資料更新而指紋尚未審核時，停止該戰鬥目錄並回報狀態，不猜測新格式。

CAT 改為動態讀取目前快照。複合技能／物品操作以 ContextVar 固定單次操作的來源，避免中途混用版本。資源頁包含來源狀態與版本刷新；桌面補給清單不再永久快取首次空結果。尚未同步時保留既有設定，但執行時仍須有當次物品／技能證據。

伺服器技能原始 key、NPC 技能槽及直接技能更新仍保留；同步後可重新映射，撤銷技能不會被舊槽資料復活。裝備尚不能定位時保留原始資料與最多 256 筆後續裝備更新；超額則清空可操作裝備並要求新快照，不猜測。此變更不增加任何自動登入或送包授權。

## 驗證與打包限制

兩端官方實檔得到 1,597 技能、378 技能索引、11,366 物品、7,586 NPC、15 角色及 5×5 屬性矩陣。與舊表比較：索引、角色和矩陣全相符；1 筆既有技能、6 筆既有物品、7 筆既有 NPC 因官方更新而不同，沿用新版值。

測試涵蓋截斷／重複技能、未知指紋、HTTP Range 與額度、被拒清單不覆寫舊版、冷啟動、單次來源一致性、技能撤銷、晚到裝備耐久回報及設定保存。測試資料為小型合成資料，不將完整舊戰鬥表搬入測試或產品。

兩端依賴固定 PyCryptodome 3.23.0；桌面 Nuitka 明確包含 Crypto 及其資料，既有離線解包器自測新增 AES 已知答案檢查。Android 固定使用的 [python-for-android 配方](https://github.com/kivy/python-for-android/blob/8ef9d1dbbf769d2c14681dbc3c116c85e2e93bae/pythonforandroid/recipes/pycryptodome/__init__.py) 提供相同版本。AES-CBC 使用 [PyCryptodome 官方介面](https://www.pycryptodome.org/src/cipher/classic)。已完成主機測試不代表 Windows／macOS 原生產物或 ARM64 APK 已重新建置；尚未進行正式服送包或 Android 實機驗收。

## 導航仍未完成

當次官方 MainPackage 有 775 個 Scene 資產。依 Manifest 宣告的完整依賴計算，沒有任何樣本符合現有 32 MiB／24 檔限制；最小 M12600 仍需 87 Bundle、825,658,853 bytes。這是完整依賴總量，不是已下載量。再逐一校驗 1,626 個不同 Bundle 的現有快取，775 個樣本仍無符合額度者；最小樣本尚需下載 86 檔、800,256,441 bytes，並經正式更新規劃器交叉確認。沒有提高額度或跳過依賴。

另以 astar、navmesh、navigation、pathfinding、recast、graph 檢查 Manifest 資產名稱，未找到獨立候選；這不代表官方沒有內嵌導航資料。仍需可靠的官方導航幾何解碼、與封包座標的映射，以及 origin／offset_y／場景邊界的交叉驗證。可行下一步是取得官方提供的獨立導航資料，或由使用者另行授權的完整同版場景樣本建立驗證流程；在此之前保留三項既有資料，不能以只換場景 ID 或空幾何替代。

最終主機回歸：桌面完整 1,752 項通過（略過 3）；Android 完整 187 檔、1,430 項通過（略過 4）。另完成失敗更新與壞 ZIP 路徑檢查，以及主機版 AES／UnityFS 自測。
