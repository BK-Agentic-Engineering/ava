param(
    [string]$Image = 'lifemate-smolagents:local',
    [string]$Assets = (Join-Path $PSScriptRoot '..\..\MILESTONE1\models')
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$modelAssets = (Resolve-Path -LiteralPath $Assets).Path
$binaryCache = Join-Path $repo 'tmp\docker-build-assets'
python (Join-Path $PSScriptRoot 'prepare_build.py') --cache $binaryCache
if ($LASTEXITCODE -ne 0) { throw 'Preparing the pinned llama.cpp binary failed' }
docker build --progress plain --build-context "model_assets=$modelAssets" --build-context "llama_release=$binaryCache" --tag $Image --file (Join-Path $repo 'Dockerfile') $repo
if ($LASTEXITCODE -ne 0) { throw 'Docker build failed' }
