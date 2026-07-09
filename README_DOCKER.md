# Docker setup for Anirudh WRF Project

This project has two services:

- `backend`: FastAPI API running on port `8000`
- `frontend`: Vite React app running on port `5173`

## 1. Install Docker Desktop

On Windows, install Docker Desktop first. Then restart your laptop and check:

```powershell
docker --version
docker compose version
```

## 2. Start the full project

Open PowerShell in the project root folder, where `docker-compose.yml` is present:

```powershell
cd C:\Users\veele\OneDrive\Desktop\anirudhwrf

docker compose up --build
```

Open these URLs:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- FastAPI docs: http://localhost:8000/docs

## 3. Stop the project

```powershell
docker compose down
```

## 4. Start again without rebuilding

```powershell
docker compose up
```

## 5. Rebuild after code/dependency changes

```powershell
docker compose up --build
```

## 6. View logs

```powershell
docker compose logs -f backend
docker compose logs -f frontend
```

## 7. Add WRF files

Put your WRF NetCDF files in:

```text
backend/data/wrf/
```

That folder is mounted into the backend container at:

```text
/app/data/wrf/
```

## 8. Ollama assistant note

If you use the assistant feature, run Ollama on your laptop first:

```powershell
ollama serve
ollama pull llama3.2:3b
```

The backend container uses this URL to reach Ollama on your host machine:

```text
http://host.docker.internal:11434
```

## 9. Voice features note

This Docker setup is lightweight and does not install heavy voice dependencies like `torch`, `faster-whisper`, and `coqui-tts` by default. The main WRF dashboard and API will run normally. If you need `/transcribe` and `/tts` inside Docker, add those packages back into `backend/requirements.docker.txt`, but expect the Docker image to become much larger.
