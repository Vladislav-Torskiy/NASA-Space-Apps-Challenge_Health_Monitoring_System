# ASTRA-Med Frontend (Role 1 — Frontend & Interactive Body UI Lead)

This directory is reserved for the React + TypeScript + Vite + Tailwind CSS astronaut health console.

## Backend API Connection
Run the FastAPI backend on port `8000` (`http://localhost:8000`), then check live API contracts in Swagger UI:
- `http://localhost:8000/docs`
- Full JSON contract specifications are documented in `../ARCHITECTURE.md` (Section 4).

Recommended `.env.local` inside `frontend/`:
```env
VITE_API_BASE_URL=http://localhost:8000
```
