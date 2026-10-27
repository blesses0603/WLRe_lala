# 與語言無關的規格（spec）

新 LaLa 的行為規格與測試資料。目的：讓 Kotlin（或任何語言）的實作可以**對著資料驗收**，
而不是憑記憶重新推導協定。舊版 Python 只是參考實作。

## 內容

| 路徑 | 內容 |
|---|---|
| `behavior/` | 文字規格（封包框架、登入與會話…），每份標明來源與未決事項 |
| `golden/` | golden packet 測試案例（JSON） |
| `verify_golden.py` | **獨立驗證器**：不引用舊程式的第二份實作，用來確認規格自洽 |
| `../tools-python/gen_golden.py` | 由舊版參考實作產生 golden（唯一會 import `wlre` 的地方） |

## 案例格式

每個案例一個 JSON 檔（下例為縮短版：實際的 `event` 還包含 `main`、`sub` 欄位）：

```json
{ "id": "decode/gold_snapshot", "priority": "P0", "type": "decode",
  "packet": { "main": 26, "sub": 4, "payload_hex": "d2040000" },
  "expected": { "result": "ok", "event": { "type": "gold_snapshot", "amount": 1234 } },
  "source": { "grade": "reference_impl", "ref": "…" }, "notes": "" }
```

| `type` | 輸入 | 比對的 `expected` |
|---|---|---|
| `wire_encode` | `packet`、`key` | `result`、`frame_hex` |
| `wire_encode_oversize` | `payload_length`、`key` | `result` |
| `wire_stream` | `chunks_hex`、`key`、`call_finish` | `result`、`packets`、`finish_result` |
| `encode` | `command`（login／select_role）、`args` | `result`、`packet`、`frame_hex` |
| `decode` | `packet` | `result`、`event` |

### 比對規則

- **必須相同**：`result`（`ok`／`rejected`）與其餘所有欄位。
- **不比對**：`error` 與 `finish_error` 的文字。它們是舊版 Python 的訊息，僅供人閱讀；其他語言只需也回報「拒絕」。
- 事件欄位名稱與型別（整數、布林、字串、巢狀物件）必須一致；`delete_time` 這類浮點欄位以 IEEE-754 雙精度比對。

## 來源分級（`source.grade`）

| 等級 | 意義 | 可信度 |
|---|---|---|
| `official_lua` | 依官方 Lua 核對推導 | 最高 |
| `reference_impl` | 由舊版 Python 實際執行產生，**尚未與 Lua 逐項對照** | 高，但可能繼承舊版的錯誤 |
| `live_capture` | 實機擷取後脫敏 | 佐證，不單獨當依據 |
| `synthetic` | 人工構造的邊界或負面案例 | 用來測容錯與拒絕 |

> 目前**沒有任何**案例標為 `official_lua` 或 `live_capture`。舊版已移除封包擷取匯入功能，
> 要取得 `live_capture` 需要重新建立擷取流程。把案例升級為 `official_lua`，需要逐項對照官方 Lua。

## 脫敏規則

- 帳號、密碼、角色名稱、ID 一律使用假值（例如 `testuser`、`Alice`、`9001`）。
- 官方原始資源（Bundle、原始 TextAsset）**不進入此 repo**。
- 未知封包的案例只能驗證「不外洩 payload」，案例本身也不放真實內容。

## 重新產生與驗證

```
python3 -I next/tools-python/gen_golden.py   # 需要在舊 repo 根目錄；會覆寫 golden/
python3 -I next/spec/verify_golden.py         # 獨立驗證，全部相符回傳 0
```

規格調整時：先改 `gen_golden.py` 與 `behavior/*.md`，重新產生，再確認獨立驗證器仍然全數通過。
若兩者不一致，代表規格有歧義，必須先釐清再往下走。
