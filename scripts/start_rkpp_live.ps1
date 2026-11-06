param(
    [string]$Iface = 'WLAN',
    [int]$Port = 8195,
    [string]$RelayHost = '127.0.0.1',
    [int]$RelayPort = 8765
)

# rkpp 实时抓包中继。
#
# 这个文件必须保存成「UTF-8 带 BOM」：Windows PowerShell 5.1 在没有 BOM 时按
# 系统 ANSI（GBK）解码，中文会被拆成乱码并破坏引号配对，报
# MissingEndCurlyBrace / 字符串缺少终止符。
#
# 为什么必须这样启动：
#  1) 抓包要读网卡原始帧 + 走 Npcap 旁路监听，必须【管理员】权限；
#  2) rkpp 依赖 scapy / pycryptodome / protobuf / msgpack，系统 python（包括 conda base）
#     没有这些包，直接用 python 跑会报 ModuleNotFoundError: No module named 'scapy'；
#  3) 项目 venv .venv-rkpp 里已经装好全部依赖，所以固定用它，并且要先 cd 到 vendor\rkpp
#     （rkpp_live_tools.py 用相对路径读同目录的 Data.py / rkpp_data.sqlite）。

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$rkppDir = Join-Path $root 'vendor\rkpp'
$python = Join-Path $root '.venv-rkpp\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $rkppDir)) {
    Write-Host "找不到 $rkppDir" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "找不到项目 venv：$python" -ForegroundColor Red
    Write-Host "先建好依赖（只需要做一次）：" -ForegroundColor Yellow
    Write-Host "  cd $root" -ForegroundColor Yellow
    Write-Host "  E:\miniconda3\python.exe -m venv .venv-rkpp" -ForegroundColor Yellow
    Write-Host "  .venv-rkpp\Scripts\python.exe -m pip install scapy==2.8.0 pycryptodome protobuf msgpack" -ForegroundColor Yellow
    exit 1
}

# 依赖自检：缺包时给出确切修复命令，而不是让用户在成堆 traceback 里猜。
$depCheck = "import scapy, Crypto, google.protobuf, msgpack; print('deps ok', scapy.__version__)"
& $python -c $depCheck
if ($LASTEXITCODE -ne 0) {
    Write-Host "venv 里依赖不全，执行：" -ForegroundColor Yellow
    Write-Host "  .venv-rkpp\Scripts\python.exe -m pip install scapy==2.8.0 pycryptodome protobuf msgpack" -ForegroundColor Yellow
    exit 1
}

# 管理员检查：没有提权就抓不到包（is_admin:false 时事件数恒为 0）。
$isAdmin = $false
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { $isAdmin = $false }

if (-not $isAdmin) {
    Write-Host "当前不是管理员权限，抓不到任何包。" -ForegroundColor Red
    Write-Host "请右键「Windows PowerShell」-> 以管理员身份运行，再执行：" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File $PSScriptRoot\start_rkpp_live.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "网卡：$Iface   中继：http://${RelayHost}:$RelayPort   接口：http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host ""
Write-Host "【重要】密钥只在客户端建连时发一次，抓包必须比建连更早开着：" -ForegroundColor Yellow
Write-Host "  - 如果游戏已经登录在线，请【先在游戏里退回登录界面重新进入】，" -ForegroundColor Yellow
Write-Host "    或重启游戏客户端；本中继会在抓到 0x1002 后自动开始解码，不用重启抓包。" -ForegroundColor Yellow
Write-Host "  - 进对局后另开一个窗口跑 scripts\check_capture_status.ps1 可确认是否已拿到密钥。" -ForegroundColor Yellow
Write-Host "  - 面板上不会再只写“等待对局数据”：没拿到密钥时会直接写明 key_hits=0 和怎么修。" -ForegroundColor Yellow
Write-Host ""
Write-Host "按 Ctrl+C 停止。" -ForegroundColor Cyan
Write-Host ""

# 复用旧密钥：只有「游戏没重启、只重启了抓包」时才成立。
# 0x1002 只在建连时发一次。如果旧 key 对应的那条 TCP 连接还活着（同本地端口、
# 同远端地址:8195），说明客户端没换会话，key 依然有效，直接复用就不必重登。
# 连接不匹配时绝不能硬套（rkpp 会判定 bad key），必须等新的 0x1002。
$keyPath = Join-Path $rkppDir 'Key\latest.key'
$reuseKey = $false
if (Test-Path -LiteralPath $keyPath) {
    $keyText = Get-Content -LiteralPath $keyPath -Encoding utf8 -Raw
    if ($keyText -match 'flow=([0-9\.]+):(\d+)->([0-9\.]+):(\d+)') {
        $keyLocalPort = 0
        [int]::TryParse($Matches[2], [ref]$keyLocalPort) | Out-Null
        $keyRemotePort = 0
        [int]::TryParse($Matches[4], [ref]$keyRemotePort) | Out-Null
        $keyRemoteAddr = $Matches[3]
        if ($keyLocalPort -gt 0 -and $keyRemotePort -eq $Port) {
            $live = @(Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
                Where-Object { $_.LocalPort -eq $keyLocalPort -and $_.RemotePort -eq $Port -and $_.RemoteAddress -eq $keyRemoteAddr })
            if ($live.Count -gt 0) { $reuseKey = $true }
        }
        if (-not $reuseKey) {
            Write-Host ("旧密钥对应的连接已断开（该连接本地端口 " + $keyLocalPort + "），不能复用，等待新的 0x1002。") -ForegroundColor DarkGray
        }
    }
}

$relayArgs = @('rkpp_live_tools.py', 'opencode-server', '--iface', $Iface, '--port', "$Port",
               '--relay-host', $RelayHost, '--relay-port', "$RelayPort")
if ($reuseKey) {
    $relayArgs += '--allow-stale-key'
    Write-Host "检测到旧密钥对应的连接仍在，直接复用（本次不需要重登）。" -ForegroundColor Green
}

Push-Location $rkppDir
try {
    & $python @relayArgs
} finally {
    Pop-Location
}
