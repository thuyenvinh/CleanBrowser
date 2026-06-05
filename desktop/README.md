# CleanBrowser Desktop

Electron wrapper for the CleanBrowser web UI. Phase 6 phase 1 scaffold —
loads the hosted web app in a desktop window with a tray icon.

## Develop

```bash
cd desktop
npm install
CLEANBROWSER_URL=http://localhost:8080 npm start
```

## Build distributables

```bash
npm run build:win
npm run build:mac
npm run build:linux
```

Outputs land in `dist/`.
