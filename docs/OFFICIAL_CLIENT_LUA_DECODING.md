# 官方 Lua 封裝解碼與 ItemData 欄位證據

本階段更新先前 `REMAINING_RESOURCE_EVIDENCE.md` 的 Lua 阻擋結論：已由公開官方 Android 客戶端的靜態讀取邏輯確認解碼，並以六份同版資源驗證。未執行官方客戶端或 Lua；沒有使用帳號、繞過認證或將內容金鑰與解碼後遊戲內容放進版本庫。

## 來源與可重現證據

- [官方網站](https://wlre.chinesegamer.net/) 提供 [Android APK](https://cgdl.chinesegamer.net/apk/wlre.apk) 下載。
- 研究樣本 APK 大小 103,074,197 bytes，ETag `"b65fca9976e6dc1:0"`。僅以有總量上限的 HTTP Range 取得 ZIP 索引及四個相關檔案；驗證 206、Content-Range、ETag、ZIP CRC。合計 27,364,442 bytes，不執行程式。
- `global-metadata.dat` SHA256：`5a71da3a4b37486b056b9873655e42d7d7a583eae6ebfe2efdd18ebe66a23260`。
- `libil2cpp.so` SHA256：`7798c9aaa6986ee200deacf9816a5d2f17a606944aa4a56dd06bfa1acb344636`。
- Metadata magic `0xfab11baf`、版本 31；參考 [Il2CppDumper MetadataClass](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs) 與 [Il2CppExecutor](https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Utils/Il2CppExecutor.cs) 定位型別、方法 token 與 native 方法表。自行撰寫最小分析腳本，透過 ELF relocation 與 ARM64 靜態反組譯交叉確認呼叫。

確認的呼叫鏈：`ArtifactLuaFileUtils.ReadFile` (0x3100664) → `File.ReadAllBytes` → `CryptUtils.DeCrypt` (0x328e6a8) → `Rijndael.Create` 與 CryptoStream。`ProjectSetting..cctor` (0x1587cec) 以 UTF-8 建立兩個 16-byte 參數，存入 static +0x30/+0x38；它們來自 metadata literal 1571、1667。不將參數值輸出或硬編碼。另一個首尾位元交換函式 `EngineTools.DecryptionBytes` 並非此呼叫鏈，不作為 Lua 解碼器。

AES-CBC、PKCS7 解碼後嚴格檢查 UTF-8，並重新加密逐 byte 比對原始檔。六份官方 MD5 驗證過的 1.3.23 資源全部成功：EmojiData、ItemData、NpcTalkData、SkillData、SkillMotionData、StageMapData。額外鎖定每份輸入與輸出的 SHA256，避免僅憑 padding 或可讀文字判斷成功。確切指紋在 `tools/official_lua_decode.py`。

離線重現工具：

```sh
python -m tools.official_lua_decode --metadata /private/global-metadata.dat --input /private/ItemData.lua --output /private/decoded/ItemData.lua
```

需要選用研究依賴 `pycryptodome`；不新增 LaLa 執行期依賴。工具只接受已審查的 metadata 與六份資源指紋，限制檔案大小、拒絕寫入 Git 工作樹或覆寫既存檔案；未知版本明確失敗。此工具不下載、執行或自動啟用 Lua。原始檔、反組譯、呼叫定位與驗證 JSON 保存在本機 `/workspace/validation/official-client/`；它們不屬於發佈內容。

## 已實作的兩端變更

官方 `ItemData.lua.New` 證實欄位順序。針對既有 SHA256 鎖定的 1296 ItemData，兩端解析器新增 `kind`、`order`、`icon_id`、`shop_icon_id`、`material`、`level`、`fit_type`、`special`、`spares`、兩組尺寸、`available_time`、`limited_time`、`use_count`。1296 尾端兩 bytes 確認為 `style_bank_set_sort_id`，同時保留舊 `unknown_tail_1296_hex` 診斷相容性。舊版不暴露未驗證的新增語意。

物品正規化 schema 提升為 `runtime-v2-dynamic`（固定版相應為 `runtime-v2-1275`），避免沿用缺少新欄位的舊快照；既有原始檔與快照保留。未知 layout 或 digest 仍明確失敗，不猜測修復。

實檔共 11,366 筆。官方 Lua 使用 `s%04d` 格式搭配 `iconId` 取得 Sprite；先前缺少的 79 筆新物品全部能對到已實際解碼的官方 Sprite，零筆缺失。舊 11,287 筆映射中 11,286 筆一致；物品 39139 由舊 s8239 改為目前官方 s7481，保留此版本差異，不強迫吻合舊種子。全部 open_used 一致，但尺寸與煉金 spares 有差異，不能用舊資料反推或覆蓋官方欄位。

## 範圍與下一步

本階段完成可靠研究解碼器、已證實欄位與資料庫 schema 升級。尚未切換物品圖示 UI 或移除其種子。剩餘九項隨附資源仍保留：stage_coordinates、graph_origins、navigation_data、item_icon_map、item_icons、item_stackable、alchemy_catalog、combat_catalog、normal_attack_data。沒有宣稱零離線資料目標完成。

下一步可依官方 iconId 建立版本化圖像與映射資料庫，處理 native fallback 與兩端 UI；堆疊判斷必須完整遷移 `CanOverlap` 的裝備、特殊 ID、限時／次數等規則，不能把單一欄位當 boolean。煉金／戰鬥／導航仍需核對各消費者語意與其他官方依賴。導航下載上限維持原值。官方伺服器實際登入、Windows／macOS 及 Android 實機驗收未執行，後續修改僅留本機、不推送。

## 本階段驗證

- 最終桌面完整回歸：1,726 項，成功，略過 3 項；含 Xvfb GUI 與選用研究加密依賴。
- 最終 Android 逐檔隔離完整回歸：181 個檔案全部成功，共報告 1,404 項測試，略過 4 項。
- 兩端均以六份實際 Lua 驗證輸入／輸出 SHA、重新加密相等，並經真實 dynamic runtime 讀取 11,366 筆新欄位。SQLite 保留 runtime-v1-dynamic 與 runtime-v2-dynamic 快照。
- 合成測試涵蓋非零欄位位置、舊版欄位隔離、未知來源／metadata、損壞密文、大小界線，以及 padding 有效但輸出指紋不符時拒絕。
- 回歸期間更新 Android 舊「僅有 opaque tail」斷言，以核對新增欄位並保留原有欄位；桌面副本 GUI 測試補上已存在的合成 catalog fixture，避免依賴已移除的種子或本機快取。產品安全閘門不變。
- 桌面 repository audit 與 Android 170 檔來源一致性檢查成功。測試日誌位於本機 /tmp/phase15-desktop-final.log、/tmp/phase15-android-final.log；未執行遠端 CI 或實機驗收。
