# ASTRA-Med — Autonomous Space Telemetry & Risk Assessment

**Team:** `xterra`  
**Challenge:** NASA Space Apps Challenge 2026 — *Create Health Monitoring Software for Astronauts on Space Missions*  
**Challenge URL:** https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/?tab=resources

---

## Огляд проєкту / Overview

**ASTRA-Med** — це автономна бортова веб-консоль самодіагностики та підтримки медичних рішень для астронавтів у довготривалих космічних місіях (Artemis, навколомісячний Gateway, транзит до Марсу, планетарні бази).

За умов затримки зв'язку з Землею (**OWLT — One-Way Light Time**, від 1 секунди на орбіті до 14+ хвилин при польоті на Марс) астронавт повинен самостійно виявляти відхилення показників, оцінювати ризики з урахуванням космічних норм та приймати своєчасні рішення.

### Офіційні ресурси NASA / CSA, покладені в основу системи
- **NASA Human Research Program (HRP) — 5 Hazards of Human Spaceflight:**
  1. *Space Radiation* — кумулятивна доза радіації (`mSv`), моніторинг сонячних спалахів (Solar Particle Events).
  2. *Isolation and Confinement* — циркадні збої, динаміка сну та настрою.
  3. *Distance from Earth* — автономний аналіз ризиків, OWLT-таймер та формування компактних пакетів телеметрії для Flight Surgeon.
  4. *Gravity Fields* — адаптовані космічні пороги (0g, 0.16g, 0.38g), контроль перерозподілу рідин та SANS (Spaceflight Associated Neuro-ocular Syndrome).
  5. *Hostile Closed Environments* — реакція на дрейф CO₂, сухість шкіри/очей та мікроклімат відсіку.
- **Canadian Space Agency (CSA):** принципи моніторингу космічної радіації та телемедичні підходи для віддалених / ізольованих середовищ.
- **NASA OSDR / RadLab & PhysioNet (референсні підходи):** реалістичні 24–30-денні біометричні та радіаційні таймлайни у `data/seed_30days.json`.

---

## Структура монорепозиторію

```text
NASA-Space-Apps-Challenge_Health_Monitoring_System/
├── README.md
├── SPECS.md                # Функціональні вимоги MVP
├── ARCHITECTURE.md         # Архітектура, API-контракти, схема БД
├── .env.example
├── docker-compose.yml
├── data/
│   ├── nasa_hrp_rules.json # Космічні пороги (4 середовища), 8 зон тіла, правила HRP
│   ├── seed_30days.json    # 24-денна базова історія місії, завдання рутини, бейджі
│   └── demo_samples/       # Тестові зображення для 3 CV-режимів
├── backend/                # Роль 2 + Роль 3: FastAPI + SQLite (WAL) + Risk & Vision Engine
├── frontend/               # Роль 1: React + TypeScript + Tailwind + Interactive Body Map
└── scripts/                # Утиліти запуску та генерації демо-зображень
```

---

## Розподіл ролей команди `xterra`

1. **Роль 1 — Frontend & Interactive Body UI Lead:** інтерфейс у `frontend/` (React, TypeScript, Vite, Tailwind, SVG-мапа тіла, Recharts, WebRTC).
2. **Роль 2 — Core Backend & Mission Simulation Engineer (реалізовано):** FastAPI REST API (`backend/`), SQLite у WAL-режимі, генератор і seed-історія місії, симулятор середовищ і криз (`Fault Injection`), планувальник рутини, гейміфікація, пакет передачі на Землю з OWLT.
3. **Роль 3 — AI / Computer Vision & Diagnostic Engine:** розширення `backend/app/services/risk_engine.py` та `backend/app/services/vision_service.py` (базовий Rule + Trend Engine і детермінований OpenCV/OCR fallback вже працюють «з коробки»).
4. **Роль 4 — Space-Med Architect, Data/Content & Pitch Lead:** наповнення та валідація довідників `data/nasa_hrp_rules.json`, `data/seed_30days.json`, реальних тестових знімків у `data/demo_samples/`, QA-прогін та фінальне демо.

---

## Швидкий старт (Backend API)

### 1. Локальний запуск без Docker
```bash
cp .env.example .env
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Або з кореня репозиторію (скрипт автоматично створить `.env` із `.env.example` за відсутності):
```bash
./scripts/run_dev.sh
```
Або через **Docker Compose** (перед запуском скопіюйте `.env.example` у `.env` і за потреби додайте `GEMINI_API_KEY`):
```bash
cp .env.example .env
docker compose up --build
```
Після запуску інтерактивна документація **Swagger UI** доступна на:  
`http://localhost:8000/docs`

### 2. Перевірка лінтером та автотестами
```bash
cd backend
.venv/bin/ruff check .
.venv/bin/pytest -v
```

### 3. Доступні REST ендпоїнти (`ARCHITECTURE.md`)
- `GET /api/health` — стан сервера, БД, доступність Vision API / Tesseract
- `GET /api/dashboard` — повний знімок місії, readiness score, бейджів, 8 зон тіла, останніх метрик, рутини
- `GET /api/metrics/history?days=30` — історія замірів, пороги для активного середовища, трендові попередження
- `POST /api/metrics` — додавання нового заміру та миттєвий перерахунок ризиків
- `POST /api/vision/analyze` — мультимодальний аналіз зображення (`ultrasound`, `skin_eye`, `device_ocr`)
- `POST /api/evaluate/risk` — комплексна оцінка ризиків (статичні пороги + 5–14-денний тренд + останній CV-результат)
- `POST /api/mission/environment` — перемикання середовища (`spacecraft`, `station`, `rover`, `base`)
- `POST /api/demo/fault` — ін'єкція кризи (`solar_flare`, `co2_drift`, `sleep_deficit`, `reset_baseline`)
- `POST /api/routine/{task_id}/complete` — виконання завдання рутини, оновлення стріку та бейджів
- `POST /api/ground/transmit` — формування `Telemetry & Medical Packet` з OWLT-затримкою
