# ver 8.0.66 受限串流資源與圖集裁切

這一批完成獨立 image archive、Texture／SerializedFile／圖集明示綁定及矩形裁切；尚未把完整官方 EmojiData／圖集指標組合成 production 批次。PNG／SQLite、撤銷發布與表情顯示、小地圖仍未完成。

## 範圍與容量

`BoundedUnityBundle.Read` 保持舊 64 MiB 解壓上限及只接受 serialized flags=4。新 `ReadImageArchive` 才允許 flags=0 的 `.resS`，必須有同一 Bundle 的精確配對 serialized 名稱；其他 flags、路徑或重複目錄拒絕。壓縮輸入仍限 64 MiB，image 專用解壓限 96 MiB，整批 `UnityExtractionBudget` 仍限 128 MiB、128 entries，既有 block、metadata、LZ4 與取消檢查維持。

`UnityImageArchive` 先擁有壓縮 bytes，再解壓及記錄 SHA；不從磁碟／網路解析任何 archive 路徑。資源必須精確等於 `archive:/<owner>/<owner>.resS`，包含完整 BundleName／EntryName 身份，offset 非負且 size 在資源內，單段 1..16 MiB。Serialized 複本亦限 16 MiB。結果皆為複本；不接受 basename fallback 或其他 Bundle 同名資源。

這是有界的**整個 Bundle 解壓**，不是懶載入或區段解壓，也沒有記憶體／速度改善宣告。image archive 持有完整 expanded buffer；批次組合層必須共用同一 budget 並控制保留期限，不得每檔重置額度來繞過整批上限。

Texture 只在明示 archive／owner 綁定且 inline 為空時接受 streamed span；尺寸、色域、格式、單 mip、complete size 與實際 payload 長度仍核對。舊呼叫沒有 archive 時照常拒絕。圖集候選指紋包含完整 serialized bytes、物件身份與 archive SHA；這不創造來源資格或目前帳號 publication。

## Python 裁切語意

核對固定 UnityPy 1.25.4 `SpriteHelper`：rotation 為 `(settings >> 2) & 15`，bit 6 為 mesh type。僅接受 packed 矩形模式及既有五種 rotation，保留拒絕 tight packing、未知高位與 downscale。Python 返回轉換後的 texture crop，不依 logical rect 補透明邊；本層要求 crop 不大於有界的整數 logical rect。

Atlas Sprite 的 physics shape 只讀取、不用於裁切或建立幾何權限；最多 64 shapes、4096 total Vector2 points，所有浮點必須有限。非 atlas 入口仍只接受空 physics。bones／bindpose 等限制不變。

## 驗證證據

自有固定 UnityPy 真實 SerializedFile writer／Sprite.image 產生 60 組 inline 與 30 組 streamed 完整 RGBA 對照：RGBA32、DXT1、DXT5、五種旋轉、有／無獨立 alpha、mesh bit、非空 physics 及較大 logical rect。另有真實 UnityFS／UnityPy `.resS` reader 對照、64／96 MiB 邊界、共享總額、錯誤配對與 flags、越界／未知 owner／取消／逐位截斷測試。產生器只寫自有 fixture，沒有提交官方 payload。

本機只讀上一批已驗證官方快取，先核對 `emoji_source_1296_audit.json` 的完整 Bundle SHA。C# 得到解壓 78,745,132 bytes、SerializedFile 3,378,476 bytes；三段 `.resS` 與獨立 UnityPy 的長度及 SHA 完全一致：

| offset | bytes | SHA256 |
| --- | --- | --- |
| 54400192 | 1048576 | 4c0a527fdba706bd834f5ad0f0dd6c31ab1fb2de37a0a9a28edcf26db6266182 |
| 10739280 | 1048576 | 99fd09abbdb28322f9982e1ee64c677632afcf8b7e786192fe602a88e6ce82c7 |
| 4147136 | 262144 | 4b7601cfeb5e273f925f01158467be55d3de4788d6b7ee37d0f7b162b273eeaa |

這只驗證實際容器與三段壓縮材質 bytes；**不是官方 62 首幀像素、完整指標、PNG／SQLite、撤銷或 UI 驗收**。未連正式遊戲服或讀真帳密，`HasVisualAssets=false`、一般操作 Held。
