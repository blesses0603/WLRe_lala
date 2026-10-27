# P0-2 登入、選角與初始化同步

> 來源：`wlre/network/protocol.py`、`layouts.py`、`client.py`（已讀取；封包編解碼已實際執行產生 golden）。
> **會話層反應（下方「狀態機」）是讀程式碼整理的，尚未以可重播的情境測試驗證**，golden 目前只涵蓋編解碼。

## 封包編號（P0 範圍）

| 方向 | 編號 | 名稱（事件 type） | 欄位 |
|---|---|---|---|
| C→S | C63-7 | 登入 | `kind:u8, 0:u8, platform:u8, language:u8, len:u8, account(ascii), len:u8, password(ascii)` |
| C→S | C63-2 | 選角 | `index:u8`（只允許 1 或 2） |
| C→S | C63-5 | 心跳回覆 | 空 payload |
| C→S | C12-1、C3-2 | 世界就緒確認 | 空 payload，見下方狀態機 |
| S→C | S63-7 | `login_result` | `result:u8, login_kind:u8` |
| S→C | S63-1 | `role_list_available` | 角色清單，見下 |
| S→C | S1-23 | `heartbeat_request` | 空 payload |
| S→C | S1-4 | `account_identity` | `account_id:u32` + 3 個 `len:u8 + bytes`（**只保留 id，字串丟棄**） |
| S→C | S3-1 | `world_player` | 見 `layouts.world_player` |
| S→C | S1-11 | `initial_data_complete` | 空 payload |

字串型別 `unicode8` = `len:u8`（位元組數，必為偶數）+ UTF-16LE，尾端 `\x00` 會被去除。

### 登入 `login_kind`

| 值 | 用途 | 備註 |
|---|---|---|
| 0 | 帳號驗證（`verify_account`，獨立連線） | 回覆的 `login_kind` 必須為 0，否則視為錯誤 |
| 2 | 正式登入 | 回覆的 `login_kind` 必須為 2 |

`result != 0` 一律視為登入被拒絕。**result 各數值的意義，舊版沒有文件，未知。**

### 帳密編碼

只接受 ASCII，空值拒絕。非 ASCII 的原生編碼（Lua `WriteStrToChar`）**尚未獨立驗證**，舊版選擇拒絕而不是猜測。
新版必須維持這個行為（見 `login/reject_non_ascii`）。

## 角色清單（S63-1）每筆欄位

`index:u8, name:unicode8, level:u8, element:u8, max_hp:u32, hp:u32, max_sp:u32, sp:u32, exp:i64, gold:u32,
sex:u8, head:u8, palette1:u32, palette5:u32, degree:u8, job:u8, scene:u16, delete_time:f64, locked:u8`，
接著九個加成：`core_hp:u32, core_sp:u32, emblem_hp:u32, emblem_sp:u32, ride_hp:u16, star_hp:i32, star_sp:i32,
relation_hp:u32, relation_sp:u32`。

- 顯示用的 `max_hp`／`max_sp` = 原值 + 所有名稱以 `_hp`／`_sp` 結尾的加成總和。
- `index` 不是 1 或 2 → 整包拒絕。任何截斷 → 整包拒絕，**不回傳部分清單**。
- 舊版註解：此佈局「cross-checked against real login/battle captures」。本專案**未重做**這個比對。

## 嚴格解碼原則（整個專案通用）

1. 欄位讀不完 → 拒絕；讀完還有剩餘位元組 → 拒絕（`unexpected trailing bytes`）。
2. 未知的 `(main, sub)` → 只回報 `payload_bytes`，**不回傳內容**（可能含憑證）。
3. 例外：少數封包刻意容忍，且各自有註記：S51-1 長度不是 7 的倍數時**整包丟棄、不更新 HP/SP、不斷線**
   （`decode/battle_attribute_partial_record_dropped`，優先級 P2）。

## 會話狀態機（讀自 `SessionLogic.receive`，尚無 golden scenario）

```
connected --送出 C63-7--> (等待)
收到 S1-23           -> 送出 C63-5
收到 S63-7           -> result != 0：登入被拒（終止）；login_kind != 2：協定錯誤（終止）；否則 authenticated
收到 S63-1 且已指定角色 -> 送出 C63-2(index)
state.player 與 initial_data_complete 兩者皆就緒（只做一次）-> 送出 C12-1、C3-2，phase = world_ready
```

連線細節：TCP 連線後，若有登入請求，等 0.1 秒再送出；之後讀取逾時 0.05 秒輪詢。

## 待補的 scenario（階段 0 之後）

1. 心跳：收到 S1-23 → 恰好送出一個 C63-5。
2. 登入被拒：result≠0 → 終止且不送出任何後續封包。
3. 世界就緒：S3-1 與 S1-11 以任意順序到達 → C12-1、C3-2 只送出一次。
4. 重連：新連線建立全新 State，舊的 pending／保留紀錄不沿用。

## Golden 對應

`login/*`（編碼與拒絕）、`decode/login_result_*`、`decode/heartbeat_request`、`decode/initial_data_complete`、
`decode/account_identity_drops_credentials`、`decode/role_list_*`、`decode/world_player`、`decode/gold_*`、
`decode/unknown_packet_hides_payload`。
