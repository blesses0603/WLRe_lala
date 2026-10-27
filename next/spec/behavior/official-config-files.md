# 版本資料夾內的設定與清單檔：欄位格式

> 來源：2026-10-27 以 `next/tools-python/probe_official.py` 實際下載 `1.0.0`、`1.3.20`、`1.3.21` 三個版本資料夾的檔案，
> 再用 `describe`（只輸出型別、不輸出值）分析。證據等級：`official_cdn`；**沒有**和官方客戶端讀取程式逐行核對。
>
> **本文件只記錄欄位格式。** `ServerList.txt`、`VerifyServer.txt` 的位址、埠號、名稱等實際值一律不寫入 repo、Log 或 PR。

## 檔案位置

```
{DataVer}/LuaScripts/LuaScriptPathList.txt
{DataVer}/LuaScripts/Lua/…                       （Lua 原檔，不進 repo）
{DataVer}/Resources{PC,Android,IOS}/Config.txt
{DataVer}/Resources{PC,Android,IOS}/ServerList.txt
{DataVer}/Resources{PC,Android,IOS}/VerifyServer.txt
{DataVer}/Resources{PC,Android,IOS}/AssetBundle/  （Bundle，不進 repo）
```

三個平台資料夾都有同樣的三個 `.txt`。副檔名雖然是 `.txt`，但 `Config`、`ServerList`、`VerifyServer` 的內容都是 **JSON**。

## 1. `LuaScriptPathList.txt`

| 項目 | 觀察結果 |
|---|---|
| 編碼與換行 | UTF-8、無 BOM、**LF**，最後一行**有**換行，沒有空行 |
| 每一行 | `相對路徑|雜湊`，以 `|` 分隔，剛好兩欄 |
| 相對路徑 | 全部以 `Lua/` 開頭、副檔名全是 `.lua`、使用 `/`、沒有開頭的 `/`、沒有重複 |
| 雜湊 | 32 個**大寫**十六進位字元 |
| 雜湊的意義 | **檔案位元組的 MD5**。抽樣 2 個檔案（`Lua/event.lua`、`Lua/list.lua`）實際下載後計算，與清單相符（2/2）。其餘 864 個未逐一驗證 |
| 筆數 | `1.3.21` 866 行、`1.3.20` 866 行、`1.0.0` 813 行 |
| 1.3.20 → 1.3.21 | 新增 0、刪除 0、雜湊變更 12 個檔案 |

Lua 檔的下載位址 = `{DataVer}/LuaScripts/` + 相對路徑。

**解析規則：** 每行必須剛好一個 `|`；路徑不可含 `..`、`\`、開頭 `/`；雜湊必須是 32 個十六進位字元。
比對時雜湊不分大小寫（清單是大寫，一般 MD5 工具輸出小寫）。任何一行不合法就整份拒絕。

## 2. `Config.txt`

JSON 物件，7 個欄位，三個版本、三個平台的**鍵名相同**：

| 欄位 | JSON 型別 |
|---|---|
| `EnableUpdateData` | bool |
| `AssetBundleNum` | 整數（JSON number） |
| `DownloadInBackground` | bool |
| `EnableCreateRoleComputerGraphics` | bool |
| `EnableNewbieTutorial` | bool |
| `EnableCreateRoleSituation` | bool |
| `DisActivityLink` | bool |

UTF-8、無 BOM、CRLF。各欄位的實際意義（例如 `AssetBundleNum` 是 Bundle 數量還是並行下載數）**尚未確認**。

## 3. `ServerList.txt`（**實際值不得外流**）

JSON 陣列。`1.3.21` 的 PC 與 Android 版都是 9 筆，每筆的鍵集合相同：

| 欄位 | JSON 型別 | 觀察 |
|---|---|---|
| `id` | 整數 | 不重複、由小到大排列 |
| `address` | **字串** | 9 筆中 7 筆是 IPv4 字串；另 2 筆是 **1 位數的數字字串**（推測是佔位值，**尚未確認**） |
| `port` | 整數 | 只有 2 種不同的值 |
| `state` | 整數 | 只有 3 種不同的值（意義**尚未確認**） |
| `title` | 字串 | 3 個 ASCII 字元 |
| `name` | 字串 | 中文，長度不一 |
| `nameChat` | 字串 | 2 個中文字 |

- 編碼：`1.3.20`、`1.3.21` 為 UTF-8 無 BOM；**`1.0.0` 三個平台都有 UTF-8 BOM**。解析器必須接受 BOM（或明確決定拒絕舊版）。
- `address` 不是 IPv4 的那幾筆，新版不可嘗試連線，也不可自行轉換成位址；應標示為不可用並保持拒絕。

## 4. `VerifyServer.txt`（**實際值不得外流**）

JSON 物件，2 個欄位：`address`（主機名稱字串）、`port`（整數）。PC 版 54 bytes、CRLF，**結尾有換行**。
用途（推測是登入前的驗證伺服器）**尚未確認**。

## 共通規則與未決事項

- 新版讀這些檔案時：先依 `ResourcePath_*.dat` 決定 DataVer，再讀**對應平台**的資料夾，不混用平台。
- 解析一律嚴格：型別不符、缺欄位、多欄位都拒絕，不猜測。
- `ServerList.txt` 的 `state`、佔位 `address` 的意義，以及 `Config.txt` 各旗標的效果：都需要對照官方 Lua，**尚未執行**。
