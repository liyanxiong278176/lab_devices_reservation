$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backendDir = Join-Path $root 'backend'
Push-Location $backendDir
try {
  foreach ($prefix in @('e2e-joint01', 'e2e-joint02')) {
    & (Get-Command uv).Source run python 'scripts\e2e_fixture.py' cleanup --prefix $prefix
    if ($LASTEXITCODE -ne 0) { throw "Fixture cleanup failed for $prefix." }
  }
} finally {
  Pop-Location
}
$runtime = Join-Path $PSScriptRoot '..\.runtime'
Remove-Item -LiteralPath (Join-Path $runtime 'fixtures.json') -Force -ErrorAction SilentlyContinue
'Cleaned only the two qa_joint fixture tenants.'
