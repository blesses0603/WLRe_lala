# NPC 第二階段：對話事件與手動接續（v0.5.8）

## 官方資料核對

- 1262 Lua/Logic/EventManager.lua 的 SendNpcEvent 使用 C20-1 / UInt16 場景索引；SendAskServerEvent 使用 C20-6 / 0。
- EventManager.ReceiveEventResult 對 S20-1～6 依序讀取 diagnosis(U8)、groupNumber(U16)、number(U8)、type(U8)、class(U8)、parameter(U16)、style(U8)、value(U32)、meanNumber(U16)、conditionNumber(U8)、eventNo(U16)，共 18 bytes。
- type=1 的 meanNumber 是 TalkData 文字 ID；type=6 則是場景 interactDatas 的索引，不是可直接送出的選項值。
- S20-8 表示事件結束；S20-74 伺服器回覆互動距離／場景／索引錯誤。
- 官方 NPCController 採 Unity 世界距離 1.6 檢查，和目前地圖格坐標尚無可信換算。LaLa 不假設使用者靠近、不自動走路，遠距離由伺服器拒絕。

## 已實作

- 在主畫面「NPC」分頁以按鈕主動送出，彈出確認，警告事件可能觸發戰鬥或任務效果；不因單擊／雙擊自動傳送。
- 僅在角色已同步且閒置、同場景、真實 Eve 官方 index + NPC ID + 坐標核對成功、eventCount 大於零時允許 C20-1。
- 每段 talk/continue 僅人工按「下一段對話」送一個 C20-6 00；送出後直到伺服器確認不能重送。
- S20-8 結束事件；S20-74 在手動 NPC 流程中解除等待；未知 S20 payload 安全顯示事件效果不可識別，而不觸發解碼斷線。
- 非 NPC 人工啟動的原有協力／副本 C20-6 接續規則不變。

## 尚未完成

- 完整官方 TalkData 字串表尚未導入，因此 UI 顯示文字 ID，不會假造台詞。
- interactDatas 及 subItemDatas 的二進位選項表沒有經獨立來源驗證，因此不會送 C20-9，也不開放購物或第三階段商品交易。
- 未支援的劇情動畫／戰鬥事件不主動推進，若結果不明應重新登入同步。

## 測試界限

本 PR 提供封包布局、身分校驗、單次接續、防重送與拒絕狀態的單元回歸。**CI 成功並不能等同正式伺服器端到端驗收**，需要以測試角色在真實場景核對完整 C20-1 → S20 → C20-6 → S20-8 及 20-74。


## 2026-10-21 對話文字與選項安全優化

官方 Lua 對照：\`Lua/Data/TalkData.lua\` 的 \`TalkData_C\` 二進位格式是 i32 筆數、逐筆 u16 文字 ID、u16 Unicode 字串 byte 長度、UTF-16LE 字串、5 個保留 byte、u16 voice ID、4 個保留 u16、5 個保留 i32。\`UIDialog.SetSelectList\` 讀 \`interactDatas[dataIndex].subItemDatas\`，\`EventData.NewInteract\` 另記 formKind 及各選項的文字 ID、種類；缺乏實際 Eve 事件二進位表，不能僅憑對話 ID 猜測選項內容。

- 新增 \`wlre/services/world/npc_talk.py\` 嚴格邊界／UTF-16LE／唯一 ID 校驗，輸入檔 SHA256 僅作完整性追蹤，不能單憑它證明來源官方。
- 取得並**獨立核對**官方繁體中文 \`TalkData_C\` 原始 TextAsset 後，可執行：

  \`\`\`bash
  python -m tools.resources.import_npc_talks TalkData_C.bytes --output npc_talk_1262.json.gz
  \`\`\`

  將產物 \`npc_talk_1262.json.gz\` 放進專案 \`wlre/resources/\`（需經審查、確認授權與來源後才提交）；目前倉庫尚未內建真實對話字串索引。
- 如果索引存在，NPC 對話顯示已匯入的文字與「查看全文」；不存在或檔案不合法時維持文字 ID，**不會顯示捏造的文字**，也不影響其他功能。
- 官方 \`EInteractListResult.CLOSE = 40\`；玩家於型別 6 的未知選項可手動確認關閉，單次 \`C20-9 0x28\` 後等待伺服器 S20-8，不重試、不推定伺服器成功。
- **一般選項選擇仍停用**：必須有真實 Eve interactDatas 並核對場景、選項排列與 formKind 才能評估 \`C20-9\` 對應值。型別 2／3 是商品商店，不屬於本階段。


## v0.5.9 官方 1262 繁中資料整合（2026-10-21）

- 使用者提供的 `TalkData_C` 29,873 筆來源 SHA256 `df9d98d268cc8cb26a109f50aee90405eefe2328c5862447f9297cb67ead45be`；`TextData_C` 39,901 筆 SHA256 `5b2d0a7e4e5048a629630e490c8c1e1bb1498f840b754087d59de28951d9aaf0`；`NpcTalkData_C` 16 組、94 筆 SHA256 `9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8`。
- GitHub 已提交 `wlre/resources/npc_battle_talk_1262.json.gz`（653 bytes）、`npc_1262_sources.json`、分離的 `TextData_C` 與戰鬥 NPC 查詢程式及測試。
- 完整官方文字資產尚未進 GitHub；可用先前產出的 `WLRE_1262_NPC_繁中資料索引包.zip` 依下面兩行本機安裝。

```powershell
py -m tools.resources.install_npc_text_1262 "WLRE_1262_NPC_繁中資料索引包.zip" --check
py -m tools.resources.install_npc_text_1262 "WLRE_1262_NPC_繁中資料索引包.zip"
```

- 匯入器不修改遊戲目錄、只允許三份已核對的原始 gzip，拒絕來源與 SHA-256 不符、拒絕不明覆寫（除非 `--replace`）。打包器會包含執行前已放入 `wlre/resources` 的 .gz。
- 戰鬥 NPC ID 屬 `TextData_C`，不可直接用 `TalkData_C` 查詢；選項資料仍需完整驗證 Eve `interactDatas`，未授權封包保持停用。正式服尚未實機驗收。


## v0.5.10 直接收到的 GitHub 資料與對話 UI（2026-10-21）

- 已在 PR #41 驗證上傳檔：`npc_talk_1262.json.gz` 886,406 bytes / Git Blob `231ffd7d92b142bfd2c7c34b1c69a4e2ed782403`；`npc_text_1262.json.gz` 757,105 bytes / Git Blob `2c38dec80539355fee4f94d94bc467c856746837`，與原始上傳 ZIP 完全相同。
- 已將兩份檔案列為 `REQUIRED_RESOURCES`，打包失敗不得宣稱成品可顯示完整繁體中文。載入時核對完整 SHA-256，避免只核對來源欄位與筆數卻漏掉內容竄改。
- 手動 NPC 對話在收到 S20-1～6 類型 1、具可信文字 ID 時，保留最近 50 個 ID，結束或拒絕後可在「本輪對話紀錄」查看本次內容；開始新 NPC 對話即清空上一輪紀錄。只呈現原始文字，不推測 NPC 選項或伺服器端條件。
- 選項 `interactDatas` 的原始 Eve 二進位資料仍需獨立核實，`C20-9` 一般選擇及商店操作繼續停用；本次未改動戰鬥 AI／協力／副本邏輯。
- 自動化單元測試與 GitHub Actions 驗收不等於遊戲正式伺服器驗收。


## v0.5.11 官方 Eve interactDatas 解析與一般選項

- 原始資源：Eve_1262.bundle，MD5 81af690395d5e6a233afa9a664e2c555。
- 解析統計：1,256 場景、10,879 NPC、1,622 互動選單（505 場景）、formKind=1 一般 1,557、formKind=2 武器商店 19、formKind=3 道具商店 46。
- 選單欄位依官方 Lua EventData.NewInteract，包含 index:u16、name:20bytes、formKind:u8、linkNumber:u16、subItemNumber:u8、subItem 每筆 id:u8、dataBaseId:u16、dataBaseKind:u8、kind:u8。每個場景另外存在 44 bytes 非 Lua NewInteract 定義的尾端資料，不當作選項來源。
- UIDialog 的 kind=3 顯示按鈕依畫面順序使用 0-based parameter；EventManager.SendInteractListResult 將其組成數值 30、31、32 等 1 byte C20-9 回覆。文字 ID、subItem.id 或整份清單索引都不能直接當回覆值。
- 已對照官方 TalkData_C，1,554 組一般選單所有資料通過保守核對。3 組一般選單資料來源／結構不明及 65 組商店仍禁用；商店與一般選項功能分離。
- 唯讀來源檔 npc_interact_1262.json.gz：19,914 bytes，SHA-256 37bba3db9ec06cc4838bec99a2fb16d6b49f7064edcfc46e59bf30ac08888592。此檔尚未提交 GitHub；需下載本次附件並透過 GitHub 網頁上傳 PR #41 分支的 wlre/resources/。
- 選項只有收到 S20-1～6 的 effectType=6、與當前場景及索引一致、formKind=1、kind=3、dataBaseKind=1、繁中文字 ID 有效，並由使用者二次確認才會送出一次。其餘情況嚴格拒絕。
- 正式伺服器劇情分支、戰鬥與物品效果尚未驗收。PR 保持 Draft，不合併 main。
