# Chiude uno scenario: ferma il server (e il suo processo figlio), salva lo screenshot e stampa i fatti verificati.
# Uso:  .\tests\scenarios\chiudi_scenario.ps1 -N 1 -Fase prima -Immagine mcp-Claude_Browser-blob-....jpg
param(
    [Parameter(Mandatory = $true)][int]$N,
    [Parameter(Mandatory = $true)][ValidateSet("prima", "dopo")][string]$Fase,
    [string]$Immagine
)
$radice = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$cartella = Join-Path $radice ("logs\scenari\{0}\S{1:D2}" -f $Fase, $N)

$pidFile = Join-Path $cartella "pid.txt"
if (Test-Path $pidFile) {
    $processo = [int](Get-Content $pidFile)
    taskkill /PID $processo /T /F | Out-Null   # /T ferma anche il server MCP figlio
}

if ($Immagine) {
    $origine = Join-Path "C:\Users\poneto\.claude\projects\C--Users-poneto-Documents-Tesi-di-laurea\6cc3b6aa-b51b-4833-973a-abc9d50976e7\tool-results" $Immagine
    $destinazione = Join-Path $radice ("docs\screenshots\scenari\{0}" -f $Fase)
    New-Item -ItemType Directory -Force $destinazione | Out-Null
    Copy-Item $origine (Join-Path $destinazione ("S{0:D2}.jpg" -f $N))
}

$env:PYTHONIOENCODING = "utf-8"
& (Join-Path $radice ".venv\Scripts\python.exe") (Join-Path $radice "tests\scenarios\verifica_scenario.py") $N --fase $Fase
