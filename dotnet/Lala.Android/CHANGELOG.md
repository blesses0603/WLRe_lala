# Android C# host 版本紀錄

## v0.2.0（開發候選，PR79，尚未正式發布）

- 建立 Service/runtime 擁有的單一選定帳號生命週期、世代隔離、取消、連線與清理逾時，以及有限次數退避重試。
- 加入 Android 前景服務、私密通知與停止操作、Activity 重新綁定、通知授權與拒絕後暫緩啟動。
- 加入 API23 相容與 API24+ default network 監控；網路可用不等同遊戲伺服器已連線。
- 保留離線封包檢視器；新增 Android 連線狀態頁，明確顯示尚未接入共用登入／TCP 核心。
- 增加跨平台純生命週期測試、Android APK 建置驗證與 CI 測試產物。
- Android `ApplicationDisplayVersion`：`0.1.0 → 0.2.0`；`ApplicationVersion`：`1 → 2`。不更動 Python Desktop／舊 Android 倉庫的獨立版本。
- 尚未完成：真實登入／transport、多帳號集合、Keystore／簽章驗證、懸浮球、實機完整生命週期與正式服驗收。沒有 Release／Tag。

## v0.1.0（PR79 初始離線 host）

- 建立 Avalonia.Android 12.1.5、.NET10／API36 host。
- 共用 Core 封包 codec 與 Desktop 離線檢視器；尚無網路、前景服務或通知權限。
