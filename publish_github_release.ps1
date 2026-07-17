param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$Repo = $env:SCRAPER_GITHUB_REPO,
    [string]$Token = $env:GITHUB_TOKEN,
    [string]$ExePath = "$env:USERPROFILE\Desktop\ScraperCorreos.exe"
)

$ErrorActionPreference = "Stop"

if (-not $Repo) { throw "Falta SCRAPER_GITHUB_REPO o el parámetro -Repo (formato usuario/repositorio)." }
if (-not $Token) { throw "Falta GITHUB_TOKEN con permisos para crear releases." }
if (-not (Test-Path $ExePath)) { throw "No existe el ejecutable: $ExePath" }

$headers = @{
    Authorization = "Bearer $Token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$releaseBody = @{
    tag_name = $Version
    name = $Version
    body = "Nueva versión de ScraperCorreos."
    draft = $false
    prerelease = $false
} | ConvertTo-Json

$release = Invoke-RestMethod `
    -Method Post `
    -Uri "https://api.github.com/repos/$Repo/releases" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $releaseBody

$assetName = Split-Path $ExePath -Leaf
$uploadUrl = ($release.upload_url -replace "\{.*\}", "") + "?name=$assetName"

Invoke-RestMethod `
    -Method Post `
    -Uri $uploadUrl `
    -Headers $headers `
    -ContentType "application/octet-stream" `
    -InFile $ExePath

Write-Host "Release publicada: $($release.html_url)"
