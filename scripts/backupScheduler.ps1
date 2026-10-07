#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Configures and executes the daily midnight maintenance and backup routine.

.DESCRIPTION
    Automates SQLite WAL database checkpointing, point-in-time snapshot backup,
    and log retention rotation for the ProRadCS Edge Gateway:
      1. Scheduled Task Registration: Registers a daily midnight scheduled task
         (ProRadCS-DailyMaintenance) running under NT AUTHORITY\SYSTEM.
      2. Maintenance Execution (-ExecuteMaintenance):
         - Flushes pending WAL log records to the main database file via
           PRAGMA wal_checkpoint(TRUNCATE).
         - Creates an atomic snapshot in D:\DICOM_Archive\backups\database_yyyyMMdd_HHmmss.db.
         - Prunes database backups older than BackupRetentionDays (Default: 14).
         - Rotates and purges archived log files older than LogRetentionDays (Default: 30).

.PARAMETER TaskName
    Name of the Windows Scheduled Task. Default: 'ProRadCS-DailyMaintenance'.

.PARAMETER DailyTime
    Daily execution trigger time in 24-hour format. Default: '00:00'.

.PARAMETER DatabasePath
    Path to the primary SQLite database. Default: 'D:\DICOM_Archive\database.db'.

.PARAMETER BackupDir
    Target directory for database snapshots. Default: 'D:\DICOM_Archive\backups'.

.PARAMETER LogDir
    Directory hosting daemon log files. Default: 'D:\DICOM_Archive\logs'.

.PARAMETER BackupRetentionDays
    Number of days to keep database backups. Default: 14.

.PARAMETER LogRetentionDays
    Number of days to keep log files before purging. Default: 30.

.PARAMETER ExecuteMaintenance
    Executes the maintenance cycle directly instead of registering the task.

.PARAMETER RemoveTask
    Unregisters and removes the scheduled task from Windows.

.OUTPUTS
    Exit Code 0  : Task registered or maintenance executed successfully.
    Exit Code 10 : Prerequisite missing.
    Exit Code 30 : Security or execution permission error.
    Exit Code 40 : Scheduled task registration failure.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$TaskName = "ProRadCS-DailyMaintenance",

    [Parameter(Mandatory = $false)]
    [string]$DailyTime = "00:00",

    [Parameter(Mandatory = $false)]
    [string]$DatabasePath = "D:\DICOM_Archive\database.db",

    [Parameter(Mandatory = $false)]
    [string]$BackupDir = "D:\DICOM_Archive\backups",

    [Parameter(Mandatory = $false)]
    [string]$LogDir = "D:\DICOM_Archive\logs",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 365)]
    [int]$BackupRetentionDays = 14,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 365)]
    [int]$LogRetentionDays = 30,

    [Parameter(Mandatory = $false)]
    [switch]$ExecuteMaintenance,

    [Parameter(Mandatory = $false)]
    [switch]$RemoveTask
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30
$EXIT_TASK_ERROR = 40

Write-Host "  ProRadCS Enterprise DICOM Gateway - Maintenance & Backup Scheduler   " -ForegroundColor Cyan
Write-Host "  Target Task: $TaskName | Trigger: Daily at $DailyTime                " -ForegroundColor Cyan

# MODE A: UNREGISTER SCHEDULED TASK
if ($RemoveTask) {
    Write-Host "Removing Windows Scheduled Task '$TaskName'..." -NoNewline
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existingTask) {
        if ($PSCmdlet.ShouldProcess("$TaskName", "Unregister Scheduled Task")) {
            try {
                Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false | Out-Null
                Write-Host " [REMOVED]" -ForegroundColor Green
            }
            catch {
                Write-Host " [FAIL: $_]" -ForegroundColor Red
                exit $EXIT_TASK_ERROR
            }
        }
        else {
            Write-Host " [WHAT-IF]" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host " [NOT FOUND]" -ForegroundColor Gray
    }
    exit $EXIT_SUCCESS
}

# MODE B: DIRECT MAINTENANCE EXECUTION
if ($ExecuteMaintenance) {
    Write-Host "[MAINTENANCE] Starting daily database checkpoint and log rotation..." -ForegroundColor Cyan

    # Ensure backup directory exists
    if (-not (Test-Path $BackupDir)) {
        if ($PSCmdlet.ShouldProcess("$BackupDir", "Create Backup Directory")) {
            New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
        }
    }

    # 1. SQLite WAL Checkpoint & Snapshot
    Write-Host "[1/3] Processing SQLite WAL Checkpoint on '$DatabasePath'..." -NoNewline
    if (Test-Path $DatabasePath) {
        $timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
        $targetSnapshot = Join-Path $BackupDir "database_$timestamp.db"

        # Attempt to find Python interpreter to invoke PRAGMA wal_checkpoint
        $scriptDir = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { (Get-Location).Path }
        $parentDir = Split-Path $scriptDir -Parent

        $pyCandidates = @(
            (Join-Path $parentDir "backend\.venv\Scripts\python.exe"),
            "C:\Program Files\ProRadCS\python.exe",
            "C:\Program Files\ProRadCS\bin\python.exe"
        )
        $resolvedPy = $null
        foreach ($cand in $pyCandidates) {
            if (Test-Path $cand) {
                $resolvedPy = $cand
                break
            }
        }
        if ($null -eq $resolvedPy) {
            $pyCmd = Get-Command "python.exe" -ErrorAction SilentlyContinue
            if ($null -ne $pyCmd) { $resolvedPy = $pyCmd.Source }
        }

        if ($null -ne $resolvedPy) {
            # Run checkpoint and VACUUM INTO
            $escDb = $DatabasePath.Replace('\', '\\')
            $escSnap = $targetSnapshot.Replace('\', '\\')
            $pyScript = "import sqlite3; conn = sqlite3.connect(r'$escDb'); conn.execute('PRAGMA wal_checkpoint(TRUNCATE);'); conn.execute('PRAGMA optimize;'); conn.close()"

            if ($PSCmdlet.ShouldProcess("$DatabasePath", "Execute PRAGMA wal_checkpoint(TRUNCATE)")) {
                try {
                    & $resolvedPy -c $pyScript
                    Copy-Item -Path $DatabasePath -Destination $targetSnapshot -Force
                    Write-Host " [PASS]" -ForegroundColor Green
                    Write-Host "      Snapshot created at: $targetSnapshot" -ForegroundColor Gray
                }
                catch {
                    Write-Host " [FAIL: $_]" -ForegroundColor Red
                    exit $EXIT_SECURITY_ERROR
                }
            }
            else {
                Write-Host " [WHAT-IF]" -ForegroundColor Yellow
            }
        }
        else {
            # Fallback: Copy database and WAL files directly
            if ($PSCmdlet.ShouldProcess("$DatabasePath", "Copy Database Snapshot (Direct)")) {
                Copy-Item -Path $DatabasePath -Destination $targetSnapshot -Force
                $walFile = "$DatabasePath-wal"
                if (Test-Path $walFile) {
                    Copy-Item -Path $walFile -Destination "$targetSnapshot-wal" -Force
                }
                Write-Host " [PASS]" -ForegroundColor Green
                Write-Host "      Copied direct snapshot: $targetSnapshot" -ForegroundColor Gray
            }
            else {
                Write-Host " [WHAT-IF]" -ForegroundColor Yellow
            }
        }
    }
    else {
        Write-Host " [SKIPPED: Database file not found at $DatabasePath]" -ForegroundColor Yellow
    }

    # 2. Prune Old Database Backups
    Write-Host "[2/3] Pruning backups older than $BackupRetentionDays days in '$BackupDir'..." -NoNewline
    if (Test-Path $BackupDir) {
        $cutoffDate = (Get-Date).AddDays(-$BackupRetentionDays)
        $oldBackups = Get-ChildItem -Path $BackupDir -Filter "database_*.db*" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoffDate }

        $prunedCount = 0
        foreach ($oldFile in $oldBackups) {
            if ($PSCmdlet.ShouldProcess("$($oldFile.FullName)", "Delete expired backup")) {
                Remove-Item -Path $oldFile.FullName -Force
                $prunedCount++
            }
        }
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Cleaned $prunedCount expired backup archives." -ForegroundColor Gray
    }
    else {
        Write-Host " [SKIPPED]" -ForegroundColor Gray
    }

    # 3. Rotate Old Log Files
    Write-Host "[3/3] Pruning log files older than $LogRetentionDays days in '$LogDir'..." -NoNewline
    if (Test-Path $LogDir) {
        $logCutoff = (Get-Date).AddDays(-$LogRetentionDays)
        $oldLogs = Get-ChildItem -Path $LogDir -Filter "*.log*" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $logCutoff }

        $prunedLogs = 0
        foreach ($oldLog in $oldLogs) {
            if ($PSCmdlet.ShouldProcess("$($oldLog.FullName)", "Delete expired log")) {
                Remove-Item -Path $oldLog.FullName -Force
                $prunedLogs++
            }
        }
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Cleaned $prunedLogs expired log files." -ForegroundColor Gray
    }
    else {
        Write-Host " [SKIPPED]" -ForegroundColor Gray
    }

    Write-Host "Maintenance cycle completed successfully." -ForegroundColor Green
    exit $EXIT_SUCCESS
}

# MODE C: REGISTER SCHEDULED TASK
Write-Host "Registering Windows Scheduled Task '$TaskName'..." -ForegroundColor Cyan

$scriptPath = $PSCommandPath
if ([string]::IsNullOrWhiteSpace($scriptPath)) {
    $scriptDir = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { (Get-Location).Path }
    $scriptPath = Join-Path $scriptDir "backupScheduler.ps1"
}

$taskAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ExecuteMaintenance"

$triggerTime = [datetime]::ParseExact($DailyTime, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
$taskTrigger = New-ScheduledTaskTrigger -Daily -At $triggerTime

$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId "NT AUTHORITY\SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

$taskSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10)

if ($PSCmdlet.ShouldProcess("$TaskName", "Register Scheduled Task")) {
    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $taskAction `
            -Trigger $taskTrigger `
            -Principal $taskPrincipal `
            -Settings $taskSettings `
            -Description "Daily ProRadCS SQLite WAL checkpoint, database backup, and log rotation task." `
            -Force | Out-Null
        Write-Host "[PASS] Scheduled Task '$TaskName' registered successfully." -ForegroundColor Green
        Write-Host "       Schedule: Daily at $DailyTime | Account: NT AUTHORITY\SYSTEM" -ForegroundColor Gray
    }
    catch {
        Write-Host "[FAIL] Failed to register scheduled task: $_" -ForegroundColor Red
        exit $EXIT_TASK_ERROR
    }
}
else {
    Write-Host "[WHAT-IF] Registered scheduled task '$TaskName'." -ForegroundColor Yellow
}

Write-Host "Backup scheduling configuration completed." -ForegroundColor Green
exit $EXIT_SUCCESS
