# 傳送點完整流程檢查（2026-11-02）

後續修正狀態（同日）：StageMap-only 入口補綁及目的地缺圖片禁止傳送這兩項已加入程式與回歸測試。Kind=3 保留明確目的場景；Kind=2 僅核對實際門，目的地不明時允許有正式名稱的單次手動觸發，等待伺服器場景確認。兩條 Runtime 載入路徑均保留無 EveDoorLinks 的 StageMap 綁定。詳見 [協定說明](PROTOCOLS.md)。以下表格與缺漏敘述保留為原檢查基準的紀錄，不能當成修正後狀態；DoorLinkData-only 補綁、完整 Prefab／效果語意與正式服實測仍未完成。

再補正：前一輪 StageMap-only 修正仍漏掉 Kind=3／EvtID=0。官方 Lua 允許顯示這種有名傳點，不能因缺目的場景就刪除。現在已納入同一個「實際門已核對、目的地由伺服器確認」流程；非零未知目的地與衝突仍不放行。新增零值二進位標記及桌面清單重現。尚未取得使用者當前開羅資源，因此沒有把這個程式缺漏直接等同於已證實的當前官方開羅資料格式。

檢查程式基準：PR #65 提交 `793e91f1f37eed1c81cd924134a78c0c2b801c4d`（本機同樹提交 `cba9973`）。這份報告記錄檢查結果，沒有把未完成項目改標成完成。

結論：序號與實際門 ID 的混用已修正，但入口來源整合仍不完整。目前不能宣稱全地圖／所有往航海大地圖入口已支援。開羅漏點是其中一種可確認的缺漏。

## 證據範圍

- 當前程式：正式 Bundle／ZIP 載入器、門解析、連線解析、物理配對、名稱、顯示、分組、傳送及權威回覆處理。
- 上傳 Lua：`StageMapData.New/Load`、`EveDoorLinksData.New/HiddenPortalNew`、`Data.LoadEveDoorLinks`、`EventData.NewDoor/NewEvent`、`EventManager._NewPortal`、`UIMain._SetPortalPosition`、`Role.SendMeetDoor`。
- 歷史 1262：既有 `Portal_Review_1262.html` 全部 2,579 筆入口，交叉核對其原始門容器清單。
- 沒有當前官方原始 Eve／Bundle 和登入環境。下面的數量與入口列表是歷史資料事實，不代表現在官方版本的數量或實機結果。

## 仍未完成的程式路徑

| 項目 | 已確認行為／影響 | 責任位置 |
| --- | --- | --- |
| 僅有 StageMap 的入口 | 實體配對只遍歷 EveDoorLinks。Kind=3 即使有已知目的場景及可配對位置，也仍只建立唯讀 H 標記，不能補成實際門入口。 | `boundary_portals.py`、`portal_evidence_1275.py`、`portals.py` |
| 僅有 DoorLinkData 的路線 | 已解析其來源／目的場景與座標，但目前只用來檢查現有綁定衝突，不建立缺失的門綁定。 | `reconcile_route_conflicts` 及兩條 Runtime 載入路徑 |
| 缺少 EveDoorLinks／StageMap | 任一缺少時，現有流程不會用其餘已驗證來源獨立補綁；標籤／路線參考不等於可操作入口。 | `bundle_runtime_1275.py`、`preview_1275.py` |
| 未知目的地一律從主畫面隱藏 | 原資料還在，但使用者看不到有門容器卻未取得目的地的入口。開羅案例會落到這類；僅改顯示名稱不會補上綁定。 | `marked_portals` |
| Prefab 門碰撞形狀尚未完整取得 | signType 2／3／5 僅接受來源點和門錨點完全相同；合法碰撞範圍內但不在精確錨點的入口仍可能配不到。 | `door_anchor`、`boundary_portal_bindings` |
| 換圖效果語意未完整解析 | 雖保留事件條件／效果欄位，仍標示 `destination_decoded=False`；無法單憑門名稱或數值欄位斷定所有條件落點。 | `doors_1275.py` |
| 目的地圖片仍是傳送限制 | 已驗證門若缺目的地小地圖圖片，`destination_problem` 仍拒絕送出；圖片完整性和門事件正確性是兩個不同判斷。 | `portal_policy.py` |
| 核對報告的版本與完成度 | `source_revision` 仍固定 1275；`all_sources_available` 只表示 StageMap 和 EveDoorLinks 已解析，並不代表所有路線、事件效果或入口都完成。 | `portal_coverage.py` |

## 最小重現

以合成資料建立場景 12500、實際門 1、有效 PlayerTouch，以及 Kind=3／目標 58001 的地圖標記；標記換算座標在門的唯一矩形範圍內。EveDoorLinks 只有場景標頭、沒有入口行。

- `read_only_stage_portal_markers` 正確解析出目的地 58001、位置 (120, 4400)。
- `reconcile_touch_bindings` 仍回傳 0 筆可操作綁定。
- 再提供同場景／同位置／目標 58001 的已解析 DoorLinkData 路線給 `reconcile_route_conflicts`，仍是 0 筆綁定。
- 這是證明兩種來源尚未補綁的合成重現，不是宣稱開羅目前官方標記一定是 Kind=3。歷史開羅報告沒有保存足夠欄位確認其原始 Kind。

## 歷史資料全量核對

| 來源 | 筆數 | 目的地空值 | 標為 confirmed | 其他狀態 |
| --- | --- | --- | --- | --- |
| EveDoorLinks | 2363 | 0 | 2350 | ambiguous 4、guide_only 4、no_touch 5 |
| StageMapData | 135 | 96 | 101 | unmatched 29、ambiguous 5 |
| DoorLinkData | 81 | 0 | 63 | unmatched 14、no_touch 1、ambiguous 3 |

共有 96 筆目的地空值，全部來自 StageMapData；其中 71 筆同時被歷史報告標為 confirmed。這裡的 confirmed 只表示門容器／觸碰事件配對，不能等同於目的地已知或實機成功。
另外 65 筆非 confirmed（43 unmatched、12 ambiguous、6 no_touch、4 guide_only）是另一個統計維度，不能用「只剩 65 筆」概括全部缺漏。
門容器交叉核對：2,514 筆 confirmed 的門容器名稱均對上同份容器清單，且其路線事件 ID 都包含於該門的觸碰事件集合。部分門另含點擊事件，事件清單不完全相等不代表錯配。
有 23 個門容器對應多個明確目的地，共 63 筆路線，歷史資料均有 conditional_destination 標記。不能因同一門 ID 就認為必定是固定目的地。

## 名稱指向航海、但目的場景未填的歷史標記

共 16 筆，其中 14 筆門配對標為 confirmed，2 筆尚未取得門編號。這些不是 16 筆已證明可以傳往 58001 的入口；名稱僅指出需要追查的線索。

| 場景 ID | 場景 | 標記名稱 | 歷史門編號 | 狀態 |
| --- | --- | --- | --- | --- |
| 11002 | 幽靈船甲板 | 往航海大地圖 | 2 | confirmed |
| 11049 | 麥哲倫艦隊 | 往航海大地圖 | 2 | confirmed |
| 11113 | 庫克船甲板 | 往航海大地圖 | 1 | confirmed |
| 12286 | 鬼島洞窟 | 往航海大地圖 | 1 | confirmed |
| 12300 | 加爾喀達 | 往航海大地圖 | 1 | confirmed |
| 12367 | 雪島洞穴一層 | 往航海大地圖 | 1 | confirmed |
| 12500 | 開羅 | 往航海大地圖 | 1 | confirmed |
| 12700 | 非洲村落 | 往航海大地圖 | 1 | confirmed |
| 12705 | 奴隸船甲板 | 往航海大地圖 | 1 | confirmed |
| 12850 | 邪馬台國 | 往航海大地圖 | 未確認 | unmatched |
| 12875 | 千葉楓樹林一 | 往航海大地圖 | 1 | confirmed |
| 13023 | 避風塘 | 往航海大地圖 | 4 | confirmed |
| 11055 | 鄭和艦隊 | 往航海大地圖 | 2 | confirmed |
| 11152 | 巴尼亞天空之城 | 往航海大地圖 | 1 | confirmed |
| 11199 | 船甲板 | 往航海大地圖 | 未確認 | unmatched |
| 15100 | 破浪號甲板 | 往航海大地圖 | 1 | confirmed |

開羅特例：歷史 `StageMapData:12500:1` 在 (6354, 7680) 配到實際門 1、觸碰事件 1，但 destination 為空。相同場景的 `EveDoorLinks:12500:1` 則在 (184, 7960) 配到實際門 2、目的地 60014（埃及野外）。兩者不能按第 1 筆合併。

## 已具備的防護與功能

- 全地圖實體配對已移除序號相同即認定實際門 ID 的舊假設；有完整證據時，清單、座標及 C20-8 取同一實際門資料。
- 同來源／同目的場景只保留一個可操作代表；原始路線與其他抵達位置仍保留。
- 同一門多連線、以及同一來源點的 DoorLinkData 目的地衝突，不任意選第一筆。
- 名稱和內部標籤不同不會自行更改門 ID 或目的地。歷史甲蟲島／往獅子島屬待查名稱差異，不能只憑文字判定門錯誤。
- 單次 C20-8 使用實際門編號；沒有本機假換圖、逾時自動重送或非預期場景誤報成功。

## 修正與驗收的順序

1. 將 EveDoorLinks、已知目的地的 StageMap Kind=3、DoorLinkData 正規化成各自保留來源的候選入口；按同版實體門匹配並交叉檢查衝突。
2. 普通 StageMap 標記沒有目的場景時，保留未確認狀態；不能從名稱猜 58001，也不能從其他入口的連線序號借用目的地。
3. 取得 Prefab 碰撞定義、換圖效果代碼及當前官方資料，補齊不能靠現有欄位證明的入口與條件分支。
4. 每次更新報告使用當前版本識別，分開列出來源完整、門身分、目的地、可操作及伺服器實測狀態；為每筆排除提供原因。
5. 對開羅及下列所有未確認案例重新產生同版報告，再進行正式服抵達驗收；單元測試與 CI 通過不能取代這一步。

## 附錄：全部目的地空值記錄

| ID | 場景 | 名稱 | 門編號 | 門配對狀態 |
| --- | --- | --- | --- | --- |
| StageMapData:10031:2 | 星之方舟主控室 | 離開方舟 | 2 | confirmed |
| StageMapData:10032:2 | 星之方舟主控室 | 離開方舟 | 2 | confirmed |
| StageMapData:10033:2 | 星之方舟主控室 | 離開方舟 | 2 | confirmed |
| StageMapData:10034:2 | 星之方舟主控室 | 離開方舟 | 2 | confirmed |
| StageMapData:10035:2 | 星之方舟主控室 | 離開方舟 | 2 | confirmed |
| StageMapData:10041:1 | 魔物塔第一層 | 魔物塔第二層 | 2 | confirmed |
| StageMapData:10042:2 | 魔物塔第二層 | 魔物塔第三層 | 2 | confirmed |
| StageMapData:10043:2 | 魔物塔第三層 | 魔物塔第四層 | 2 | confirmed |
| StageMapData:10044:2 | 魔物塔第四層 | 魔物塔第五層 | 2 | confirmed |
| StageMapData:10045:2 | 魔物塔第五層 | 魔物塔第六層 | 2 | confirmed |
| StageMapData:10046:2 | 魔物塔第六層 | 魔物塔第七層 | 2 | confirmed |
| StageMapData:10047:2 | 魔物塔第七層 | 魔物塔第八層 | 2 | confirmed |
| StageMapData:10048:2 | 魔物塔第八層 | 魔物塔第九層 | 2 | confirmed |
| StageMapData:10049:2 | 魔物塔第十一層 | 魔物塔第十二層 | 2 | confirmed |
| StageMapData:10050:2 | 魔物塔第九層 | 魔物塔第十層 | 2 | confirmed |
| StageMapData:10051:2 | 魔物塔第十層 | 魔物塔第十一層 | 2 | confirmed |
| StageMapData:10052:2 | 魔物塔第十二層 | 魔物塔第十三層 | 2 | confirmed |
| StageMapData:10054:2 | 魔物塔第十三層 | 魔物塔第十四層 | 2 | confirmed |
| StageMapData:10055:2 | 魔物塔第十四層 | 魔物塔第十五層 | 2 | confirmed |
| StageMapData:10056:2 | 魔物塔第十五層 | 魔物塔第十六層 | 2 | confirmed |
| StageMapData:10082:1 | 海底 | 海溝右一 | 1 | confirmed |
| StageMapData:10082:2 | 海底 | 海溝左一 | 2 | confirmed |
| StageMapData:10104:2 | 魔物塔第十六層 | 魔物塔第十七層 | 1 | confirmed |
| StageMapData:10105:2 | 魔物塔第十七層 | 魔物塔第十八層 | 1 | confirmed |
| StageMapData:10106:2 | 魔物塔第十八層 | 魔物塔第十九層 | 1 | confirmed |
| StageMapData:10107:2 | 魔物塔第十九層 | 魔物塔第二十層 | 1 | confirmed |
| StageMapData:10108:2 | 魔物塔第二十層 | 魔物塔第二十一層 | 2 | confirmed |
| StageMapData:10109:2 | 魔物塔第二十一層 | 魔物塔第二十二層 | 1 | confirmed |
| StageMapData:10110:2 | 魔物塔第二十二層 | 魔物塔第二十三層 | 1 | confirmed |
| StageMapData:10111:2 | 魔物塔第二十三層 | 魔物塔第二十四層 | 1 | confirmed |
| StageMapData:10112:2 | 魔物塔第二十四層 | 魔物塔第二十五層 | 1 | confirmed |
| StageMapData:11002:1 | 幽靈船甲板 | 往航海大地圖 | 2 | confirmed |
| StageMapData:11005:13 | 基督村-東 | 往基督村漁夫家 | 3 | confirmed |
| StageMapData:11049:2 | 麥哲倫艦隊 | 往航海大地圖 | 2 | confirmed |
| StageMapData:11078:1 | 恐龍巢穴中段 | 往恐龍巢穴深處 | 2 | confirmed |
| StageMapData:11091:2 | 黑風洞 | 往海盜船甲板 | 未確認 | unmatched |
| StageMapData:11113:1 | 庫克船甲板 | 往航海大地圖 | 1 | confirmed |
| StageMapData:11148:2 | 幽冥之地深處 | 往幽冥之地祭壇 | 未確認 | unmatched |
| StageMapData:11168:1 | 海溝左一 | 海底 | 2 | confirmed |
| StageMapData:11168:2 | 海溝左一 | 海溝左二 | 1 | confirmed |
| StageMapData:11169:1 | 海溝左二 | 海溝左一 | 1 | confirmed |
| StageMapData:11169:2 | 海溝左二 | 海溝左三 | 2 | confirmed |
| StageMapData:11170:1 | 海溝左三 | 海溝左二 | 1 | confirmed |
| StageMapData:11170:2 | 海溝左三 | 海溝左四 | 2 | confirmed |
| StageMapData:11171:1 | 海溝左四 | 海溝左三 | 1 | confirmed |
| StageMapData:11172:1 | 海溝右一 | 海底 | 2 | confirmed |
| StageMapData:11172:2 | 海溝右一 | 海溝右二 | 1 | confirmed |
| StageMapData:11173:1 | 海溝右二 | 海溝右三 | 1 | confirmed |
| StageMapData:11173:2 | 海溝右二 | 海溝右一 | 2 | confirmed |
| StageMapData:11174:1 | 海溝右三 | 海溝右四 | 1 | confirmed |
| StageMapData:11174:2 | 海溝右三 | 海溝右二 | 2 | confirmed |
| StageMapData:11175:1 | 海溝右四 | 海溝右三 | 未確認 | unmatched |
| StageMapData:12250:8 | 京都 | 往溫泉屋 | 未確認 | unmatched |
| StageMapData:12286:1 | 鬼島洞窟 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12300:1 | 加爾喀達 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12300:3 | 加爾喀達 | 往山洞密道 | 未確認 | unmatched |
| StageMapData:12367:1 | 雪島洞穴一層 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12500:1 | 開羅 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12700:1 | 非洲村落 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12705:2 | 奴隸船甲板 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12800:1 | 雅典城 | 地中海 | 1 | confirmed |
| StageMapData:12816:2 | 第二宮 | 往聖殿走道二 | 未確認 | unmatched |
| StageMapData:12817:2 | 第一宮 | 往聖殿走道一 | 未確認 | unmatched |
| StageMapData:12818:2 | 第三宮 | 往聖殿走道三 | 未確認 | unmatched |
| StageMapData:12819:2 | 第四宮 | 往聖殿走道四 | 未確認 | unmatched |
| StageMapData:12820:2 | 第五宮 | 往聖殿走道五 | 未確認 | unmatched |
| StageMapData:12821:2 | 第六宮 | 往聖殿走道六 | 未確認 | unmatched |
| StageMapData:12822:2 | 第七宮 | 往聖殿走道七 | 未確認 | unmatched |
| StageMapData:12823:2 | 第八宮 | 往聖殿走道八 | 未確認 | unmatched |
| StageMapData:12824:2 | 第九宮 | 往聖殿走道九 | 未確認 | unmatched |
| StageMapData:12825:2 | 第十宮 | 往聖殿走道十 | 未確認 | unmatched |
| StageMapData:12826:2 | 第十一宮 | 往聖殿走道十一 | 未確認 | unmatched |
| StageMapData:12827:2 | 第十二宮 | 往聖殿走道十二 | 未確認 | unmatched |
| StageMapData:12850:1 | 邪馬台國 | 往航海大地圖 | 未確認 | unmatched |
| StageMapData:12875:1 | 千葉楓樹林一 | 往航海大地圖 | 1 | confirmed |
| StageMapData:12905:2 | 凝視之森 | 往地中海 | 1 | confirmed |
| StageMapData:13023:1 | 避風塘 | 往航海大地圖 | 4 | confirmed |
| StageMapData:13200:1 | 羅馬 | 往地中海 | 未確認 | unmatched |
| StageMapData:60001:4 | 北島-南 | 往南北島地道一 | 未確認 | ambiguous |
| StageMapData:60012:2 | 台灣 | 往樹洞 | 10 | confirmed |
| StageMapData:10073:1 | 奪寶第一關 | 往國會大樓四樓 | 未確認 | unmatched |
| StageMapData:10074:1 | 奪寶第二關 | 往國會大樓四樓 | 1 | confirmed |
| StageMapData:10075:1 | 奪寶第三關 | 往國會大樓四樓 | 1 | confirmed |
| StageMapData:10076:1 | 奪寶第四關 | 往國會大樓四樓 | 1 | confirmed |
| StageMapData:10077:1 | 奪寶第五關 | 往國會大樓四樓 | 1 | confirmed |
| StageMapData:10078:1 | 奪寶第六關 | 往國會大樓四樓 | 未確認 | ambiguous |
| StageMapData:11055:1 | 鄭和艦隊 | 往航海大地圖 | 2 | confirmed |
| StageMapData:11055:2 | 鄭和艦隊 | 往鄭和艦船艙走道 | 1 | confirmed |
| StageMapData:11061:1 | 酒窖秘道 | 往釀酒師傅的家 | 1 | confirmed |
| StageMapData:11061:2 | 酒窖秘道 | 往基督村酒吧 | 3 | confirmed |
| StageMapData:11120:1 | 地下通道 | 往地下通道 | 1 | confirmed |
| StageMapData:11152:1 | 巴尼亞天空之城 | 往航海大地圖 | 1 | confirmed |
| StageMapData:11152:2 | 巴尼亞天空之城 | 天空之城內部 | 未確認 | ambiguous |
| StageMapData:11199:1 | 船甲板 | 往航海大地圖 | 未確認 | unmatched |
| StageMapData:12801:1 | 大神殿 | 聖殿走道十二 | 未確認 | unmatched |
| StageMapData:15100:1 | 破浪號甲板 | 往航海大地圖 | 1 | confirmed |

## 附錄：全部非 confirmed 記錄

| ID | 名稱 | 目的場景 | 狀態 |
| --- | --- | --- | --- |
| EveDoorLinks:11009:3 | 往 地下密室 | 11154 | ambiguous |
| DoorLinkData:11016:59 | 往 巴豆島 | 15083 | unmatched |
| EveDoorLinks:11034:2 | 往 南北島地道二 | 11035 | guide_only |
| EveDoorLinks:11071:1 | 往 台灣 | 60012 | no_touch |
| StageMapData:11091:2 | 往海盜船甲板 | 未確認 | unmatched |
| StageMapData:11134:2 | 萬魔冰洞 | 11133 | unmatched |
| StageMapData:11148:2 | 往幽冥之地祭壇 | 未確認 | unmatched |
| StageMapData:11175:1 | 海溝右三 | 未確認 | unmatched |
| DoorLinkData:11196:58 | 往 時空裂縫 | 15082 | unmatched |
| DoorLinkData:12122:40 | 往 年獸洞穴1層 | 12133 | no_touch |
| DoorLinkData:12147:37 | 往 火龍迷宮一層 | 15049 | unmatched |
| DoorLinkData:12147:39 | 往 麒麟神殿 | 13000 | unmatched |
| StageMapData:12164:1 | 往瑪雅部落 | 12150 | unmatched |
| StageMapData:12212:1 | 火山迷宮三 | 12211 | unmatched |
| EveDoorLinks:12250:15 | 往 京都城堡一樓 | 12251 | no_touch |
| StageMapData:12250:8 | 往溫泉屋 | 未確認 | unmatched |
| EveDoorLinks:12293:2 | 往 監禁之窟 | 12294 | no_touch |
| StageMapData:12300:3 | 往山洞密道 | 未確認 | unmatched |
| DoorLinkData:12379:18 | 往 研究室 | 12380 | ambiguous |
| EveDoorLinks:12537:1 | 往 帕奈西的家 | 12502 | ambiguous |
| DoorLinkData:12670:63 | 往 幽幻禁地 | 12677 | unmatched |
| StageMapData:12816:2 | 往聖殿走道二 | 未確認 | unmatched |
| StageMapData:12817:2 | 往聖殿走道一 | 未確認 | unmatched |
| StageMapData:12818:2 | 往聖殿走道三 | 未確認 | unmatched |
| StageMapData:12819:2 | 往聖殿走道四 | 未確認 | unmatched |
| StageMapData:12820:2 | 往聖殿走道五 | 未確認 | unmatched |
| StageMapData:12821:2 | 往聖殿走道六 | 未確認 | unmatched |
| StageMapData:12822:2 | 往聖殿走道七 | 未確認 | unmatched |
| StageMapData:12823:2 | 往聖殿走道八 | 未確認 | unmatched |
| StageMapData:12824:2 | 往聖殿走道九 | 未確認 | unmatched |
| StageMapData:12825:2 | 往聖殿走道十 | 未確認 | unmatched |
| StageMapData:12826:2 | 往聖殿走道十一 | 未確認 | unmatched |
| StageMapData:12827:2 | 往聖殿走道十二 | 未確認 | unmatched |
| StageMapData:12850:1 | 往航海大地圖 | 未確認 | unmatched |
| StageMapData:12859:2 | 往主祭殿一樓 | 12851 | unmatched |
| EveDoorLinks:12962:1 | 往 航海大地圖 | 58001 | ambiguous |
| StageMapData:13200:1 | 往地中海 | 未確認 | unmatched |
| StageMapData:15030:2 | 往地下水道中段 | 15031 | unmatched |
| StageMapData:15031:2 | 往地下水道後段 | 15032 | unmatched |
| StageMapData:15032:2 | 往地下水道中樞 | 15041 | unmatched |
| EveDoorLinks:15043:2 | 往 瑪雅地下裂縫 | 15043 | guide_only |
| EveDoorLinks:15044:2 | 往 瑪雅地下裂縫 | 15044 | guide_only |
| EveDoorLinks:15045:2 | 往 瑪雅地下裂縫 | 15045 | guide_only |
| DoorLinkData:15051:38 | 往 火龍迷宮二層 | 15052 | unmatched |
| StageMapData:15052:2 | 火龍迷宮三層 | 15053 | ambiguous |
| StageMapData:15053:2 | 火龍迷宮四層 | 15054 | ambiguous |
| DoorLinkData:15060:44 | 往 大蛇的腸 | 15061 | unmatched |
| DoorLinkData:15060:45 | 往 大蛇的胃 | 15062 | unmatched |
| DoorLinkData:15060:46 | 往 大蛇的毒囊 | 15063 | unmatched |
| DoorLinkData:15060:47 | 往 大蛇的動脈 | 15064 | unmatched |
| DoorLinkData:15060:48 | 往 大蛇的靈識 | 15065 | unmatched |
| DoorLinkData:15093:66 | 往 右側洞穴 | 15108 | ambiguous |
| StageMapData:60001:4 | 往南北島地道一 | 未確認 | ambiguous |
| EveDoorLinks:60002:17 | 往 攻城戰第一關 | 10065 | no_touch |
| EveDoorLinks:60002:18 | 往 南島-北 | 60002 | ambiguous |
| DoorLinkData:60004:19 | 往 地下水道前段 | 15030 | unmatched |
| DoorLinkData:60006:9 | 往 澳洲熔岩洞穴 | 15005 | unmatched |
| EveDoorLinks:60008:2 | 往 航海大地圖 | 58001 | no_touch |
| DoorLinkData:60008:21 | 往 夏威夷祭典會場 | 15048 | unmatched |
| StageMapData:10073:1 | 往國會大樓四樓 | 未確認 | unmatched |
| StageMapData:10078:1 | 往國會大樓四樓 | 未確認 | ambiguous |
| StageMapData:11152:2 | 天空之城內部 | 未確認 | ambiguous |
| DoorLinkData:11152:62 | 往 天空之城內部 | 15006 | ambiguous |
| StageMapData:11199:1 | 往航海大地圖 | 未確認 | unmatched |
| StageMapData:12801:1 | 聖殿走道十二 | 未確認 | unmatched |

## 本次驗證

在上述程式基準重新執行完整本機回歸：1,451 項，1,309 通過、142 依環境跳過。新報告通過嚴格儲存庫稽核：53 份 Markdown、233 條本地連結，無失效連結或重複內容檔案；git diff --check 通過。這些是本機檢查結果，不代表上述缺漏已修正或正式服已驗收。

## 來源指紋

- 歷史 HTML SHA-256：`3fc665be1263f82dac9b1ca63de92d2e3991d451181616e6d2870bd669539e16`
- 上傳 Lua ZIP SHA-256：`3e53db47ea22294207bfbc230322dbcc0429e4a4c94c7f67aacc924e18d77fce`
