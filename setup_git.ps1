# Git Repository Setup Script
# Sets up and pushes to GitHub repository

Write-Host "Setting up Git repository..." -ForegroundColor Green

# Initialize git if not already done
if (Test-Path .git) {
    Write-Host "✓ Git already initialized" -ForegroundColor Yellow
} else {
    git init
    Write-Host "✓ Git initialized" -ForegroundColor Green
}

# Configure git (update with your actual name and email)
git config user.name "VXC Developer"
git config user.email "gwils031@users.noreply.github.com"
Write-Host "✓ Git config set" -ForegroundColor Green

# Add remote
$remoteExists = git remote | Select-String "origin"
if (-not $remoteExists) {
    git remote add origin https://github.com/gwils031/VXC_ADV_Controller.git
    Write-Host "✓ Remote 'origin' added" -ForegroundColor Green
} else {
    git remote set-url origin https://github.com/gwils031/VXC_ADV_Controller.git
    Write-Host "✓ Remote 'origin' updated" -ForegroundColor Yellow
}

# Add all files (respecting .gitignore)
git add .
Write-Host "✓ Files staged" -ForegroundColor Green

# Create initial commit
git commit -m "Initial commit: VXC/ADV Flow Measurement System

- Complete PyQt5 GUI with 4 tabs
- VXC Stepping Motor Controller integration (COM8 @ 9600 baud)
- ADV FlowTracker2 integration
- Port/Protocol Probe for device discovery
- Independent VXC and ADV connection management
- Jog controls and position management
- Configuration management via YAML
- Comprehensive documentation"

Write-Host "✓ Initial commit created" -ForegroundColor Green

# Push to GitHub
Write-Host "`nPushing to GitHub..." -ForegroundColor Cyan
git branch -M main
git push -u origin main --force

Write-Host "`n✓ Successfully pushed to GitHub!" -ForegroundColor Green
Write-Host "Repository: https://github.com/gwils031/VXC_ADV_Controller" -ForegroundColor Cyan
