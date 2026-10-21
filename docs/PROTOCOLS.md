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
cabinet_count:u16=0, furniture_count:u8=0. C64-2 tool:u16, schedule:u8,
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
Design unlocks, timed/limited recipes, cabinet materials and placed furniture
ingredients are not fabricated; unsupported conditions remain explicitly gated.


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


## v0.5.18 住宅動態場景與離屋限制修正

來源：官方 `Lua/Common/Define.lua` 714～727 行、`Lua/Logic/Stage.lua` 481～486 / 983～985 行、
`Lua/Data/StageData.lua` 235～236 行、`Lua/Logic/Room.lua` 1538～1556 / 2596～2602 行。

- 玩家真實地圖 ID 為 `RetainMinSceneNum=63501` 至 `RetainMaxSceneNum=65500`；
  `FurSysSceneNum={10299,10298,10000}` 是繪製家具樓層用的基礎場景 ID。
  不得以基礎場景 ID 判斷玩家是否已進屋。
- `S12-1/S7-1` 的玩家地圖變化與自家 `S62-4` 所有權快照同時確認才標記已進入；
  登入直接落在住宅動態場景時也能確認。未接收自家資料不可推定已進入。
- 動態房屋 ID 沒有可重用的靜態門編號，也沒有獨立導航圖；地圖面板不會捏造「返回出口」。
- 官方 `Room.SendLeaveCamp` 的 `C65-5` 在原檔被註解掉，尚無使用證據，未建立有效的 LaLa 離屋操作；
  需官方客戶端實際離屋封包／事件證據才能開放，避免錯誤傳送或反覆操作。
