# 組隊與煉金實作依據

來源：1262 Lua。

| 功能 | 指令／回覆 |
| --- | --- |
| 邀請／申請 | C13-7／C13-1 + roleId UInt32 |
| 接受拒絕邀請／申請 | C13-8／C13-3 + answer UInt8 + roleId UInt32；1接受、2拒絕 |
| 離隊／踢出 | C13-4 空內容／C13-9 + roleId |
| 指派隊長 | C13-10 + 1 + roleId |
| 接受／拒絕隊長 | C13-10 + 3／C13-10 + 2,2 |
| 隊伍事件 | S13-1,3,4,5,6,9,10,15,16 |
| 組隊開關 | C33-5 + 1開啟、2關閉；S33-2回覆 |
| 附近玩家 | S4-1；S1-1離線；名片私密欄位丟棄 |
| 無技能／一般／中階／高階煉金 | C23-150／14／87／101 |
| 特殊同類材料 | C23-115 |
| 煉金內容 | UInt8欄數 + 每欄UInt8包包格位、UInt8用量 |
| 結果及扣料 | S23-13產物ID UInt16、數量UInt8；S23-9扣料 |

對應原檔：Logic/Team.lua、Protocols_013.lua、Protocols_033.lua、Data/AppearanceData.lua、UI/Logic/UIAlchemy.lua、Protocols_023.lua、Data/SkillData.lua。

原生UI前置判斷尚有任務、載具、特殊場景等條件；本版未模擬未知條件，以伺服器回覆為準。煉金不估算成功率／指定產物。逾時不重送，也不在資料不明時猜測材料已扣除。

材料表來源見README。欄位順序保留使用者所選順序，不假定第一格一定是最終主材；原版會依材質權重判斷。包包空間為保守格數預檢，特殊排列仍可能被伺服器拒絕。


## v0.3.35 text chat

Source: 1262 Lua/UI/Logic/UIChat.lua (SendChat), Lua/Logic/Chat.lua
(CheckCanSpeak; cooldown=2), Lua/Logic/Protocols/Protocols_002.lua and
Lua/Data/AppearanceData.lua (OtherPlayerData:NewChat). No game Lua is executed.

C2-{1,2,3,5,6}: linked-item count=0 (u8), recipient ID (u32, whisper only),
u8 byte length + UTF-16LE text, quoted reply ID=0 (u32).
S2-{1,2,3,5,6,10,17,27,28}: text receives with item/reply parsing. S2-3 includes
recipient ID only when sender equals the local role ID. Stateful live/offline
paths pass that identity explicitly; without it the decoder reports an unread
whisper notice rather than guessing packet offsets. S2-{10,17} include
NewChat profiles; S2-28 has DBId and no business card. S2-13 handles result
codes; S2-21 reports offline whisper targets. S2-0 EncodingType.System is
not assumed to be UTF-16: unverified non-ASCII announcements show a notice.

Normal chat does not enter movement/event gating, but requires initialized
world state. No automatic sends/replies. Sent notifications follow sendall;
only S2 message packets become received chat lines. Interoperability still
requires user testing on the official server.


## v0.3.36 local log and EXP efficiency

Event log rendering is a whitelist, matching the current player role ID or
owned battle units (pid/master_id). Unrelated movement, nearby-player and
team broadcasts are silent. Attack target lists are filtered without mutating
network events. Chat remains in its independent channel panel.

EXP uses S8-1 kind=36,param=0 and S8-2 humanKind=4,kind=36,param=0 for
known local follower indices. S5-47 is Lv:u8, StarCore:u8, Exp:i64 and 30
awakening bytes (1262 Role.ReceiveSecondJobInfo). Local battle start opens
a pending sample; S20-8 commits the last EXP values once. First completion is
a baseline; subsequent valid completions yield rates. Skill EXP is excluded.
Histories contain at most31 samples per identity; all-session gain/count are
aggregates. Negative totals, stage changes and identity changes rebase.

Phase 07 correction: both the first per-role efficiency object and
individual character/companion rows must be re-read after assignment to
State's guarded container. The former code wrote the role ID onto a detached
pre-wrapped temporary, causing every subsequent event to reset all statistics;
newly created rows similarly lost initial EXP and level. Both now update the
authoritative State-owned dictionaries before any battle is sampled.
Roster members not in the current battle do not lose
previously confirmed 10/30-sample history. If a *known participant* has no
S8 EXP evidence when S20-8 arrives, its baseline is invalidated rather than
guessing a zero gain or bridging an unknown interval; previous valid history
is retained for display until a new confirmed baseline is established.
Server-confirmed follower level/stage clears any prior inferred-status flag,
while stale levels may still be inferred and explicitly labeled when the
current EXP lies outside the received level's reference curve.

Reference: current project exp_monitor(4).py (2026-10-15 version1),
window_efficiency, level_need, cumulative and forecast_lines. Curves retain
EXP_Monitor's level-one origin and the unreincarnated 3.1/5 reference
parameters. Do not treat ETA or inferred follower levels as server-confirmed.


## v0.3.37 native-order roaming and smith schedules

AutoPlay.lua autoPosition, SwitchAutoWalk, AutoWalk, ReAutoWalk and GetCanWalk
are the decision sources. Coordinates.to_navigation/to_packet map world X/Z
(dX,dZ) to Int3 changes (dX*1000,dZ*1000), preserving Stage.SCALE_RATIO=0.01
and the inverted packet Y. Sequence is fixed, dwell=0. Python movement and
server arrival confirmation remain distinct. Known fishing/gather/dance/toilet/
sport locks are decoded; this is not a complete Unity movement-controller port.

SmithData_C (1030 x33-byte records after int32 count) is from DataPackage_1262.
Its checksum is in crafting_catalog.json. Layout: SmithData:New; runtime needs
only the extracted JSON, not UnityPy. Room.lua and Protocols_064 define:
C64-1 tool:u16, product:u16, batches:u8, bag_count:u8, [index:u8,count:u8],
cabinet_count:u16, [index:u16,count:u16], furniture_count:u8=0. C64-2 tool:u16, schedule:u8,
human_index:u8,human_id:u32; C64-3 pause:u8; C64-4 delete:u8; C64-6 swap:u8,u8;
C64-10 has no body (normal completion, never paid acceleration).
S64-1 records index:u8,id:u16,time_ms:u32,count:u8,base_time_s:u32 + active:u8;
S64-16 one same record; S64-2/3/5 index:u8; S64-4/6/7/8 index:u8,points:u16.
S64-10 craft NPC index:u8,id:u32; S64-25 success:u8 + indices on success.
Own tool evidence uses S62-4 owner:u32 + [index:u16,FurnitureData:42 bytes],
S62-1 add, S62-2 remove, S62-5 workbench-tool updates and S62-76 retention.
S62 geometry updates continue to invalidate house navigation as before.
C65-1 own role ID:u32 requests entry to an existing tent; it never deploys one.

No optimistic schedule changes. Adds wait for schedule ACK and material drops
in either order. Completion is sent once, accepts a server completion only for
the active row, and auto-next waits for matching product updates rather than
unrelated inventory revisions. Queue replacement/reordering uses server indices
and revisions. Reconnect defaults to no automatic completion/continuation.
Craft materials allocate bag first, then synchronized cupboard stock, with
independent reservations and deductions for both sources. Design unlocks,
timed/limited recipes and placed furniture ingredients remain gated.

Storage transfers from UIRoomStorage.lua use C62-18 (garage deposit), C62-19
(garage withdrawal), and C62-52 (kind 1 cupboard deposit, kind 2 withdrawal).
Garage and deposit rows use u8 indices/counts; cupboard withdrawal rows use
u16 index + u8 count, split at 200 each. Completion requires matching S62-71
and both inventories. See [storage protocol details](room_storage_1262.md).


## v0.3.38 craft browser evidence

ItemData_C from 1262 supplies iconId, openUsed and sizeL/sizeW, matched to the
existing item catalog by ID/name/kind/special/restrict/fit type. Original Sprite
assets s%04d are from MainPackage_1262. Runtime ZIP includes1026 distinct
PNG icons covering1297 product/material/tool IDs. The browser keeps12 cards
and a128-image cache. No requests are sent from browsing, stock checks or
favoriting. Favorites persist locally, at most100 IDs.

Own-house full S62-4 snapshots and personal S62-1(kind2) batches are accepted.
Personal batches become complete at S1-11, while incomplete data remains
unknown. Bag stock, active placed objects, retained objects and queued output
are separate counts. Visible material availability uses the same inventory
reservation/lock checks as the sender. Existing C64 operations are unchanged;
one unopenUsed product is now rejected at the protocol command layer as well.


## v0.4.4 chat evidence

UIChat.SendChat in Lua 1262 writes item count, optional whisper target, Unicode message, replyId, optional quote text / haveAt / quote-item IDs. C2-1/2/3/5/6 use this layout. Cross-server sending remains unsupported.
EmojiData_C: 62 x8-byte records after int32 count, token number is Lua array index. Example [Emoji33] → iconId57 → Emoji_057. Original sprites use animation frame suffixes _1.._4; this release displays the original _1 frame statically.
Images extracted from official https://cgdl.chinesegamer.net/client/wlre.exe, MainPackage 1077 mainpackage_atlas.bundle (e46f9057a086753750de3296ba928301), checked against current 1262 EmojiData mapping. No substitute images.
Packet capture import/replay/profile extraction and standalone packet inspection have been removed. Live protocol decoders and map navigation remain.


## v0.4.6 組織名稱（1262 Lua）

- S39-2：GuildBaseInfoData:New，兩個 Unicode8 字串、成員數 byte、完整 GuildMemberInfo:New 陣列及組織欄位；完整消耗成功才替換名單。
- 每名成員依序讀取 ID、姓名、外觀、裝備、名片、簽名、上線日期、職位、發展值、狀態、寶箱分數、索引。MaxInterest=3、Max_GuildHashTag=3、OrganMaxBuilding=6。
- S39-60：ID + GuildMemberInfo:UpdateInfo，同步名稱；S39-8/6 新增／移除成員，S39-7/10 成功退出／解散時清除目前名單。
- 名稱只來自伺服器資料，保持本服／跨服快取隔離。名單含離線成員，聊天既有 ID 可回填。
- 此路徑只接收原版推送，無新增 C39 查詢或組織操作。未宣稱正式服已驗證。


## v0.4.7 回復與背包同步

- C23-147：MagicBottleKind（HP=3/SP=4）、筆數 1、roleIdx（玩家 0／出戰夥伴索引）、UInt16 消耗量，單次最多 65535，不預扣本機儲存量。
- S23-208-3：類型（1/3=HP、2/4=SP）與 Int32 絕對量；-4 已有基準才套用增量；-5 類型+角色索引清單為使用回覆。使用通知對上目前單筆請求後扣除該次已知量；若先收到完整扣量的絕對快照，不重扣。仍需對應生命／魔力增加才解除等待。
- 儲存槽未知值、戰鬥／戰後事件未結束、已死亡或非出戰夥伴均不送出。
- ItemData_C 1262 全 11287 筆與現有物品表交叉核對，依 ItemData.CanOverlap 產生 item_stackable.json。新增背包物品遵守原版 ItemBox 規則，堆疊上限 200，容量與索引 0 自動分配均依伺服器初始化資料。
- 煉金 S23-13 只記錄結果，TFlow_MixGetThing=3 的 S23-6 才作入包證據；結果、扣料、產物入包可任意順序抵達。完整快照亦可確認非同材料產物的數量增長。未完整確認逾時則停止並標記包包不可靠，不人工恢復。

## 連續煉金節流

每次完整確認結果、入包與扣料後，至少間隔 1 秒才續送。戰鬥或補給等待期間會延後續送時間；逾時仍停止、不重送，並列出未確認的結果、入包或材料格。此間隔為客戶端保守節流，不代表已驗證伺服器冷卻時間；使用者回報「第一輪成功後停止」的確切伺服器回覆仍需實機複測。

## 夥伴出戰／休息

- 來源：使用者提供的 `WLRE_Lua_1262_Decoded_Analysis.zip`，`Lua/UI/Logic/UIPartner.lua` 的 `OnClick_Event_Confirm`（第 66–100 行）與 `OnClick_Event_Rest`（第 185–217 行）。僅靜態核對，不執行 Lua。
- C19-1：夥伴 ID（UInt32 little-endian），不是清單索引。C19-2：空內容，只讓目前出戰夥伴休息；不處理坐騎下馬指令。
- S19-1／4 更新出戰 ID，S19-2 清除；發送時不修改本機出戰狀態。
- 本次介面僅支援非戰鬥操作；戰鬥、伺服器事件、活動、自動戰鬥／徘徊與製作進行時暫停切換，並驗證選取索引與 ID 是否仍相符。僅跟隨型（CanGrow=0）不能出戰。連續指令至少間隔 2 秒（本機保守節流，非原版冷卻規則）。
- 已驗證封包位元組、狀態回覆與介面操作，尚未驗證正式伺服器連線。

## Phase 07: network command and packet observation boundaries

- `command_envelope.py` validates that network-thread commands have a usable,
  bounded `type` field. Invalid envelopes cause `command_rejected` events
  without printing arbitrary submitted command contents. The individual
  game service still validates its own action arguments and activity gates.
- `outbound_observations.py` validates minimum bytes for locally observable
  C50-1/2 and C23-15/147 candidate packets. A command send is only recorded
  after `sendall` returns successfully. Movement C6-1 retains its original
  decoder; S8/S20 and all server protocol semantics are unchanged.
- The XOR frame reader continues to support fragmented and coalesced frames.
  This refactor is *not* a new live-server wire-compatibility claim and does
  not add speculative commands or network retries.


## v0.5.17 1262 帳篷操作（來源與保守限制）

依使用者提供的 `Lua/Logic/Bag.lua`、`Lua/Logic/Stage.lua`、`Lua/Logic/Protocols/Protocols_065.lua` 及 `Lua/Common/Define.lua` 核對：
- `Bag.SendOpenCamp` 傳送無內容 C65-6；`Bag.SendCloseCamp` 傳送無內容 C65-2。
- `Stage.SendClickCamp(id)` 傳送 C65-1 + ownerId:u32；只對目前場景 S65-1/3 確認的自家帳篷開放操作。
- S65-1：單筆 16 bytes，ownerId:u32、tentId:u16、x:u32、y:u32、kind:u8、make:u8；S65-3 為同格式多筆場景帳篷清單，S65-4 為收起玩家 ID:u32。
- S65-2 為本場景帳篷數量上限；S65-8 為無法進入；S65-16 伺服器錯誤代碼，代碼 2 對應無帳篷標記。
- 原版家具場景 `FurSysSceneNum` 為 10299／10298／10000；只有進入指令之後的家具場景與自家 S62-4 家具資料兩者均確認，才顯示「已進入」。
- 本機未知其他場景帳篷實際狀態；缺少伺服器確認時不自行改變已展開／收起或製作排程。操作逾時不盲目重送，重新登入以取得新資料。
- 未取得正式伺服器 E2E 證據；不宣稱場景搭帳篷限制、任務標記或帳篷跨圖狀態已完整驗證。

## 海岸／航海大地圖出口

所有地圖共用實體門配對，不再把 EveDoorLinks 的連線序號或 StageMap EvtID 直接當成 Eve NewDoor 實際門編號。矩形 signType 1／4 使用同版來源點、場景倍率、唯一碰撞範圍及 PlayerTouch；signType 2／3／5 的碰撞形狀由 Prefab 決定，目前只接受與 NewPortal 精確錨點唯一吻合，不推測半徑。資料以實際門 index 為鍵，另存 `link_index` 追溯原連線。標記、名稱或序號相同，都不能代替實體配對。

來源：使用者提供的 1262 Lua `EventData.NewDoor/NewEvent`、`Data.LoadEve`、`EventManager._NewPortal`、`Stage.TransferGridPosition`、`StageObjectData.New`、`PlayerController.OnTriggerEnter` 和 `Role.SendMeetDoor`。矩形只支援 signType 1／4；已確認 PlayerTouch 發生種類旗標為 2。原始門格座標轉封包座標為 `(grid-1)*20*sceneRatio + signOffset*sceneRatio`，不可和 EveDoorLinks 的 `point*sceneRatio` 混用。

小地圖仍透過既有 C20-8 + u16 實際門編號單次嘗試，等待伺服器位置／換圖通知；58001 是 Lua 的航海場景，不會拿來當門編號。載具、距離、任務等條件由伺服器判定；錯誤或逾時不重送。隱藏 Kind=3 標記、獨立路線序號和不明／重疊範圍維持不可直接傳送。

`tests/test_boundary_portals.py` 包含完整合成 v115 門／事件解析、60000→58001 出口、倍率與偏移、缺少一般標記、錯誤或重複事件、範圍歧義、動態 Runtime 清單／按鈕／C20-8 請求，以及拒絕／逾時回歸；正式服航海換圖仍需實際連線驗收。

小地圖顯示另按來源／已知目的場景合併成一個入口，並隱藏未知、無有效名稱與無標記點。代表點優先使用可操作入口，清單和圖示共用同一筆原始記錄；原始路線與事件 ID 不刪除，送出仍由 PortalTravel 重新核對。

只有門事件可對應、`destination_verified` 與 `direct_eligible` 為真，且實際門編號有效的標記才進入主小地圖。已知名稱／位置但尚不能傳送的灰色參考點改為僅留核對報告，不在主清單或圖示中顯示。

歷史 1262 的完整航海入口對照見 [航海入口門編號核對](SAILING_DOOR_IDENTITIES.md)。這份歷史表不參與目前 Runtime 綁定。


## 傳送點名稱與門事件證據

可用傳點若有同版場景名稱，主清單以「前往 目的場景(場景ID)」顯示；原 StageMap 文字與 Eve 門容器名稱另列核對資訊。名稱差異不被視為換圖指令，不因文字相同就通過綁定，也不因「往獅子島／甲蟲島」等文字差異自行改寫門編號或目的地。

NewDoor 的 Big5／CP950 名稱、門觸碰事件 ID，以及相關 NewEvent 的名稱、條件與效果欄位均保留。條件 paraValue 為無號 32 位，效果 paraValue 為有號 32 位，依上傳 Lua EventData.NewEvent 的定義解析。無效名稱保留原始位元組供診斷；無關門事件的效果不展開，以限制記憶體使用。

這些效果明細是原始證據，不代表已解碼換圖效果語意。現有 Lua 提供結果欄位格式，但不足以獨立確認所有換圖效果代碼；`destination_decoded=False` 不會被改成已驗收。目的地配對仍來自已驗證的官方連線和門事件綁定，實際換圖則由伺服器回覆判定；收到不同場景會記為 `different_map`，不回報成功。


## 全地圖目的地錯配修正

已移除一般地圖「StageMap／連線／門事件序號相同即綁定」的處理；正式 Runtime、預覽及位置／目的地低階 API 都採相同的實體配對。只有場景 ID 集合、缺少場景幾何時，不再回傳可執行綁定。

同一門被多條連線認領時不任意保留一條；即使其中一條指向未知場景，也不能先忽略它再宣稱另一條為唯一目的地。獨立 DoorLinkData 的同場景、同來源位置若列出不同目的地，會撤銷唯一目的地綁定，並在唯讀證據列出衝突及候選場景。未配對的原始入口與條件路線仍保留於核對資料。

這些檢查解決本機序號誤配及可見的多目的地衝突，不構成所有官方事件效果已解碼或正式服已實測。伺服器依條件選擇的實際目的地，仍以權威場景回覆確認。


## StageMap-only 入口與無目的地圖片傳送

StageMap Kind=2／3 的來源位置依同版場景倍率轉換，並與唯一的實際 PlayerTouch 門匹配。即使 EveDoorLinks 沒有對應行或整個可選 Bundle 未取得，正式 Bundle Runtime 與 ZIP 預覽仍能保留這些綁定。跨場景 Kind=4 不作門事件補綁。

- Kind=3：EvtID 是目的場景 ID，必須存在於同版場景表；經實體門配對後送出實際門 index，不能將 EvtID 當成 C20-8 參數。
- Kind=2：EvtID 不被當作目的地或實際門 ID。只有正式名稱有效、來源位置／觸碰事件／實際門唯一吻合時，建立 `stage_marker_only=True`、`door_binding_verified=True` 的手動入口。目的地維持 None、`destination_verified=False`、`destination_status=server_decided`，等待伺服器確認，不靠「往航海大地圖」名稱猜填 58001。
- 已有 EveDoorLinks 的模糊或衝突配對，不以 StageMap 名稱重新放行；已知 StageMap 目的地和現有綁定衝突時撤銷綁定。重複標記保留一個實際門；原始標記仍供核對。
- 標籤只附到物理位置配對成功的門，不再按相同連線序號借用。開羅形態的合成測試確認門 1「往航海大地圖」不會借用連線第 1 筆通往埃及野外的資料；門 2 仍指向埃及野外。

目的地有沒有小地圖圖片不再影響傳送按鈕或 `destination_problem`。已核對的門仍會送出單次 C20-8；有圖片時仍檢查來源投影；目前場景也沒有圖片時，清單保留已核對的門並允許單次手動觸發，停用地圖選點。未配對門、戰鬥或事件阻塞等原有檢查仍保留。抵達後以伺服器場景為準，圖片缺少時由既有無圖畫面處理，不捏造圖片或場景。

未知目的場景的 StageMap-only 入口只確認實際門身分，不標示目的地已驗證。同場景位置同步不當成換圖成功；真正抵達通知、拒絕與逾時仍走 PortalTravel 原有處理。正式服開羅當前版本的實際傳送仍待驗收，測試使用合成幾何，未把歷史門號寫死到 Runtime。


### Kind=3／EvtID=0 的有名入口

官方 Lua `StageMapData.Load` 仍把 EvtID=0 的 HiddenPortal 放入場景傳點清單，`UIMain._SetPortalPosition` 對 Kind=3 直接使用標記位置顯示，不要求 EvtID 非零。只有建立明確目的地連線的 `HiddenPortalNew` 才跳過 EvtID=0。這表示「未宣告目的場景」，不能當作整筆入口無效。

修正 StageMap 補綁時將這種 None 當成未知／衝突目標的錯誤：有名標記與唯一實際 PlayerTouch 門配對後，Kind=3／EvtID=0 和 Kind=2 一樣可單次手動觸發，目的地保留空值、等待伺服器確認。主清單、傳送策略及帳篷出口共用相同的未宣告目標分類；不送門 0，也不從名稱推填航海場景 58001。Kind=3 的非零但未定義目的場景仍被拒絕，不當成空白目標放行。

新增的二進位標記重現，在修正前因沒有實際門綁定而失敗；修正後核對實際門 1、保留未知目的地，並涵蓋旁邊 EveDoorLinks 第 1 筆仍配到門 2／埃及野外的情況。桌面案例也檢查零目標標記在清單中可見、可按下且無圖仍可觸發。這證明程式已處理該分支，不宣稱已取得使用者當前官方開羅原始 Bundle 或完成實機傳送。


## 縮小版 NPC 清單配置

NPC 分頁原本將七個操作按鈕及會自動換行增高的說明先放進容器，最後才配置清單；在主畫面 340×280 的小地圖區域，清單可能完全沒有顯示空間。現在將清單放在可伸縮且保留最小高度的獨立列，只常駐「互動」「接續」與「更多操作」。選項、商店、全文、歷史及關閉選項收在更多操作選單，沿用原本的按鈕狀態及事件處理；選單開啟前同步可用狀態，不新增繞過驗證的操作路徑。

說明列維持單行；完整資訊可由「更多操作 → NPC 資訊」開啟可捲動、唯讀視窗。修改不會把 NPC 資料載入失敗當成有資料、不會在選取或開啟選單時送出 NPC 封包，也不啟用商店交易。

`test_npc_compact_list` 在實際 Tk 桌面重現舊版清單未映射的失敗，並驗證修正後至少三列高度、25 筆可捲動、長說明不擠壓清單、視窗放大後清單擴張、原操作啟用狀態與唯讀全文資訊。


## 雙擊 NPC 清單移動至附近

單擊仍只選取 NPC；雙擊清單中實際點到的列，送出本機 `npc_approach` 指令，網路執行緒重新核對目前地圖、官方 NPC 索引／ID 及同版場景倍率。依上傳 Lua `Data.LoadEve` 將 NPC 原始 XY 分別乘上 PosXRatio／PosYRatio，不直接把資料格座標當封包座標。

雙擊前往會停止自動徘徊，避免抵達附近後自動走開。移動目標選在 NPC 周圍約 100 封包座標單位，優先朝向角色一側；若導航不通，僅在附近嘗試其他方向與 60／140 單位距離，所有候選都透過既有 Movement／導航圖做完整路徑驗證。已在附近則停止舊路徑；找不到可達點時回報失敗，不傳送或吸附位置。戰鬥、事件、隊員跟隨、動態障礙及資料版本變更等既有移動檢查繼續適用。

雙擊不送 C20 NPC 對話或商店指令。規劃成功後只沿既有移動排程送出 C6-1；角色的伺服器座標不由 UI 改寫，抵達後仍需手動互動。來源是官方 NPC 靜態位置，未宣稱已完成正式服移動 NPC 追蹤或全部場景實機驗收。

## 移動完成後手動 NPC 互動

UI 與網路分派共用位置證據檢查，避免把 `finished` 誤判為仍在移動。最新伺服器定位可直接使用；未收到新定位時，只有已送出移動步驟、確實走完目標、角色／場景／起始定位封包／官方資料版本／導航修訂均一致且障礙未失效的完成路徑，才允許手動請求 NPC 互動。途中、停止、舊路徑及不完整的移動紀錄仍不可用。

這項許可不改寫伺服器座標、不將 `confirmed_is_current` 設為真，也不自動開啟對話。使用者按下互動後仍走原有確認與 C20-1 流程，由伺服器 S20-74 判定實際距離。舊版缺少版本／導航證據的移動紀錄，需重新定位或重新完成路徑。


## NPC 一般選項後的單次接續

官方 Lua `EventManager.SendInteractListResult` 在送出 C20-9 選項結果後，會設定 `SetCanAskServerEvent(true)`；`UpdateEvent` 下一輪送 C20-6 00，並不等待額外 S20-10。LaLa 原本只送選項且全面抑制手動 NPC 事件的自動接續，會停在 `awaiting_choice`、兩個按鈕皆停用。

目前在已驗證、人工確認的一般選項成功送出後，記錄一次專屬接續許可，在既有封包批次結束／下一輪事件 flush 消耗，單次送出 C20-6 00；不重送 C20-9，也不自動選下一個選項。新對話、商店、未知效果、結束或拒絕會清除此許可；場景變更、戰鬥或會話失效也不送出。若同批收到 S20-10，仍只接續一次。對話逐段接續與商店關閉保留原本操作，不套用此一般選項規則。

回歸以真實 SessionLogic 命令分派／事件 flush 及 S20 解碼重現修正前的兩項失敗，驗證選項封包、單次接續、後續商店效果、同批許可與失效取消。正式服後續內容仍需使用者在更新程式後實際驗收。


## 直接執行操作，不再二次確認

依使用者設定，LaLa UI 的 22 處是／否確認視窗已移除。按下 NPC 互動、選項／商店關閉、製作排程／自訂清單／煉金、能力配點、組隊移除／轉交／離隊、副本建立／加入／離開／開始／進入、協力準備／領獎／放棄／自動領獎，以及下載更新後，通過原本檢查即直接送出。此處僅移除 UI 的第二次確認，不預設接受 NPC 選項或組隊邀請，也不因打開頁面而自動操作。

公開副本房間按加入後直接送出，不開只有確認用途的視窗；私人房間保留密碼輸入，建立房間保留公開／私人、密碼及協力人數設定。數量輸入、配點配置、檔案選擇、NPC 選項與錯誤／資訊提示仍保留。儲存方案及連線設定的原生檔案選擇器停用額外覆寫確認，使用者選定儲存路徑後直接儲存。

網路層的 `confirmed`／`confirm_cost` 等欄位依原格式送出，仍由使用者的操作按鈕觸發；版本、身分、場景、材料、密碼、同步狀態、戰鬥、重複請求及伺服器回覆等檢查不變。不修改 Tk 全域 messagebox，也不替錯誤或未知事件自動回覆。測試將是／否視窗設為一旦呼叫就失敗，以確認直接送出且不可操作狀態仍被拒絕。


## 依指定目標自動接續（預計 v7.1.0）

本次將已實作且能明確判定的後續步驟交給網路執行緒的 `AutomaticFlows`，每輪最多啟動一個新要求。登入後預設開啟，但沒有指定目標時不發起 NPC、製作或副本操作。目標不跨連線／角色沿用。

| 起始目標／操作 | 自動接續 | 邊界 |
| --- | --- | --- |
| 雙擊已驗證 NPC | 完成該次導航後發起一次互動；一般對話／允許繼續時自動接續 | 不使用被替換或停止的路徑；保留正式來源與位置檢查 |
| NPC 傳回一般選項或商店 | 自動開啟對應視窗，選項回答後沿既有單次 C20-6 繼續 | 不任意選答案或商品，既有商店買賣未實作部分仍不啟用 |
| 選定並建立／加入一般副本 | 房主手動開始；確認房間與本人成員名單、收到 started 後才自動入場 | 隊員不代替房主開始；未知房間、拒絕或結果不明不重送 |
| 選定並建立／加入協力副本 | 房主滿員後仍須手動準備／配對；啟用既有免費領獎流程 | 仍驗證可靠背包、四格空位與獎勵旗標，不購買或放棄付費寶箱 |
| 加入製作排程成功 | 等待排程及完整材料扣除確認，再開始／接管既有隊列並沿既有產物確認流程接續 | 原有設備、住宅與材料條件仍須成立；新增失敗不能啟動舊隊列 |
| 顯示副本頁面 | 自動查詢房間；頁面顯示／狀態更新時每模式最多每分鐘一次 | 隱藏頁面不查詢，仍受原本戰鬥／事件檢查 |
| 遠征、煉金、戰鬥 AI、傳點、已啟動自訂製作 | 延用既有自動派遣／下令／移動／製作接續 | 既有啟動目標與設定不猜值、不重置 |

主畫面目前活動顯示 NPC／副本／製作的等待或停止原因，可按「暫停自動接續」取消尚未送出的目標，停止未來製作／自訂清單及協力免費領獎接續；不偽造已送出要求被取消，不解除伺服器事件或庫存保留。重新開啟後需重新指定起始目標。既有 AI／遠征／煉金停止按鈕維持各自控制。

對話選項、商品及數量、配點配置、帳號／角色、密碼與起始目標是設定，仍由使用者選擇；來源不明、未實作效果、角色／資料版本改變、逾時或伺服器拒絕是停止條件，不以自動化繞過。製作外部環境尚未就緒時不自動猜測設備、變更帳篷或搬動材料。正式服全流程與安裝包驗收仍需分開執行。
