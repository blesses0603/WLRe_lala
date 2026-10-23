# 以 1262 為基準擷取官方版本查詢網址（僅掃描 Player.log）

# PowerShell 5.1+。不需要管理員權限、不送出網路請求、不讀取遊戲帳密。
$logs = @()
$localLow = Join-Path $env:USERPROFILE 'AppData\LocalLow'
if (Test-Path -LiteralPath $localLow) {
    $logs += Get-ChildItem -LiteralPath $localLow -Recurse -File -Filter 'Player.log' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
}
$game = 'D:\Program Files\D\wlre'
if (Test-Path -LiteralPath $game) {
    $logs += Get-ChildItem -LiteralPath $game -Recurse -File -Include '*.log' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
}

# Only retain URLs belonging to official ChineseGamer domains; strip queries/fragments.
$found = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$pattern = 'https?://[^\s"<>]+'
foreach ($file in ($logs | Select-Object -Unique)) {
    try {
        Get-Content -LiteralPath $file -ErrorAction Stop | ForEach-Object {
            foreach ($item in [regex]::Matches($_, $pattern)) {
                $candidate = $item.Value.TrimEnd('.',',',')',']',"'")
                try {
                    $uri = [Uri]$candidate
                    $hostName = $uri.DnsSafeHost.ToLowerInvariant()
                    if ($hostName -eq 'chinesegamer.net' -or $hostName.EndsWith('.chinesegamer.net')) {
                        $path = $uri.AbsolutePath.ToLowerInvariant()
                        if ($path -match '(manifest|version|package|update|yoo)') {
                            # URI path only. Never export session tokens in URL queries.
                            [void]$found.Add($uri.GetLeftPart([System.UriPartial]::Path))
                        }
                    }
                } catch {}
            }
        }
    } catch {}
}
$output = Join-Path (Get-Location) 'WLRE_官方版本網址候選.txt'
if ($found.Count -gt 0) {
    $found | Sort-Object | Set-Content -LiteralPath $output -Encoding UTF8
    Write-Host "找到 $($found.Count) 筆候選版本 URL：$output"
} else {
    '找不到官方版本 URL。請啟動一次原版遊戲更新視窗後，再執行此掃描。' |
        Set-Content -LiteralPath $output -Encoding UTF8
    Write-Host "沒有找到候選 URL：$output"
}
Write-Host '注意：找到網址不等於已驗證可用。必須再核對官方主機、HTTP 回應與版本格式。'
