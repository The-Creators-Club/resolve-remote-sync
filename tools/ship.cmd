@echo off
rem One-command release: deploy dashboard, publish builds, upgrade this
rem machine, verify. Wraps tools\ship.ps1 with an execution-policy bypass so
rem it runs from any fresh window. Pass-through args: -DashboardUrl, -AdminUser,
rem -DashboardOnly, -Recreate, -SkipLocalUpgrade, -SkipTests, -AllowDirty.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ship.ps1" %*
