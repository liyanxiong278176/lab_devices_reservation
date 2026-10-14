$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '..\.runtime'
foreach ($name in @('frontend', 'backend')) {
  $file = Join-Path $runtime "$name.pid"
  if (-not (Test-Path -LiteralPath $file)) { continue }
  $id = [int](Get-Content -LiteralPath $file -Raw)
  $process = Get-Process -Id $id -ErrorAction SilentlyContinue
  if ($process) {
    & taskkill.exe /PID $id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not stop the $name process tree (PID $id)." }
  }
  Remove-Item -LiteralPath $file -Force
}
'Stopped only the backend/frontend process trees started by qa_joint.'
