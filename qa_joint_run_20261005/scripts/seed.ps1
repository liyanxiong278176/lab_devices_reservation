$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backendDir = Join-Path $root 'backend'
$runtime = Join-Path $PSScriptRoot '..\.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

$script = @'
import asyncio
from sqlalchemy import select
from app.core.settings import get_settings
from app.infrastructure.db.models import College
from app.infrastructure.db.session import build_engine, build_session_factory
async def main():
    engine = build_engine(get_settings())
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            for prefix in ('e2e-joint01', 'e2e-joint02'):
                found = await session.scalar(select(College.id).where(College.code == prefix.upper()))
                if found is not None:
                    raise SystemExit(f'Refusing to overwrite existing fixture tenant: {prefix}')
    finally:
        await engine.dispose()
asyncio.run(main())
'@
Push-Location $backendDir
try {
  $script | & (Get-Command uv).Source run python -
  if ($LASTEXITCODE -ne 0) { throw 'Fixture collision preflight failed.' }

  $fixtures = @()
  foreach ($prefix in @('e2e-joint01', 'e2e-joint02')) {
    $raw = & (Get-Command uv).Source run python 'scripts\e2e_fixture.py' seed --prefix $prefix
    if ($LASTEXITCODE -ne 0) { throw "Fixture seeding failed for $prefix." }
    $data = $raw | ConvertFrom-Json
    $fixtures += [pscustomobject]@{
      prefix = $data.prefix
      username = $data.username
      alternate_username = $data.alternate_username
      manager_username = $data.manager_username
      admin_username = $data.admin_username
      device_id = $data.device_id
      device_name = $data.device_name
      second_device_id = $data.second_device_id
      second_device_name = $data.second_device_name
      college_id = $data.college_id
    }
  }
} finally {
  Pop-Location
}
$fixtures | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runtime 'fixtures.json') -Encoding utf8
$fixtures | Select-Object prefix, username, manager_username, admin_username, device_id, second_device_id | Format-Table -AutoSize
