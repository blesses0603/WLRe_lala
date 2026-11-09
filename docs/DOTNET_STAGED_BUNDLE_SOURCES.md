# ver 8.0.72 分階段來源與串流快取

## 本批實作

`BundleStreamVerifier` 用固定 64 KiB 工作陣列驗證精確 manifest-derived spec，串流計算長度、MD5、little-endian CRC32 及 SHA256；每次讀取最多 64 KiB，最後多讀一個 byte 判斷尾端超量。接受可選的既有 SHA，重新開啟來源時必須比對。取消每次 I/O 前後及每 4096 bytes CRC 工作檢查。呼叫者擁有 streams；輸出在成功前只是暫存，不能提供像素或來源准入。

`RuntimeBundleCacheWriter.StoreStreamAsync` 是明示的新磁碟暫存入口，單檔上限 64 MiB；同 writer 透過 semaphore 同時只處理一個 stage，等候中的取消不讀來源。路徑仍由固定 cache root 和已驗證 spec 產生，沿用 root／子路徑 reparse/link 檢查。CreateNew 私有暫存檔完成寫入／flush 後，重新讀取並驗證全檔，再 atomic move；發布後再次核對。合作 writer 競爭只在重新核對相同 bytes 後接受。取消／失敗只刪除自己尚未發布的暫存；發布完成後的取消不撤銷已完成檔案。

`BundleStreamReceipt` 只有 spec 和完整 SHA 的觀測，不是持有整檔 bytes 的 `VerifiedBundleSource`，不能轉為 publication、帳號准入或任意檔案的可信聲明。既有 `StoreAsync`、來源保留 32 MiB、下載 24 檔／32 MiB 及解碼限制完全不變；**新入口尚未註冊 production 下載／解碼**。每個新 stage 最多 64 MiB 暫存，替換既有同大小檔案時該項目可暫時占用 128 MiB 磁碟；它不是整個使用者 cache 的總額上限。

## 驗證

自有零資料 stream 長度 43,187,027 bytes（僅大小與官方小地圖相同，沒有官方 payload），以 Python hashlib／zlib 獨立計算 MD5 `91af61388a40636feebd02d6bba45131`、CRC `83e54ea9`、SHA `b7fe8b0896ac3f9f7c3bcdb0f6dd57ac568e92541ac36333ffafbd0a2c2aa50f`。測試確認請求不超過 65,536 bytes、檔案完整及新 reader 回讀相同。這是讀取區塊上限測量，不宣稱 managed heap 或整體應用程式峰值。

另測試截斷、多餘尾端、checksum 錯誤、SHA 聲明不符、超過 64 MiB、初始／stage／move 前後取消、暫存竄改、既有檔案保留、input ownership、同 writer 排隊取消、不同 writer 合作發布及暫存清理。完整本機／CI 結果以精確提交為準。

## 後續接線設計（未完成）

1. 必要資料階段：保留現有完整表驗證、inventory 回讀與來源重查；持久化已驗證 Bundle 後，用 spec＋SHA receipt 取代跨階段保留的所有 byte[]。所有舊 callback／publication 在開始新階段前撤銷，完成結果不得提前發出。
2. 圖資暫存階段：每次只持有固定 stream buffers，逐檔暫存並驗證；使用獨立、明示、有限的檔數／磁碟／下載總額規範。不得只是重設同一次 32 MiB 計數或將 64 MiB 磁碟限制當成放寬記憶體上限。階段間及每次發布前重查同一份版本／manifest。
3. 表情：將既有來源工廠的全閉包 byte[] 改為 receipt-based 重新驗證讀取，Data 映射及圖集根檔逐次使用、釋放；完整閉包每檔 SHA 仍參與指紋。未做到這一點，必要表＋表情聯集 33,772,710 bytes 仍不能通過原 32 MiB 保留限制，cache hit 也不例外。
4. 小地圖：43,187,027 bytes 來源可用新 stage 保存，但不能再整檔載入現有 32 MiB source holder，也不能將整個展開 archive 放入現有有限解碼預算。需要 bounded UnityFS block index／compressed-block SHA receipts 與按需解壓，對每個實際讀取 block 比對初次完整 source SHA 驗證時記錄的 hash，防止快取在分段讀取期間變動；有界 metadata 與 block cache，逐張 1024 Texture／PNG 消費並釋放。
5. 每圖及整批 PNG／SQLite 仍需來源依賴、像素指紋、獨立讀回、最終來源重查與帳號撤銷。取消、已發布 cache、已提交 SQLite 與結果不明分別處理；不能因部分 cache 成功啟用圖片。

上述 phase coordinator、receipt-backed decoder、實際小地圖 pixel／場景映射與顯示尚未完成。保持現有 production 阻擋，不以本批合成大 stream 冒稱正式完整圖資驗收。

## v8.0.71 CI 核查

`0902c68` Python 全成功；.NET Windows／Linux／Android 成功，先前 Windows SQLite 修正已通過。macOS job 129440634189 的兩個 timeout：ReceiveAttemptTests.ByteReadsAndDifferentCompletionThreadsStillHaveOneActualWriter(xor:255)（10 秒）及 PreparedPendingInputRetirementKeepsCleanupPendingAndClearsLateCredentials(expiry)（30 秒等待進入輸入回呼）；45,822 通過／2 失敗。

本批只修正測試排程依賴：逐 byte read 沿用全部封包，但以兩個輪替的真實 completion threads 取代每 byte 建立 OS thread，關閉等待兩者退出，單一 writer／不同 completion thread 斷言保留。expiry 案例改用同檔既有 PreparationClock，確定 input 已進入後才推進到期限；保留取消、清除晚到帳密、清理等待及零正式連線斷言。不延長產品期限、測試 guard 或自動重跑舊 CI。舊 failure 保留，不修改被拒的 PR 說明。
