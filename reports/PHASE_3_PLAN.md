# Phase 3 Plan: iPhone Controller Page

Goal (PLAN.md, Phase 3): a phone page that sends sugar (tap), bitter (shake) and light
(camera brightness) to the Phase 2 server, shows the fly's mood, vibrates when the fly
eats, and a dashboard QR code so the phone can connect quickly.

The protocol is fixed by `reports/MESSAGE_FORMAT.md`. The server protocol does not change;
Phase 3 only adds static pages and three small HTTP endpoints.

## What gets built

| Piece | File(s) |
|---|---|
| Phone page (HTML/CSS + browser glue) | `web/phone/index.html`, `web/phone/phone.css`, `web/phone/phone.js` |
| Phone logic with no browser dependencies (shake detector, brightness, light throttling, status → view, eat-start detection, reconnect backoff) | `web/phone/controller.js` (ES module) |
| Minimal dashboard: QR code + phone URL + connection status. **Not** the Phase 4 dashboard | `web/dashboard/index.html` |
| Static file serving, `/` → dashboard, `GET /api/phone-url`, `GET /api/qr.svg`, `GET /api/phone-config` | `server/app.py`, `server/web.py` |
| HTTPS: `--certfile/--keyfile` (mkcert output) and ngrok auto-detection for the QR URL | `server/__main__.py`, `server/web.py` |
| Every phone tunable (shake threshold, camera rate, light send rule, vibration pattern…) | `PhoneConfig` in `server/config.py`, served by `/api/phone-config` |
| Mock-event check against the real reduced brain | `python -m server.phone_page_check --spawn` |

## Design choices (made up front)

1. **Pure logic separate from browser glue.** `controller.js` takes `send`, `vibrate`
   and `now` as injected functions, so Node can drive it with mock events and a real
   WebSocket. `phone.js` only wires DOM, sensors and the socket to it.
2. **Tap = `{"type":"sugar"}`** with the server's default duration (2 s). A tap during a
   running stimulus extends it (server rule).
3. **Shake = `{"type":"bitter"}`.** Detector: magnitude of `acceleration` (gravity
   removed; if the browser only gives `accelerationIncludingGravity`, subtract a running
   low-pass estimate of gravity). A shake is ≥ 3 peaks above 15 m/s² within 800 ms,
   followed by a 1.5 s cooldown. Values are in `PhoneConfig`, chosen before testing on
   a device; they will need tuning on a real iPhone (Phase 6 item 4).
4. **Light = mean luma of a 32×24 downscaled camera frame** (Rec. 601 weights), 4 times
   per second. Sent when it changes by ≥ 0.05 or at least once every 2 s.
   Front camera by default (the one the player covers while looking at the screen).
   Light stays game-only on the server (`light_is_brain_input: false`).
5. **iOS permissions:** one "Enable shake + camera" button. Its click handler calls
   `DeviceMotionEvent.requestPermission()` first (it must run inside the user gesture),
   then `getUserMedia`. On non-HTTPS pages the button explains that iOS needs HTTPS.
6. **Vibration:** on the transition `eating: false → true` in `status`. Uses
   `navigator.vibrate` where it exists. iOS Safari has no Vibration API; as a fallback
   the page toggles a hidden `<input type="checkbox" switch>` (iOS 18+ plays a haptic
   tick for it). Whether that fires outside a user gesture is unverified; the page
   always flashes the screen too.
7. **Mood display** shows the `status.mood` values and labels them "placeholder until
   Phase 5" while `mood_rules_active` is false. No mood logic on the phone.
8. **QR code** generated on the server with `segno` (pure Python, no network).
   Phone URL priority: `FLY_PUBLIC_URL`/`--public-url` → a running ngrok tunnel
   (local API at `127.0.0.1:4040`) → `https://<LAN IP>:<port>/phone/` when the server has a
   certificate → `http://<LAN IP>:<port>/phone/` (tap only; the page warns).
9. **Reconnect** with exponential backoff (0.5 s → 8 s); the page shows the connection state.

## Tests

- `tests/js/controller.test.mjs` (`node --test`): shake detector (real shake fires once,
  walking/gentle motion does not, cooldown, gravity-only fallback), brightness of mock
  frames, light throttling, status view model, eat-start vibration, reconnect backoff.
- `tests/test_phone_page.py`:
  - static pages and endpoints are served (`/phone/`, `/dashboard/`, `/api/qr.svg` is a
    valid SVG, `/api/phone-url` rules, `/api/phone-config` matches `PhoneConfig`)
  - runs the Node unit tests
  - **mock-event end-to-end test**: a real uvicorn server (toy brain) + the real
    `controller.js` in Node over a real WebSocket. Mock tap → `ack sugar`, mock
    `devicemotion` shake → `ack bitter`, mock dark then bright camera frames → `ack light`
    with low then high level, `status` with `eating: true` → vibrate called once.
- `python -m server.phone_page_check --spawn`: the same scenario against the real
  reduced brain, printing each event, ack and status.

Pass thresholds (set now, before the first run): in the reduced-brain check, the fly must
reach `eating: true` within 2 s of the tap, `vibrate` must be called exactly once per
eating onset, a covered camera (all-black frames) must report `level ≤ 0.05`, and a
bright frame `level ≥ 0.8`.

## Not doable here

PLAN.md's done-criterion is "all three inputs work on a real iPhone over HTTPS". I have no
iPhone. I will test everything up to the browser boundary (mock events in Node, the pages
in a desktop browser, HTTPS with a local certificate) and list the manual iPhone steps in
the report.
