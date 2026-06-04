Write-Host "=== USB devices (recently enumerated) ==="
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'USB' -and $_.FriendlyName -match 'AirPods|Apple|Audio|Headphone|USB' } | Select-Object Status,Class,FriendlyName | Format-Table -AutoSize

Write-Host "`n=== Audio endpoints (playback) ==="
Get-PnpDevice -Class AudioEndpoint -PresentOnly | Select-Object Status,FriendlyName | Format-Table -AutoSize

Write-Host "`n=== MEDIA class devices ==="
Get-PnpDevice -Class MEDIA -PresentOnly | Select-Object Status,FriendlyName | Format-Table -AutoSize

Write-Host "`n=== Any device with 'AirPods' in name ==="
Get-PnpDevice | Where-Object { $_.FriendlyName -match 'AirPods|Apple' } | Select-Object Status,Class,FriendlyName,InstanceId | Format-Table -AutoSize
