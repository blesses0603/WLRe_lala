# 官方 1275 副本與協力圖示來源（PR #57）

## 來源
使用者另外提供兩張從 Unity `Texture2D` 提取的圖片：

| 程式中圖示 | 使用者提供之原始提取檔 |
| --- | --- |
| `Menu_Dungeon.png` | `Btn_DungeonList02_Texture2D_7291917609996986674_41c38d89ac31.png` |
| `Menu_Cooperate.png` | `Btn_DungeonCooperate02_Texture2D_2261232642749247050_41c38d89ac31.png` |

兩張原圖都是 85×85 RGBA，內容分別為螺旋門與三星三人。
提取檔名稱具有 Texture2D / PathID 線索，但尚未獨立核對
完整官方 Bundle SHA 或 SpriteAtlas，故**不宣稱已完成
1275 原始資產校驗**。

## LaLa UI 處理

LaLa 其他分頁既有的 `function_icons.icon_image()` 使用
深藍圓形底板、淺色描邊與 34px 目標尺寸。
原提取檔自帶藍色背景，直接縮小會形成突兀的藍色方塊。
因此 **本目錄 PNG 儲存的是從上述新圖分離的透明圖案，
不是未修改的原始提取檔**：

- 保留原圖案的星星／人像、螺旋門輪廓與抗鋸齒；
  移除內建藍色底板、保留透明通道。
- `instance_menu_icons.menu_icon_image()` 套用與既有
  主分頁完全相同的圓底填色、外框、內距及 3 倍超採樣。
- 主程式「副本」與視窗內「主要／協力」子分頁一律 34px。
- `RoundedNotebook` 的原本選取效果、hover、方向鍵及
  分頁切換不變；圖片異常時仍使用文字回退。

這次只是圖片與顯示樣式調整，沒有修改伺服器封包、
協力領獎、自動化功能鎖或其他模組的業務邏輯。
