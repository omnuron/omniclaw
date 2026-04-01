$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Building OmniClaw npm release artifacts..."

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm is required to run build.ps1"
}

Write-Host "Cleaning previous build artifacts..."
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
Get-ChildItem -Filter "*.tgz" -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host "Installing dependencies..."
npm install

Write-Host "Running TypeScript checks..."
npm run typecheck

Write-Host "Building package..."
npm run build

Write-Host "Creating tarball..."
npm pack

Write-Host ""
Write-Host "Build complete."
Write-Host "Next:"
Write-Host "  1. Inspect package contents: npm pack --dry-run"
Write-Host "  2. Publish with: npm publish"
