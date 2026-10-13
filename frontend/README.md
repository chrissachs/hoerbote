# Frontend

The web app: a start page with every issue (and, logged in, a form to
import another one) and a page view. The page
view shows the page image with the narrated article highlighted and
plays the narration across the whole issue. Clicking an article jumps to
it. Built with React, Vite and TypeScript. The [backend](../backend/)
serves the build and all data.

## Run it

For development, against a backend on port 8001:

    npm --prefix frontend ci
    npm --prefix frontend run dev

Then open http://localhost:5173. To see every issue, log in with the
backend's password ("Anmelden" at the foot of the start page).

For the backend to serve it:

    npm --prefix frontend run build

## Where to start reading

| File | |
|---|---|
| `App.tsx` | state, the audio player, asking for an issue's audio |
| `playback.ts` | play order across pages, what a click hits |
| `PageView.tsx` | the zoomable page with the highlight |
| `IssueList.tsx`, `PageList.tsx` | start page, page sidebar |
| `ImportForm.tsx` | asking for an issue, and how far its import is |
| `api.ts` | backend calls |

## Good to know

- An issue without audio shows a "Jetzt vertonen" button instead (logged
  in only; anonymous visitors just see that there's no audio yet). The
  audio job then takes about 3 minutes, and the app checks every 10
  seconds.
- While a segment plays, the next one loads into the browser cache, so
  there's no gap between them.
- There's no login screen: "Anmelden" at the foot of the start page
  unlocks the issues that can't be shown publicly.
- Article boxes can overlap. A click picks the smallest box under it.
