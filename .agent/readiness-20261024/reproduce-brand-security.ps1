$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('gl3-brand-security-repro-' + [guid]::NewGuid().ToString('N'))

New-Item -ItemType Directory -Path (Join-Path $tempRoot 'tools\brand'), (Join-Path $tempRoot 'docs\design'), (Join-Path $tempRoot 'web\public'), (Join-Path $tempRoot 'web\src') | Out-Null
Copy-Item (Join-Path $repoRoot 'tools\brand\generate.py'), (Join-Path $repoRoot 'tools\brand\validate.py'), (Join-Path $repoRoot 'tools\brand\requirements.txt') (Join-Path $tempRoot 'tools\brand')
Copy-Item -Recurse (Join-Path $repoRoot 'tools\brand\masters') (Join-Path $tempRoot 'tools\brand')
Copy-Item (Join-Path $repoRoot 'docs\design\brand.tokens.json') (Join-Path $tempRoot 'docs\design')
Copy-Item -Recurse (Join-Path $repoRoot 'web\public\fonts') (Join-Path $tempRoot 'web\public')
Copy-Item -Recurse (Join-Path $repoRoot 'web\src\*') (Join-Path $tempRoot 'web\src')
Copy-Item (Join-Path $repoRoot 'web\index.html') (Join-Path $tempRoot 'web')
Copy-Item (Join-Path $repoRoot 'web\public\site.webmanifest') (Join-Path $tempRoot 'web\public')

$requirements = Join-Path $tempRoot 'tools\brand\requirements.txt'
$generator = Join-Path $tempRoot 'tools\brand\generate.py'
$validator = Join-Path $tempRoot 'tools\brand\validate.py'

uv run --python 3.11 --with-requirements $requirements $generator
if ($LASTEXITCODE -ne 0) { throw "Initial brand generation failed with exit $LASTEXITCODE" }
uv run --python 3.11 --with-requirements $requirements $validator
if ($LASTEXITCODE -ne 0) { throw "Initial brand validation failed with exit $LASTEXITCODE" }

function Get-OutputInventory {
    $files = @(Get-ChildItem -Recurse -File (Join-Path $tempRoot 'web\public\brand'))
    $files += Get-Item (Join-Path $tempRoot 'web\src\styles\brand-tokens.css')
    return (($files | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($tempRoot.Length).TrimStart('\').Replace('\', '/')
        (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash + ' ' + $relative
    }) -join "`n")
}

$firstInventory = Get-OutputInventory
uv run --python 3.11 --with-requirements $requirements $generator
if ($LASTEXITCODE -ne 0) { throw "Repeat brand generation failed with exit $LASTEXITCODE" }
uv run --python 3.11 --with-requirements $requirements $validator
if ($LASTEXITCODE -ne 0) { throw "Repeat brand validation failed with exit $LASTEXITCODE" }
if ($firstInventory -cne (Get-OutputInventory)) { throw 'Generated brand outputs changed between runs' }

$brandFileCount = (Get-ChildItem -Recurse -File (Join-Path $tempRoot 'web\public\brand')).Count
Write-Output "PASS: $brandFileCount brand files plus generated CSS are byte-identical across two runs."
Write-Output "Temporary output: $tempRoot"
