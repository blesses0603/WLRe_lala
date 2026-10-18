# 戰後修理／物品整理

自動戰鬥設定的「修理／整理」分頁使用目前帳號已可靠同步的背包選取物品，兩格修理優先順序、十五格整理名單；清單在上線／背包變更後自動更新。排除鎖定、限時及已保留格位；選取時重查庫存，缺貨保留設定不換物品。設定隨 AI 設定依帳號與伺服器保存，預設關閉，登入不自動啟動。

## 執行流程

- 必須啟用 AI，至少完成一場戰鬥，且戰鬥、戰後事件均結束。背包更新安定 0.5 秒後才操作，檢查期間暫停徘徊；角色活動、製作、煉金、遠征待確認操作及 HP／SP 補給待確認時等待。
- 先找角色及目前出戰夥伴穿戴的普通裝備。剩餘耐久為 `250 - damage`，低於或等於設定門檻時依指定順序從背包挑選修理工具。門檻預設 50，可設 0～249；工具已損壞或無可靠耗損值時不使用。不修倉庫／背包裝備、不修未出戰夥伴裝備。需修復但指定道具缺貨時，徘徊保持等待，補足背包後自動重查。
- 自動修理限 fit_type 1～6、special=0 的普通裝備；排除已損壞、黑暗胸針、鎖定及限時裝備。現有精簡物品表沒有 useCount 與 CantRepairEquip 全欄位，因此其他修理資格仍由伺服器確認；不推定特殊裝備可修，拒絕或逾時即停止而非改試另一件裝備。
- 修理確認需同一裝備（ID／序號）耐久恢復至 250，且同一修理道具的損害增加或件數扣除，兩者可以任意順序抵達。修復扳手可能只增加耗損，不會每次扣一件。
- 再依整理名單逐格檢查。官方 CanSale 是 restrict 沒有 16 位元，CanDelete 是沒有 128 位元；可販售則販售，不能販售但可丟棄才丟棄，兩者皆不可者跳過。販售被拒絕不轉為丟棄。
- 不整理已設定的修理工具；戰後補給啟用時亦保護其明確指定的補品。已被戰鬥補給、製作、煉金或遠征保留的物品不使用。
- 每次只送一筆並保留該格位；等待期間阻擋其他物品操作並暫停徘徊，遠征也等待目前操作確認。停止 AI 不撤回已送出操作，仍接收並確認結果，完成後不再接續。
- 物品格位／序號或裝備變更、販售回覆數量不符、背包失效、明確失敗或 20 秒逾時，停止 AI 與徘徊、保留格位且不重送。需重新登入取得新狀態。未做本機物品扣除或修復成功預測。

## 協定

C23-84（Enhancement.SendRepairEquip）：kind UInt8（穿戴=2）、裝備 ID UInt16、裝備索引 UInt8、夥伴索引 UInt8（角色=0）、道具來源 UInt8（背包=1）、工具格位 UInt16、工具 ID UInt16、數量 UInt16（1）。

C27-3（Bag.SendSellItem）：格位 UInt8、數量 UInt8。S27-6：gold UInt32、格位 UInt8、數量 UInt8；原版 ReceiveSellItemResult 直接扣除該格物品，不額外等待另一筆 S23-9。gold 欄位原版沒有更新錢包，本程式亦不猜測餘額。S27-8 result=0 視為販售失敗。

C23-124（Bag.SendDeleteItem）：格位 UInt8、數量 UInt8、固定 UInt8=2。等待相符 S23-9 扣料確認。

S23-140 kind=1：grid UInt8、index UInt8、damage UInt32、npc UInt8；grid 1 為背包、2 為角色、3 為夥伴。kind=4：穿戴索引 UInt8、damage UInt8、npc UInt8。另接收 S23-27／28 裝備耗損及 S23-35 損壞，避免使用舊耐久。

不使用 C23-78／79 開啟官方伺服器遙控器，避免沿用未確認的伺服器補給／經驗道具設定。所有操作由本機單筆規劃並使用官方公開於 Lua 的相同手動操作協定。

## 核對來源與驗證範圍

使用者提供的 WLRE_Lua_1262_Decoded_Analysis.zip，SHA256 `3e53db47ea22294207bfbc230322dbcc0429e4a4c94c7f67aacc924e18d77fce`。來源為 Logic/AutoPlay.lua（AutoSellDelete）、Logic/Bag.lua（SendSellItem／ReceiveSellItemResult／SendDeleteItem／UpdateItemDamage）、Logic/Enhancement.lua（SendRepairEquip）、Logic/Protocols/Protocols_023.lua、Protocols_027.lua、Data/ItemData.lua、Common/Define.lua、UI/Logic/UIEnhancement.lua。

已用原始封包格式、狀態機與介面測試驗證；尚未在正式服實測修理、販售或丟棄。Lua 原始來源保留於開發環境，未將解碼原始碼加入程式發佈。
