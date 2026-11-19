# Starts the API, coder workstation and dashboard in separate windows.
# Prerequisite: Ollama is running and the model exists (ollama create icd-coder -f Modelfile).
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Create the virtual env first (see README)."; exit 1 }

Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit","-Command","& '$py' -m uvicorn app.api:app --port 8001"
Start-Sleep -Seconds 4
Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit","-Command","& '$py' -m streamlit run workstation.py"
Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit","-Command","& '$py' -m streamlit run dashboard.py --server.port 8502"
Write-Host "API: http://localhost:8001/docs | Workstation: http://localhost:8501 | Dashboard: http://localhost:8502"
