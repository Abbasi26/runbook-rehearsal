# Parsed with Parser.ParseFile. rehearse does not execute this file.
$share = "\\fs01.ops.harborpine.example\finance"
if (Test-Path -LiteralPath $share) {
    Write-Output "present"
