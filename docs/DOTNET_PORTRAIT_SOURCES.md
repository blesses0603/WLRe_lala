# Core 頭像來源投影（PR #79 ver 8.0.55）

本批核對 Python `portrait_assets.py`（SHA256 `c0269bea2160fe975220895640f626f0706389ce20d54cd3e8643a782c5d4809`）及 [既有官方頭像紀錄](OFFICIAL_CHARACTER_PORTRAITS.md)，新增內部來源計畫與受限取得入口。**尚未接入 production 自動準備或頭像 UI**；缺少 Material／Shader／外部 PPtr 解碼時不先下載無法使用的圖資。

## 精確來源與邊界

- 只接受 Data 1.3.23、MainPackage `1296_2026_11_04_13_36_07_72`。
- 三個固定來源：material 1,903,222 bytes、texture_a 21,442,774 bytes、unityshaders 1,226,061 bytes；合計 24,572,057 bytes。每檔沿用 Python SHA256 pin，另外仍需當前 manifest 的 MD5／CRC32／size 完全符合。
- 精確材料路徑必須都指向 material Bundle，目錄與檔名 icon 相同；完整集合 778 個，角色圖正好 0001–0015。未知名稱、大小、版本、重複／不完整集合拒絕。
- 這是指定三檔的 **data-only projection**，不是 material Bundle 的完整 Unity 相依閉包。沒有把未載入的其餘相依視為滿足，也不啟動 Unity 或執行 shader。
- 計畫指紋包含 manifest SHA256、材料映射、三檔 specs 與既有 pins；來源驗證複製集合並保存不可變 owned handles，不接受呼叫者聲稱的 hash 或可改寫 stream。

`PreparePortraitSourcesAsync` 重用既有 attempt、下載／保留總額度、快取、精確 HTTPS URL 與取消／清理，不另開配額。取得後先逐檔核對 pins，再重查官方版本與 manifests，確認 attempt 仍有效才回傳。回傳仍只是歷史已核對來源，不是可用材質、當前 publication、登入或遊戲操作權限。

## 驗證與尚缺工作

自有 manifest 與全零 Bundle 可通過合成的 MD5／CRC／size，但必須被真實 SHA pins 拒絕。測試涵蓋版本、大小、路徑、角色集合、下載預算、來源集合、重複來源、取消、失效 attempt、僅取得三檔及不重下載已有 bytes。沒有加入替換 pin 的測試後門，也未宣稱正向官方來源取得成功；重查成功路徑須待真實固定來源驗收。

必要資料／可選技能／每日／副本／物品圖共用的取得部分抽為私有 helper，既有相依集合選擇仍保留；完整核心回歸用來檢查沒有放寬原有下載與來源驗證。

接續仍需精確 Material／Shader／外部 Texture／mask 指標與 metadata 解析，將來源鎖定接上 [頭像合成](DOTNET_PORTRAIT_RENDERING.md)、base/mask 儲存、角色映射、背景工作及可撤銷 UI。表情 SpriteAtlas、小地圖獨立 Texture 路徑與全介面仍未完成。HasVisualAssets=false；本次沒有新官方線上驗收、正式服登入或實機驗收。

## 同批表格載入優化

舊 TextTable 在任何一列改變時都重建全部 ListBoxItem／Grid／TextBlock。現在保留穩定集合，按唯一鍵更新變動列並移動原控制項；重複鍵保持不同控制項，清空後清除選取。輸入欄位複製，避免呼叫者修改陣列導致更新被跳過。

原生計數測試：200 列中修改一列，僅新增 1 次 row 建立（原路徑 200）；重新排序新增 0 次（原路徑 200），選取鍵保持。大型表格離屏列量測暴露字型繼承問題，改為明示既有桌面字型後回歸通過。這是控制項建立次數證據，不代表 FPS／整體載入時間或所有大量列表問題已解決；仍需列資料比較，重新排序也仍有集合移動成本。
