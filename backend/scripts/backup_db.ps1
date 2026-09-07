# Daily DB backup. Schedule with Windows Task Scheduler (or cron on Linux: see backup_db.sh).
# orders_cache can be rebuilt from the API; customers, sessions and logs cannot.
param(
  [string]$OutDir = "$PSScriptRoot\..\backups",
  [string]$MysqlHost = "localhost",
  [string]$User = "root",
  [string]$Password = "root",
  [string]$Database = "order_bot",
  [int]$KeepDays = 14
)
New-Item -ItemType Directory -Force $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$file = Join-Path $OutDir "order_bot-$stamp.sql"
& mysqldump -h $MysqlHost -u $User -p$Password --single-transaction --routines $Database | Out-File -Encoding utf8 $file
Get-ChildItem $OutDir -Filter "order_bot-*.sql" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } | Remove-Item -Force
"backup written: $file"
