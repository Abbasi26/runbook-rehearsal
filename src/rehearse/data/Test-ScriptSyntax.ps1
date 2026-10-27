# Parse a PowerShell file. This script does not dot-source or execute the target.
param(
    [Parameter(Mandatory = $true)]
    [string] $Path
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Output '{"ok":false,"errors":[{"line":0,"column":0,"message":"file not found"}]}'
    exit 2
}

$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $Path,
    [ref] $tokens,
    [ref] $parseErrors
)

if ($null -eq $parseErrors) {
    $parseErrors = @()
}

$items = New-Object System.Collections.Generic.List[object]
foreach ($err in @($parseErrors)) {
    if ($null -eq $err) {
        continue
    }
    $items.Add([pscustomobject]@{
        line    = [int] $err.Extent.StartLineNumber
        column  = [int] $err.Extent.StartColumnNumber
        message = [string] $err.Message
    })
}

$result = [pscustomobject]@{
    ok     = ($items.Count -eq 0)
    errors = $items
}
$result | ConvertTo-Json -Compress -Depth 4
if ($items.Count -gt 0) {
    exit 1
}
exit 0
