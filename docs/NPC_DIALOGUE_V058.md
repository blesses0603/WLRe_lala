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
