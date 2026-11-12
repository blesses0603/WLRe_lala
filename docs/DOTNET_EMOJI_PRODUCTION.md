# ver 8.0.71 正式表情來源工廠與發布接線

`EmojiRuntimeBatch.Create` 只接收 `PreparedEmojiSources` 的私有已驗證來源閉包。每次建構／重建均重驗精確 Data／Main manifest 規格、重新從 Data Bundle 解出已知 SHA 的 EmojiData，依 manifest 的依賴後根檔順序定位圖集，核對完整 archive SHA；只接受一個 Serialized owner、本檔必要物件圖、既有有界解壓／physics／小數裁切／像素限制。輸入來源指紋包含完整七檔及兩份 manifest，不能傳入 caller pixels 或自稱指紋。

`OfflineBundleRuntimePreparation` 在已審查 data／package 版本及精確資產路徑吻合時呼叫既有 `PrepareEmojiSourcesAsync`，共享既有下載及保留容量。完整 factory 成功才保留額外來源供快取。未知映射不下載圖集；容量或未支援格式保持選用圖片不可用；取消、來源版本／manifest 改變及退役不當成可忽略錯誤。

`ResourceRuntimeOwner` 優先取正式 prepared batch，再沿用表情 SQLite 整批 transaction、獨立全新回讀、最後來源重查與撤銷 publication。既有帳號／gallery 請求接上同一 activation；正式來源不會被離線 hook 取代。唯讀刷新仍不建立／修復資料庫。來源准入與遊戲協定權限維持分離，`HasVisualAssets=false` 及一般操作 Held 不變。

登入／版本資源確認與 public disclosure 已描述表情快取的條件式寫入，不再宣稱「尚不寫入」。網格與草稿插入沿用 v8.0.69；沒有聊天傳送。

## 驗證及限制

同一雲端私有官方快取經精確七檔大小／MD5／CRC／SHA 與 manifest 驗證，production factory 的 62 首幀完整 RGBA／尺寸／token 與 UnityPy 比對一致，PNG 279,975 bytes。以 factory source fingerprint 進行 SQLite 寫入及新連線讀回，均獨立重建且指紋／PNG 相符；取消重建拒絕。這是快取來源工廠正向驗證，不是重新取得端點的即時版本保證，也不是完整正式帳號 owner／桌面線上驗收；沒有提交官方 payload。

合成全流程來源若偽稱 1296，仍先被必要 ItemData 原始 SHA pin 阻擋，不會因新增表情入口繞過。正式正向資料未以測試 seam 放寬；owner 撤銷／取消／提交結果沿用合成測試，不能把它當正式 owner 准入證據。

## 正式表情完整流程的容量阻礙

進一步以同份已驗證 Data manifest 核對：必要十表來源六檔合計 7,231,669 bytes，與表情完整閉包去重後為 **33,772,710 bytes**，超過 Core 共用保留上限 **33,554,432 bytes** 共 **218,278 bytes**。`AcquireOptionalSourcesAsync` 會在圖集取得前拒絕，且保留上限與 cache hit 無關。因此**此已審查版本仍不能在完整 production 準備流程啟用表情**；factory＋owner 接線不代表完整來源取得可成功。沒有增加全域額度或省略依賴；下一步需分階段持有來源／快取與重新驗證的設計，並測試停止、撤銷、已提交及來源漂移。

## 小地圖前置接線與具體容量阻礙

新增 `SmallMapSourcePlan`：依 Python `smallmap_database.py` 驗證 MainPackage 的精確 `Assets/ResourcesBuild/Texture/SmallMap2D/SmallMap2D_N.png`，模型 1..65535、最多 2048、數字別名碰撞拒絕；保留精確每圖依賴閉包。這是來源預檢，未註冊下載／像素／SQLite／場景顯示。

已用既有已驗證的 1296 Main manifest 查得 **562** 張，完整閉包只有 `mainpackage_texture_s.bundle`，大小 **43,187,027 bytes**。Python 該家族允許 64 MiB，但 Core 現有共用下載與保留上限都是 **32 MiB**；本批固定拒絕此超限閉包，不增大額度、不下載。下一步需先設計獨立有界取得／解碼與快取策略，再驗證 1024×1024 Texture、像素、場景 model／offset／版本綁定及撤銷顯示，不能挪用 512 Sprite 路徑或歷史 ZIP。來源模型計數不等於像素或場景投影已完成。

## v8.0.70 CI 與競爭測試修正

`8d1de24` 的 Python 三平台成功，.NET Linux／macOS／Android 成功；Windows job `129431873795` 的 `Competing_writers_preserve_contradiction(mode:1)` 收到 SQLite Error 5，45,812 通過／1 失敗。Store 原本就限制 writer 等待一秒，測試卻要求兩次競爭都成功。修正只在測試接受明確 BUSY 且無 rollback error：等待兩次嘗試結束、確認至少一筆成功，再明示提交被拒觀測，最終仍必須 conflict。其他錯誤不接受；既有 busy-bounded 測試仍檢查一次 BEGIN、命令逾時與失敗後無寫入。沒有延長產品 timeout 或增加產品重試。

完整本機驗證與新 head CI 結果列於 PR #79；未合併 main、未發版、未讀取真帳密或連正式遊戲 TCP。
