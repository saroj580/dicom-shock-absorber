#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Provisions the dedicated, non-interactive PacsServiceWorker service account.

.DESCRIPTION
    Creates and configures the local service account for ProRadCS Edge Gateway
    daemons (DicomReceiverService, ProcessorWorker, WebDashboardService).
    Applies zero-trust host security policies according to IEC 62304 / NHS / HIPAA:
      1. Generates or sets a high-entropy non-expiring password.
      2. Ensures the account is strictly unprivileged (NOT a member of Administrators).
      3. Grants LSA User Right: SeServiceLogonRight (Log on as a service).
      4. Explicitly denies interactive logon rights to eliminate attack surface:
         - SeDenyInteractiveLogonRight (Local console / keyboard logon denied)
         - SeDenyRemoteInteractiveLogonRight (RDP / Remote Desktop logon denied)
         - SeDenyNetworkLogonRight (SMB / Network share access denied)

.PARAMETER AccountName
    Name of the local service account. Default: 'PacsServiceWorker'.

.PARAMETER Password
    Optional explicit SecureString password. If omitted, a cryptographically
    secure 32-character random password is generated and applied.

.PARAMETER ForceResetPassword
    If specified, updates the password for an existing account.

.OUTPUTS
    Exit Code 0  : Account configured successfully with all LSA rights applied.
    Exit Code 10 : Prerequisite missing.
    Exit Code 30 : Security or LSA privilege assignment error.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$AccountName = "PacsServiceWorker",

    [Parameter(Mandatory = $false)]
    [System.Security.SecureString]$Password = $null,

    [Parameter(Mandatory = $false)]
    [switch]$ForceResetPassword
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30

Write-Host "  ProRadCS Enterprise DICOM Gateway - Service Account Provisioning     " -ForegroundColor Cyan
Write-Host "  Target Account: $AccountName | Security Policy: Least Privilege       " -ForegroundColor Cyan

# 1. P/Invoke Definition for LSA Policy Management (Advapi32.dll)
$lsaTypeDefinition = @'
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;

public class LsaPolicyManager {
    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_OBJECT_ATTRIBUTES {
        public int Length;
        public IntPtr RootDirectory;
        public IntPtr ObjectName;
        public uint Attributes;
        public IntPtr SecurityDescriptor;
        public IntPtr SecurityQualityOfService;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct LSA_UNICODE_STRING {
        public ushort Length;
        public ushort MaximumLength;
        public string Buffer;
    }

    [DllImport("advapi32.dll", PreserveSig = true)]
    private static extern uint LsaOpenPolicy(
        IntPtr SystemName,
        ref LSA_OBJECT_ATTRIBUTES ObjectAttributes,
        uint DesiredAccess,
        out IntPtr PolicyHandle
    );

    [DllImport("advapi32.dll", PreserveSig = true)]
    private static extern uint LsaAddAccountRights(
        IntPtr PolicyHandle,
        byte[] AccountSid,
        LSA_UNICODE_STRING[] UserRights,
        uint CountOfRights
    );

    [DllImport("advapi32.dll", PreserveSig = true)]
    private static extern uint LsaClose(IntPtr ObjectHandle);

    private const uint POLICY_CREATE_ACCOUNT = 0x00000010;
    private const uint POLICY_LOOKUP_NAMES = 0x00000800;

    public static uint GrantUserRight(SecurityIdentifier sid, string privilegeName) {
        LSA_OBJECT_ATTRIBUTES objAttr = new LSA_OBJECT_ATTRIBUTES();
        objAttr.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));

        IntPtr policyHandle = IntPtr.Zero;
        uint access = POLICY_CREATE_ACCOUNT | POLICY_LOOKUP_NAMES;
        uint status = LsaOpenPolicy(IntPtr.Zero, ref objAttr, access, out policyHandle);
        if (status != 0) {
            return status;
        }

        try {
            byte[] sidBytes = new byte[sid.BinaryLength];
            sid.GetBinaryForm(sidBytes, 0);

            LSA_UNICODE_STRING[] rights = new LSA_UNICODE_STRING[1];
            rights[0] = new LSA_UNICODE_STRING {
                Length = (ushort)(privilegeName.Length * 2),
                MaximumLength = (ushort)((privilegeName.Length + 1) * 2),
                Buffer = privilegeName
            };

            return LsaAddAccountRights(policyHandle, sidBytes, rights, 1);
        } finally {
            if (policyHandle != IntPtr.Zero) {
                LsaClose(policyHandle);
            }
        }
    }
}
'@

if (-not ([System.Management.Automation.PSTypeName]'LsaPolicyManager').Type) {
    Add-Type -TypeDefinition $lsaTypeDefinition
}

# 2. Account Generation / Password Initialization

function New-CryptographicPassword {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    # Generate 32-character base64 with mixed characters and symbols
    $raw = [Convert]::ToBase64String($bytes) + "!A1#"
    return ConvertTo-SecureString $raw -AsPlainText -Force
}

$effectivePassword = $Password
if ($null -eq $effectivePassword) {
    $effectivePassword = New-CryptographicPassword
}


# 3. Local Account Verification & Creation

Write-Host "[1/3] Checking local account status for '$AccountName'..." -NoNewline
$existingUser = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue

if ($null -eq $existingUser) {
    Write-Host " [NEW]" -ForegroundColor Yellow
    Write-Host "      Account does not exist. Creating local user '$AccountName'..." -ForegroundColor Cyan

    if ($PSCmdlet.ShouldProcess("$AccountName", "Create Local User")) {
        New-LocalUser -Name $AccountName `
            -Password $effectivePassword `
            -Description "ProRadCS Enterprise DICOM Gateway Service Account" `
            -AccountNeverExpires `
            -PasswordNeverExpires `
            -UserMayNotChangePassword | Out-Null
        Write-Host "      User '$AccountName' successfully created with non-expiring credentials." -ForegroundColor Green
    }
}
else {
    Write-Host " [EXISTS]" -ForegroundColor Green
    Write-Host "      Account '$AccountName' exists (Enabled: $($existingUser.Enabled))." -ForegroundColor Gray

    if ($ForceResetPassword -and $PSCmdlet.ShouldProcess("$AccountName", "Reset Password")) {
        Set-LocalUser -Name $AccountName -Password $effectivePassword
        Write-Host "      Password reset applied successfully." -ForegroundColor Yellow
    }

    # Ensure flags
    Set-LocalUser -Name $AccountName -PasswordNeverExpires $true -UserMayNotChangePassword $true
}


# 4. Privilege Verification (Ensure Account is NOT Administrator)

Write-Host "[2/3] Verifying account is not a member of Administrators..." -NoNewline
$adminMembers = Get-LocalGroupMember -Group "Administrators" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }
$isAccountAdmin = $adminMembers | Where-Object { $_ -like "*\$AccountName" -or $_ -eq $AccountName }

if ($null -ne $isAccountAdmin) {
    Write-Host " [VIOLATION]" -ForegroundColor Red
    Write-Host "      Warning: '$AccountName' was found in Administrators group. Removing immediately..." -ForegroundColor Yellow
    if ($PSCmdlet.ShouldProcess("$AccountName", "Remove from Administrators")) {
        Remove-LocalGroupMember -Group "Administrators" -Member $AccountName
        Write-Host "      Successfully removed '$AccountName' from Administrators." -ForegroundColor Green
    }
}
else {
    Write-Host " [PASS]" -ForegroundColor Green
    Write-Host "      Confirmed: Account is unprivileged (Standard User context)." -ForegroundColor Gray
}

# 5. LSA Policy User Rights Assignment
Write-Host "[3/3] Enforcing LSA User Rights Assignment (Logon Policy)..." -NoNewline
try {
    $ntAccount = New-Object System.Security.Principal.NTAccount($AccountName)
    $sid = $ntAccount.Translate([System.Security.Principal.SecurityIdentifier])
}
catch {
    if (-not $PSCmdlet.ShouldProcess("$AccountName", "Resolve SID")) {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
        Write-Host "      (WhatIf dry-run: Using placeholder SID since account was not created in SAM)" -ForegroundColor Gray
        $sid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-21-0-0-0-1000")
    }
    else {
        Write-Host " [FAIL]" -ForegroundColor Red
        Write-Host "      Error resolving SID for account '$AccountName': $_" -ForegroundColor Red
        exit $EXIT_SECURITY_ERROR
    }
}

$rightsToApply = @(
    @{ Name = "SeServiceLogonRight"; Description = "Log on as a service (GRANT)" },
    @{ Name = "SeDenyInteractiveLogonRight"; Description = "Deny local console logon (DENY)" },
    @{ Name = "SeDenyRemoteInteractiveLogonRight"; Description = "Deny Remote Desktop / RDP logon (DENY)" },
    @{ Name = "SeDenyNetworkLogonRight"; Description = "Deny SMB / network share logon (DENY)" }
)

Write-Host " [APPLYING]" -ForegroundColor Cyan

foreach ($right in $rightsToApply) {
    Write-Host "      - Assigning $($right.Name) ($($right.Description))..." -NoNewline
    if ($PSCmdlet.ShouldProcess("$AccountName", "Assign LSA Right: $($right.Name)")) {
        $status = [LsaPolicyManager]::GrantUserRight($sid, $right.Name)
        if ($status -eq 0) {
            Write-Host " [OK]" -ForegroundColor Green
        }
        else {
            # STATUS_SUCCESS = 0; if non-zero, format hex code
            $hexStatus = "0x{0:X8}" -f $status
            Write-Host " [ERROR: $hexStatus]" -ForegroundColor Red
            Write-Host "        Failed to set LSA right $($right.Name)." -ForegroundColor Red
            exit $EXIT_SECURITY_ERROR
        }
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}

Write-Host "Service account '$AccountName' successfully hardened and ready for use." -ForegroundColor Green
exit $EXIT_SUCCESS
