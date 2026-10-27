# P0-1 封包框架（Wire Framing）

> 來源：`wlre/network/wire.py`（已讀取並實際執行產生 golden）。證據等級：`reference_impl`。
> 舊程式的模組註解寫明：外送編碼在取得真實官方客戶端擷取前僅為「候選」；`profile` 註記為
> `observed PCAP; official live client not tested`。**以下規格描述舊程式行為，不代表已與官方客戶端比對。**

## 框架格式

```
明文框架 = C4 C6 | length:u16le | main:u8 | sub:u8 | payload[length-2]
線上位元組 = 明文框架的每個位元組 XOR key
```

| 項目 | 規則 |
|---|---|
| 位元組序 | 全部 little-endian |
| 魔術值 | `C4 C6`（XOR 解碼之後比對） |
| length | 涵蓋 `main + sub + payload`，不含魔術值與 length 自身 |
| length 下限 | `< 2` 視為錯誤（放不下 main/sub） |
| length 上限 | body 長度最大 65535；超過則**編碼端拒絕** |
| XOR key | 單一位元組。舊版預設 `0xAD`（173），收送各自設定（`rx_xor`／`tx_xor`），預設相同 |

## 串流解碼規則（對應 `FrameDecoder`）

1. 收到的每個位元組先做 XOR，再放進緩衝區。
2. 緩衝區 `>= 4` 位元組才開始檢查：魔術值不符 → 錯誤；length `< 2` → 錯誤。
3. 緩衝區不足 `4 + length` 時**什麼都不輸出，等待更多資料**（分片）。
4. 一次收到多個框架（黏包）時依序輸出，順序不變；剩餘不足一個框架的部分留在緩衝區。
5. `finish()`：緩衝區仍有任何位元組 → 錯誤（不完整的最後一個框架）。

### 錯誤後的狀態

魔術值錯誤代表串流已失同步或編碼不同。舊版丟出例外且**不嘗試重新同步**；新版應視同連線層級錯誤，
不得「略過幾個位元組再試」（那樣可能把憑證或其他內容誤當封包）。

## Golden 對應

| 案例 | 驗證的行為 |
|---|---|
| `wire/encode_empty_payload`、`encode_with_payload` | 編碼與 XOR |
| `wire/encode_max_body`、`reject_oversize_body` | body 65535 可、65536 拒絕 |
| `wire/decode_single_frame` | 基本解碼 |
| `wire/decode_fragmented` | 三段分片 |
| `wire/decode_coalesced`、`decode_partial_then_rest` | 黏包與殘段 |
| `wire/reject_bad_magic`、`reject_body_shorter_than_header` | 錯誤判定 |
| `wire/finish_with_incomplete_frame`、`finish_clean` | 結尾檢查 |

## 未決事項

- ❓ 官方伺服器是否始終使用固定 key `0xAD`、是否有握手協商：舊版只靠一份 PCAP（s2c 1848 筆、c2s 9 筆）推得，**未確認**。
- ❓ 舊版沒有對 `main`/`sub` 之外的欄位做版本協商；若官方更新了框架，行為未知，應以 fail-closed 處理。
