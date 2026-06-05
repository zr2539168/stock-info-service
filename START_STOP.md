# Start / Stop Scripts

Windows CMD:

```bat
start.bat
stop.bat
```

PowerShell:

```powershell
.\scripts\start.ps1
.\scripts\stop.ps1
```

Optional arguments:

```powershell
.\scripts\start.ps1 -Port 8001
.\scripts\start.ps1 -NoInstall
.\scripts\stop.ps1 -ByPort
```

The start script creates `.venv` when needed, installs dependencies, starts
`uvicorn app.main:app` in the background, writes the PID to
`data/service.pid`, and writes logs to `logs/service.out.log` and
`logs/service.err.log`.
