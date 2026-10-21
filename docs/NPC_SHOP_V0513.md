# NPC 第三階段：武器／道具商店與交易安全（v0.5.13 開發版）

## 官方 1262 資料證據（已逐檔核對）

- Lua/Logic/EventManager.lua：EventInteractList 依 Eve 的 formKind 開啟普通選項（1）、武器商店（2）、道具商店（3）；SendCloseShop 使用 C20-9 **零位元組 payload**，不同於普通選項 C20-9 40。
- Lua/Logic/Shop.lua：ShopCommodityData.SetDataFromEvent 僅接受 subItem.kind=3，商品索引是 subItem.id，物品 ID 是 subItem.dataBaseId。價格取 itemData[itemId].price、幣種 Gold，不是 TalkData 字串。
- Lua/Logic/Shop.lua：SendPurchaseItem(index,buyingCount) 發 C27-1，欄位為 u8 商品索引 + u32 數量（Little Endian）。
- Lua/Logic/Bag.lua：SendSellItem(index,count) 發 C27-3，欄位為 u8 背包格位 + u8 數量。
- Lua/Logic/Protocols/Protocols_027.lua：S27-1 購買結果 1 byte，0 伺服器回覆成功、1 金幣不足、2 背包空間不足、3 超數量、4 其他失敗；S27-6 為販售後背包/金幣資料；S27-8 為販售結果通知（1 成功）。
- Lua/Data/ItemData.lua：ItemData.New 的 price 和 sellPrice 是 u32；restrict 的 bit 16 表示不可賣給 NPC。
- 官方 Eve 1262 資源：共 65 組 formKind 2/3 商店（19 武器、46 道具）。目前 65 組商品的 kind=3 / database_kind=2 都通過來源核對。

## 已完成

1. 新增 wlre/services/world/npc_shop.py：只接受已驗證 Eve 真實場景及 formKind=2/3，按官方 id 列出商品，已知名稱取現有戰鬥道具清單；未知名稱顯示 ID。不把商品 id 當作一般 NPC 對話或 TextData。
2. 小地圖 NPC 分頁在已接收到該場景的 S20 type 6 商店事件時開啟唯讀商品／背包視窗；尚未同步的背包不顯示推測存貨。買入／賣出金額一律顯示「待官方 ItemData_C」。
3. 獨立的 close_npc_shop 只在商店真實事件啟動、場景一致、手動確認時送一次官方 C20-9 空內容，等待 S20-8。普通對話關閉不再適用於已核對的商店。
4. 補上 S27-1 官方 1-byte 回覆解析，S27-8 既有訊息沿用。伺服器回覆成功**不等於**價格已扣除或物品已入背包，必須重新核對實際同步。
5. purchase_wire_layout / sell_wire_layout 僅用於單元測試及未來協定驗證。命令路由明確拒絕 npc_shop_buy / npc_shop_sell；現階段任何交易都不會送到伺服器。

## 尚缺與後續必要條件

- 完整官方 ItemData_C TextAsset（不是 TextData_C 或 TalkData_C），用於確認商品 name、price、sellPrice、restrict、可堆疊狀態。
- 角色 Gold 的真實 S 封包載入、持有金額與修訂版次。沒有權威同步不允許付款。
- 購買前必須確認背包空格與容量、數量上限、價格×數量溢位保護、交易前金額、交易唯一識別，以及購買結果和背包變化一致性。
- 販售前必須先查 restrict bit 16、已同步可售格位與實際數量；不得賣任務物品、綁定或未核對物品。
- 交易須人工二次確認；送出後不重送，直到權威 Gold 與背包資料對帳完成，遇不一致則標記 uncertain 並要求重新登入。
- 正式遊戲伺服器真實 NPC 買賣、關閉商店與伺服器重試情境仍未 E2E 驗收，不能宣稱真實購物功能可用。

## 下一階段所需的來源

可沿用以前的 AssetStudioMod 或 UnityPy 搜尋器，從 DataPackage/MainPackage 的 BundleFiles 掃描 TextAsset 名稱 ItemData_C，保留原始 bytes 與掃描報告。不要從資料庫或一般文字 ID 推算價格。完成可靠 ItemData_C 解碼並擷取金幣同步封包後，才能啟用真正的購買與販售。


## v0.5.14 原始 ItemData_C 來源驗證與 UI 基礎價整合（2026-10-21）

- 來自使用者上傳 `ItemData_搜尋結果.zip`，TextAsset 為 `ItemData_C`，原始 3,157,231 bytes、SHA-256 `5fea03839a3e737ff33c5462fc553ab88966de5b02d1c95d71d3ffb54351ece1`。
- 完整依 `Lua/Data/ItemData.lua` 的 `ItemData:New` 解碼 11,287 筆，4 組 bodyType 顏色/圖號欄位及剩餘所有欄位均消耗；ID 零重複，檔案結尾剩餘 0 bytes。
- Eve 1262 的 65 組商店共 309 筆商品欄位，215 種不同物品 ID，**所有 215 種都有 ItemData_C 物品資料**；既有商店資料的商品順序、C20-9 關閉語意不變。
- 將完整官方來源轉成 **派生欄位索引** `wlre/resources/npc_item_data_1262.json.gz`，11,287 筆，112,854 bytes，SHA-256 `94f45d1b0e4f8c8587219b5c87c3a7e5f65b5573487a1e8d4d7f64f35e2ceb17`。只收錄名稱、基礎買價、NPC 收購價、restrict、openUsed、needLevel，並保留來源檔 SHA，未包含原始完整遊戲二進位。
- `ItemData.CanSale` 對應 restrict bit5（0x0010），全物品中 5,301 筆禁止賣給 NPC。UI 會逐筆標示「不可賣給 NPC」；不會因資料表有 sellPrice 就允許賣出。
- 價格若實際享有折扣，`ItemData.price` 只是官方**基礎價**，不是伺服器最終扣款額。角色列表具原始 gold 欄位，但並非下單時的可靠即時金額；尚缺交易後權威同步和對帳。保留購買/販售指令拒絕，僅 UI 價格唯讀。
- 資料缺失、SHA 錯誤、結構不符，UI 退回價格未知，購物永遠不會因此開放；原生打包必要資源檢查將拒絕不正確資料。


## v0.5.15 官方 Gold 封包與可靠餘額（2026-10-21）

- `Lua/Logic/Protocols/Protocols_026.lua` 已確認 `S26-4` 為 Gold u32 絕對初始化；`S26-1` + `S26-2` 各以 u32 增減及 u8 提示旗標處理；`S26-3` 是金額上限通知。已在 `wlre/network/protocol.py` 增加精確讀取及欄位長度校驗。
- 新增 `State.gold` 單執行緒持有的 `amount/ready/reliable/source/revision` 欄位，不採用角色列表中的 Gold 取代權威初始化。S26 增減早於初始化、數量溢位/不足、觸及未知上限或重新選角色時金幣標為不可信。
- NPC 商店預覽顯示最新已核實的金幣金額，但仍不可購買／販售；真正交易須等 S27 購買結果與 S26/S23 原始金錢／背包事件能完整對帳、折扣最終價驗證以及正式服端到端。
- 保持 PR Draft，不合併 main，不宣稱實測帳號金幣同步成功。


## v0.5.16 S23/S26/S27 接續加工：實際封包證據與非授權對帳

### 官方 1262 內容再核對
- `Protocols_023.lua`：S23-5 `Bag.ReceivePlayerThing` 背包初始化；S23-6 `Bag.ReceiveGetItem` 增加物品；S23-9 `Bag.ReceiveDeleteItem` 扣除物品。
- `Protocols_026.lua`：S26-1、S26-2 `u32 Gold + boolean notify`；S26-4 `u32` 絕對初始化；S26-3 通知上限。
- `Protocols_027.lua`：S27-1 `u8` 買入結果；S27-6 `u32 gold + u8 index + u8 count`，由官方 `Bag.ReceiveSellItemResult` 扣除背包，但原版**不以此 u32 寫入金幣餘額**；S27-8 `u8` 販售通知。
- 這些協定**沒有在目前來源中核對到唯一交易識別碼**，因此單次成功通知不等於全額扣款及庫存變動已經完成，更無法從多筆混合變化推測哪個交易屬於哪個 NPC。

### 新程式
- `wlre/services/world/npc_shop_evidence.py`：已接入 `State.apply` 正常處理完成後的只讀觀察；最多 96 筆，存封包次序、簡化物品與金幣欄位、兩邊修訂序號及可靠性；不含原始封包、帳密或其他個資。
- `classify()` 只對**預先提供的離線預期訂單**比對，檢查 S27 回覆、S26 變動、S23 數量；支持互相亂序，但拒絕重複與旁支事件。結果可能為 `pending`、`rejected`、`uncertain`、`observed_consistent`，最後一者仍不等於正式交易結算。
- 這個比對器**不註冊到 UI 或網路指令路由**，不能直接呼叫購買／販售，也不會根據離線相符自動開放付款。商店視窗只顯示最近看到的封包類別。
- 將三組封包的離線亂序、錯誤金額、重複通知、缺少初始化、無金幣增加的販售、證據窗口被捲動及角色切換，加入回歸單元測試。

### 未完成的安全前提
必須在真實伺服器以**單筆、人工可控、已明確授權的商店測試**核對：交易前 Gold/背包權威快照、折扣後實價、買賣封包、S27 結果、S26 及 S23 變動、異動封包重送／其他系統影響，才可能啟用對應 UI。不可因離線 CI 成功就開放支付。
