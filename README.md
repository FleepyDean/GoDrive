# GoDrive

GoDrive is a real-time ride request monitoring system for Telegram groups. It listens to ride requests, extracts pickup/dropoff locations, and displays them in a minimalist Progressive Web App (PWA) with instant updates via Server-Sent Events (SSE).

## Features

- **Real-time updates** via Server-Sent Events (no polling)
- **Minimalist, mobile-optimized UI** with clean monochrome design
- **Instant message appearance** — messages appear in ~50–200ms (avatars load in background)
- **Route pills** showing pickup → dropoff at a glance
- **Reply previews** with original message snippets (batched via SQL JOIN)
- **Contact history** tracking for quick access to past interactions
- **PWA support** — installable as a mobile app

## Architecture

GoDrive runs as **two separate processes**:

1. **`GoDrive.py`** — Telegram userbot (Telethon) that listens to groups, extracts ride data, and writes to SQLite
2. **`app.py`** — Flask API server that serves the PWA and pushes SSE updates to browsers

The two communicate via:
- SQLite database (shared)
- Internal `/api/notify` endpoint that GoDrive.py calls after DB writes to trigger SSE refresh

## Setup Instructions

1. **Clone the Repository**
   ```bash
   git clone https://github.com/FleepyDean/GoDrive.git
   cd GoDrive
   ```

2. **Create a Virtual Environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # On Windows
   # On Linux/Mac: source .venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up Environment Variables**
   Create a `.env` file in the root directory (see `.env.example` for reference). Required variables:

   - `API_ID` — Telegram API ID (from my.telegram.org)
   - `API_HASH` — Telegram API Hash (from my.telegram.org)
   - `BOT_TOKEN` — Telegram Bot Token (from @BotFather)
   - `GROUP_ID` — Dictionary mapping Telegram chat IDs to group names
   - `CUSTOM_LOCATIONS` — Dictionary of location aliases for parsing
   - `UTM_COORDS` — Central coordinates for relevance filtering
   - `MAX_RADIUS_KM` — Maximum distance for location relevance (default: 30)

## Running the Application

You need **two terminals** running simultaneously:

### Terminal 1 — Flask PWA server
```bash
.venv\Scripts\activate
python app.py
```
Then open **http://localhost:5000** in your browser.

### Terminal 2 — Telegram userbot
```bash
.venv\Scripts\activate
python GoDrive.py
```

Both processes must be running for the app to work. GoDrive.py listens to Telegram and writes to the database; Flask serves the PWA and streams real-time updates to browsers.

## Performance

| Scenario | Latency |
|---|---|
| Cached sender (avatar on disk) | ~50–200ms |
| New sender (avatar download) | ~50–200ms (avatar loads in background) |
| SSE refresh event | Instant (no polling delay) |

## Project Structure

```
GoDrive/
├── app.py              # Flask API + SSE endpoint
├── GoDrive.py          # Telegram userbot (Telethon)
├── config.py           # Configuration & environment variables
├── requirements.txt    # Python dependencies
├── .env                # Environment variables (not in git)
└── pwa/                # Progressive Web App
    ├── index.html      # Main dashboard
    ├── history.html    # Contact history
    ├── app.js          # Frontend logic (SSE client, incremental DOM)
    ├── style.css       # Minimalist design system
    ├── manifest.json   # PWA manifest
    └── avatars/        # Cached profile photos
```

## Development Notes

- **SSE instead of polling** — browsers maintain an open connection to `/api/stream` for instant updates
- **Incremental DOM updates** — only changed cards are patched, not full re-renders
- **Avatar non-blocking** — messages appear immediately; avatars download in background and update via SSE
- **SQL JOIN for replies** — reply previews are batched in `/api/messages` to avoid per-card HTTP requests
- **Google Maps removed** — geocoding and distance calculation code has been removed (unused)

## License

This project is licensed. Unauthorized usage or illegal activities will be taken action.