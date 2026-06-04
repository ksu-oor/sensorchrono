Write-Host "Watching for USB device changes for 30 seconds..."
Write-Host "Unplug the AirPods now, then plug them back in.`n"

$before = Get-PnpDevice -PresentOnly | Select-Object -ExpandProperty InstanceId
$start = Get-Date

while (((Get-Date) - $start).TotalSeconds -lt 30) {
    Start-Sleep -Milliseconds 500
    $now = Get-PnpDevice -PresentOnly
    $nowIds = $now | Select-Object -ExpandProperty InstanceId
    $added = $nowIds | Where-Object { $before -notcontains $_ }
    $removed = $before | Where-Object { $nowIds -notcontains $_ }
    foreach ($id in $added) {
        $d = $now | Where-Object { $_.InstanceId -eq $id }
        Write-Host ("[+] {0,-12} {1}  ({2})" -f $d.Class, $d.FriendlyName, $d.Status) -ForegroundColor Green
    }
    foreach ($id in $removed) {
        Write-Host ("[-] removed: {0}" -f $id) -ForegroundColor Yellow
    }
    $before = $nowIds
}
Write-Host "`nDone."
