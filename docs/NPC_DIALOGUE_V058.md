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
