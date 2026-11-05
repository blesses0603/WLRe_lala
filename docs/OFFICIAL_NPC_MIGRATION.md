# 第五階段：NPC 預設來源與 Lua 封裝查證

本機分支接續第四階段，未推送。種子從 21 項減為 **17 項**，仍未達成零離線資料安裝包。

## 已完成的 NPC 遷移

以下四項已從種子 `bundled_active`、`bundled_resources`、完整 Manifest、必要封裝清單及舊 initial_catalog 群組移除並 VACUUM：

- `npc_event_index_1262.json.gz`
- `npc_interact_1262.json.gz`
- `npc_talk_1262.json.gz`
- `npc_text_1262.json.gz`

`NPCIndex()`、`NPCInteractIndex()`、`load_catalog()`（NPC Talk）、`load_text_data()` 的預設讀取統一要求 `active_runtime()`；不再因舊 baseline 分支讀種子或使用者 SQLite 裡的歷史 BLOB。Runtime 仍經官方版本／Manifest、Bundle 校驗、既有嚴格解析器、規範 SQLite 與跨表驗證。新版本失敗時拒絕使用歷史預設來源，沒有改動遊戲封包閘門。

明確傳入檔案的歷史格式驗證 API 仍保留。已有使用者資料庫不刪除舊資料；歷史讀取工具與 pinned SHA 常數保留，不等於安裝包仍包含這四項內容。完整種子驗證會拒絕已退休的 BLOB，封裝也會排除同名鬆散檔案。

桌面 HomeMap／Android NPC 頁面原有來源錯誤處理及 catalog token 刷新沿用；冷啟動沒有正式 Runtime 時不能互動。getter 回傳資料仍保持拷貝隔離，對話 Talk 與本地化 Text 的 ID 空間不混用。`npc_battle_talk_1262.json.gz` 尚未遷移，不能以新 Text 表搭配舊群組就宣稱戰鬥文字已完成版本驗證。

2026-11-05 移除種子後，以真實官方 `1.3.23`／1296 Bundle 建立 Runtime，透過 scoped injection 供四個公共入口驗證：**11,014 NPC、1,637 互動、29,936 對話、40,000 文字**。Bundle 已獨立校驗，資料仍由規範 SQLite 讀取；`can_send_packets=False`。未登入遊戲、未連正式服，未做手機實機驗收。

測試不再依賴已刪除的舊 NPC 檔；改用明確合成的小型 Runtime 測試索引、選項順序、商店無價格時禁止交易及封包狀態守衛。官方實檔筆數另以上述記錄呈現，不把合成測試稱為官方實檔驗收。

## Lua 查證結果與缺少證據

第四階段已下載的 6 個 Lua 檔均與官方路徑清單 MD5 一致。再查目前專案／tools／工作區，未找到匹配這批檔案的解碼器或可讀同版 Lua；搜尋 `LuaScriptPathList`、`NpcTalkData`、`WLN Lua decrypt`、`wlreftpsrc Lua` 等公開來源，也未找到能以本批實檔驗證的實作。

已閱讀的公開候選：

- [slua-decode 原始專案](https://github.com/vshbnj/slua-decode)：作者明示其常數與 opcode mapping 來自另一個特定遊戲 build；包含封裝、壓縮及多層轉換。沒有本專案檔案的格式關聯證據，未套用或嘗試常數。
- [decrypt lua Gist](https://gist.github.com/myrhhcaiah/ce200e7f88e60ef957e41335262b36fb)：內容針對 Bundle／TextAsset 的固定遮罩與檔名轉換，沒有 WLN 版本、官方檔案指紋或對應測試；不能據此判定獨立下載的 Lua 檔使用相同封裝，未執行或納入程式。

上述是候選排除，不是宣稱所有開源實作均已窮盡。沒有匹配證據前，不做金鑰猜測、常數試探或執行官方 Lua，也沒有繞過伺服器認證／存取限制。

繼續解碼至少需要其一：官方／維護者提供的封裝規格與已知輸入輸出；可合法取得且有同版來源證據的解碼實作與測試向量；或官方發布的同版可讀表格／Lua。取得後仍需對六個實檔逐一驗證完整性、解碼邊界與欄位語意，不能只因輸出看似文字就啟用。

其餘 17 項的圖集、導航及戰鬥缺口沿用第三／四階段盤點。尤其圖像有資產位置不代表 item ID／sprite mapping 已可靠，導航還缺可重現的場景幾何與投影驗證。後續發布仍需先桌面種子提交、再 Android source lock；本階段只保留本機提交。

## 本機驗證結果

桌面最終全套 1,675 項通過（略過 163）；DISPLAY NPC 測試 82 項、冷啟動／GUI 3 項通過。Android 172 個測試檔共 1,356 項（略過 4），初跑僅商店測試還引用舊筆數；修正合成 fixture 的預期筆數後，全部 NPC 相關 57 項重跑通過。166 個共用核心檔案核對通過。未執行本階段遠端 CI。
