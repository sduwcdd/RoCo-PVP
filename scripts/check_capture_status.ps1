# rkpp 抓包健康检查（不需要管理员）。
#
# 用途：观战/野外打怪 HUD 一直不出数据时，先跑这个，一眼看出卡在哪一层：
#   target_packets      网卡抓到的包数      -> 0 表示抓包没跑 / 网卡选错
#   decoded_rows        TCP 流解出的行数    -> 0 表示端口/网卡不对
#   parsed_business_records 解出的业务记录  -> 0 而 key_hits=0 表示没拿到会话密钥
#   key_hits            抓到 0x1002 密钥次数 -> 0 就是"解不开"的唯一原因
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$base = Join-Path $root 'vendor\rkpp'

$sessions = Get-ChildItem -LiteralPath $base -Directory -Filter 'rkpp_*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 3
if (-not $sessions) {
    Write-Host "没找到任何抓包会话目录（$base\rkpp_opencode_server_*）" -ForegroundColor Red
    Write-Host "说明抓包还没启动过：以管理员身份运行 启动实时抓包.bat" -ForegroundColor Yellow
    exit 1
}

$summary = $null
$session = $null
foreach ($s in $sessions) {
    $log = Join-Path $s.FullName 'capture.log'
    if (-not (Test-Path -LiteralPath $log)) { continue }
    $line = Get-Content -LiteralPath $log -Encoding utf8 -Tail 4000 |
        Where-Object { $_ -match '\[capture-diag\].*"event":"summary"' } | Select-Object -Last 1
    if (-not $line) { continue }
    $json = ($line -replace '^.*?\[capture-diag\]\s*', '')
    try { $summary = $json | ConvertFrom-Json } catch { continue }
    if ($summary) { $session = $s; break }
}

if (-not $summary) {
    Write-Host "会话目录里还没有 [capture-diag] summary 行。" -ForegroundColor Yellow
    Write-Host "抓包可能刚启动（每 5 秒打一次摘要），等几秒再跑一次。" -ForegroundColor Yellow
    exit 0
}

Write-Host ("会话目录 : " + $session.Name) -ForegroundColor Cyan
Write-Host ("包数     : " + $summary.target_packets)
Write-Host ("TCP 行   : " + $summary.decoded_rows)
Write-Host ("业务记录 : " + $summary.parsed_business_records)
Write-Host ("密钥命中 : " + $summary.key_hits)
Write-Host ""

if ([int]$summary.parsed_business_records -gt 0) {
    Write-Host "解密正常，业务帧在出了。" -ForegroundColor Green
    Write-Host "如果 HUD 还是空的，看中继是否有事件：curl http://127.0.0.1:8765/health" -ForegroundColor Green
    exit 0
}

if ([int]$summary.key_hits -eq 0) {
    Write-Host "卡在：没拿到本次会话的 0x1002 密钥。" -ForegroundColor Red
    Write-Host "0x1002 只在客户端建立连接时发一次。抓包必须比建连更早开着。" -ForegroundColor Yellow
    Write-Host "修复：在游戏里退回登录界面重新进入，或直接重启游戏客户端。" -ForegroundColor Yellow
    Write-Host "      密钥一到中继就会自动开始解码，不用重启抓包。" -ForegroundColor Yellow
} else {
    Write-Host "密钥拿到了但业务记录仍是 0，属于解码/端口问题，把本输出发给开发者。" -ForegroundColor Yellow
}