param(
    [ValidateSet('Start', 'Stop')][string]$Mode = 'Start',
    [string]$IfaceEncoded = 'V0xBTg==',
    [switch]$Elevated
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root 'artifacts\app'
[void][IO.Directory]::CreateDirectory($logs)
$resultFile = Join-Path $logs 'capture-result.json'
$receiptFile = Join-Path $logs 'capture-owner.json'
$utf8 = New-Object Text.UTF8Encoding($false)
function Write-Result($value) {
    [IO.File]::WriteAllText($resultFile, ($value | ConvertTo-Json -Depth 5), $utf8)
}
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) {
        if ($Elevated) { throw 'Administrator permission was not granted.' }
        $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Elevated -Mode ' + $Mode + ' -IfaceEncoded ' + $IfaceEncoded
        $helper = Start-Process -FilePath $ps -ArgumentList $argLine -Verb RunAs -WindowStyle Hidden -PassThru
        # Wait only for the elevated helper, not its long-running capture child.
        $helper.WaitForExit()
        exit $helper.ExitCode
    }
    $python = Join-Path $root '.venv-rkpp\Scripts\python.exe'
    $script = Join-Path $root 'vendor\rkpp\rkpp_live_tools.py'
    if ($Mode -eq 'Stop') {
        if (-not (Test-Path -LiteralPath $receiptFile)) { throw 'No capture process owned by this app.' }
        $receipt = Get-Content -LiteralPath $receiptFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $capture = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$receipt.pid)
        if ($capture) {
            $running = Get-Process -Id $capture.ProcessId
            if ($running.StartTime.ToUniversalTime().Ticks.ToString() -ne [string]$receipt.start_ticks -or
                -not $capture.CommandLine.Contains($script)) { throw 'Process identity changed; refusing to stop.' }
            Stop-Process -Id $capture.ProcessId -ErrorAction Stop
        }
        [IO.File]::Delete($receiptFile)
        Write-Result @{ ok = $true; state = 'stopped' }
        exit 0
    }
    if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python environment is missing.' }
    if (-not (Test-Path -LiteralPath $script)) { throw 'rkpp module is missing.' }
    if (Test-Path -LiteralPath $receiptFile) {
        $old = Get-Content -LiteralPath $receiptFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $running = Get-Process -Id ([int]$old.pid) -ErrorAction SilentlyContinue
        if ($running -and $running.StartTime.ToUniversalTime().Ticks.ToString() -eq [string]$old.start_ticks) { throw 'Capture is already running; stop it first.' }
    }
    $iface = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($IfaceEncoded))
    if (-not $iface.Trim() -or $iface.Length -gt 128 -or $iface -match '["\r\n\x00]') { throw 'Invalid network interface.' }
    & $python -c 'import scapy, Crypto, google.protobuf, msgpack'
    if ($LASTEXITCODE -ne 0) { throw 'Capture dependencies are missing in the project Python environment.' }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
    $stdout = Join-Path $logs ('capture-' + $stamp + '.stdout.log')
    $stderr = Join-Path $logs ('capture-' + $stamp + '.stderr.log')
    $arguments = '"' + $script + '" opencode-server --iface "' + $iface + '" --port 8195 --relay-host 127.0.0.1 --relay-port 8765'
    $keyPath = Join-Path $root 'vendor\rkpp\Key\latest.key'
    if (Test-Path -LiteralPath $keyPath) {
        $keyText = Get-Content -LiteralPath $keyPath -Raw -Encoding UTF8
        if ($keyText -match 'flow=([0-9\.]+):(\d+)->([0-9\.]+):(\d+)') {
            $localPort = [int]$Matches[2]; $remoteAddress = $Matches[3]; $remotePort = [int]$Matches[4]
            $matchesLive = @(Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | Where-Object {
                $_.LocalPort -eq $localPort -and $_.RemoteAddress -eq $remoteAddress -and $_.RemotePort -eq $remotePort
            })
            if ($remotePort -eq 8195 -and $matchesLive.Count -gt 0) { $arguments += ' --allow-stale-key' }
        }
    }
    $env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
    $child = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory (Join-Path $root 'vendor\rkpp') -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $started = Get-Process -Id $child.Id
    [IO.File]::WriteAllText($receiptFile, (@{pid=$child.Id;start_ticks=$started.StartTime.ToUniversalTime().Ticks.ToString();script=$script;stdout=$stdout;stderr=$stderr} | ConvertTo-Json), $utf8)
    Write-Result @{ok=$true;state='starting';pid=$child.Id;hint='Waiting for relay and a fresh session key.'}
    exit 0
} catch {
    Write-Result @{ok=$false;error=$_.Exception.Message}
    Write-Error $_.Exception.Message
    exit 1
}
