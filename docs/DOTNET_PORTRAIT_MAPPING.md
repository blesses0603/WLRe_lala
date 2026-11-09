# ver 8.0.61 頭像角色與配色映射

## 來源與語意

對照 `wlre/services/world/portrait_mapping.py`、`character_portraits.py` 及 `portrait_database.py`。玩家固定 15 組 sex／head 對應 Define.lua CHARACTER_DATAS，使用 palette1／palette5；必須有非零 role_id，未知組合不採預設。夥伴必須唯一符合 active_npc_id，使用接收資料及 stat override 的 modeling，非零 modeling 優先，否則使用 NPC ID；未知 ID、重複匹配、超出 ushort modeling 拒絕。

NPC 原始資料必須通過既有完整 layout 與固定 SHA `edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c`。從 203-byte fields 的 modelKind@5、iconId@6、四組 uint palettes@8 讀取；icon=0 無頭像，modelKind=0 的圖示字串不補零，其他為四位 icon 加 kind suffix，保持 Python 語意。配色均限制 0..999999999，NPC 第五組保持材質預設。

production 可選頭像取得現在同時要求 DataPackage `1296_2026_11_04_13_34_19_13`、既有 data 1.3.23／Main1296 及 NPC SHA；在下載頭像前檢查，未知版本不擴大請求。映射持有不可變資料，原始 buffer 改寫不影響結果。

## 發布與界線

同次來源準備建立映射，頭像獨立回讀完成後才附加到 publication。選圖必須經精確目前 activation、映射及同批 image key，帳號 binding 仍前後檢查快照。沒有圖片的 key 不回退到其他角色。停止、刷新、釋放撤銷後不能選取。

**本批仍沒有公開頭像渲染 API 或 Avalonia 頭像顯示**，後續需有界背景解碼／配色快取、畫面角色與世代重查及失效清圖；表情與小地圖未完成。HasVisualAssets=false、一般操作 Held，不連正式服。

## 可重現驗證

`generate_mapping.py` 呼叫實際 Python parser／select_portrait，建立三筆自有 NPC 及 60 種玩家 sex/head 組合。只有產生自有 parser fixture 時暫時替換 Python 測試程序內的預期 digest，C# production 測試必須拒絕同一合成 bytes；沒有正式 pins 替換入口。其餘測試涵蓋 modeling／stat override、未知／零／重複出戰、配色邊界、截斷／重複資料、不可變性、圖片可用性與 owner 撤銷。

這是 Python 語意與自有資料對照，不是正式 NPC／三檔圖資／778 張圖片正向驗收。尚未量測或宣稱新的 FPS、載入秒數或 GPU 畫面一致性。
