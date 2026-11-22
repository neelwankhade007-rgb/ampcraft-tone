# Ampcraft Tone

## Setup

Use Python 3.10 or later. From the project directory, create and activate a
virtual environment, then install the project dependencies:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, allow scripts for the current terminal with:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

## Configuration

Copy `.env.example` to `.env` and add a `GROQ_API_KEY` if you want to use Groq.
Leave it blank to use the local Ollama fallback configured in the app.
