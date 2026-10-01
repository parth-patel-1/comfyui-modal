$ErrorActionPreference = "Stop"
$u = Get-Content d:\parth\comfyui_modal\scripts\.testuser | ConvertFrom-Json
$envLines = Get-Content d:\parth\comfyui_modal\backend\.env
$surl = ($envLines | Select-String '^SUPABASE_URL=(.+)$').Matches[0].Groups[1].Value.Trim()
$skey = ($envLines | Select-String '^SUPABASE_ANON_KEY=(.+)$').Matches[0].Groups[1].Value.Trim()

$login = Invoke-RestMethod -Uri "$surl/auth/v1/token?grant_type=password" -Method Post `
  -Headers @{ apikey = $skey; "Content-Type" = "application/json" } `
  -Body (@{ email = $u.email; password = $u.password } | ConvertTo-Json)
$tok = $login.access_token
$H = @{ Authorization = "Bearer $tok" }
$J = @{ Authorization = "Bearer $tok"; "Content-Type" = "application/json" }
$B = "http://127.0.0.1:8900"

Write-Host "== /api/me =="
(Invoke-RestMethod -Uri "$B/api/me" -Headers $H) | ConvertTo-Json -Compress

Write-Host "== overview =="
$o = Invoke-RestMethod -Uri "$B/api/admin/overview" -Headers $H
"users=$($o.users) gens_total=$($o.generations_total) credits=$($o.credits_in_circulation) maintenance=$($o.maintenance_mode)"

Write-Host "== users (search test) =="
$users = Invoke-RestMethod -Uri "$B/api/admin/users?q=tester" -Headers $H
$users | ForEach-Object { "  $($_.email) role=$($_.role) balance=$($_.balance) gens=$($_.generations) spent=$($_.credits_spent)" }

Write-Host "== settings =="
$s = Invoke-RestMethod -Uri "$B/api/admin/settings" -Headers $H
"site=$($s.app.site_name) grant=$($s.app.signup_grant_credits) pricing_rules=$($s.pricing.Count) engines=$($s.engines.Count)"

Write-Host "== modal =="
$m = Invoke-RestMethod -Uri "$B/api/admin/modal" -Headers $H
"image_gpu=$($m.settings.image_gpu) video_gpu=$($m.settings.video_gpu) rates=$(($m.gpu_rates | ConvertTo-Json -Compress)) deploys=$($m.deploys.Count)"

Write-Host "== PUT pricing image base_credits=6 =="
(Invoke-RestMethod -Uri "$B/api/admin/pricing/image" -Method Put -Headers $J -Body '{"base_credits":6}') | ConvertTo-Json -Compress

Write-Host "== PUT settings (daily_job_cap) =="
(Invoke-RestMethod -Uri "$B/api/admin/settings" -Method Put -Headers $J -Body '{"daily_job_cap":250}') | ConvertTo-Json -Compress

Write-Host "== credits adjust +10 self =="
$me = Invoke-RestMethod -Uri "$B/api/me" -Headers $H
(Invoke-RestMethod -Uri "$B/api/admin/users/$($me.id)/credits" -Method Post -Headers $J -Body '{"delta":10,"note":"admin smoke test"}') | ConvertTo-Json -Compress

Write-Host "== credits adjust 0 (should fail 400) =="
try { Invoke-RestMethod -Uri "$B/api/admin/users/$($me.id)/credits" -Method Post -Headers $J -Body '{"delta":0}' } catch { "  -> $($_.Exception.Response.StatusCode.value__) $($_.ErrorDetails.Message)" }

Write-Host "== self-suspend (should fail 400) =="
try { Invoke-RestMethod -Uri "$B/api/admin/users/$($me.id)/status" -Method Post -Headers $J -Body '{"status":"suspended"}' } catch { "  -> $($_.Exception.Response.StatusCode.value__) $($_.ErrorDetails.Message)" }

Write-Host "== toggle engine video disabled then enabled =="
(Invoke-RestMethod -Uri "$B/api/admin/engines/video/enabled?enabled=false" -Method Put -Headers $H) | ConvertTo-Json -Compress
(Invoke-RestMethod -Uri "$B/api/admin/engines/video/enabled?enabled=true" -Method Put -Headers $H) | ConvertTo-Json -Compress

Write-Host "== audit =="
(Invoke-RestMethod -Uri "$B/api/admin/audit?limit=8" -Headers $H) | ForEach-Object { "  $($_.action) target=$($_.target) by=$($_.admin_email)" }

Write-Host "== revert pricing/base =="
(Invoke-RestMethod -Uri "$B/api/admin/pricing/image" -Method Put -Headers $J -Body '{"base_credits":5}') | ConvertTo-Json -Compress
(Invoke-RestMethod -Uri "$B/api/admin/settings" -Method Put -Headers $J -Body '{"daily_job_cap":200}') | ConvertTo-Json -Compress
Write-Host "DONE"