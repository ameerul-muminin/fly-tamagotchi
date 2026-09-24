# Phase 3 Report: iPhone Controller Page

**Status: built and tested up to the browser boundary. NOT yet tested on a real iPhone.**

PLAN.md's done-criterion for Phase 3 is "all three inputs work on a real iPhone over HTTPS".
I have no iPhone, so that step is still open. Everything short of it passes:

- **Unit tests:** 16 Node tests of the phone logic with mock sensor data.
- **Mock-event end-to-end check:** the real phone logic runs in Node against the live
  reduced brain over a WebSocket. **10/10 checks pass**, including over HTTPS/WSS.
- **Browser smoke test:** the actual page runs in headless Edge at iPhone size.
  **11/11 checks pass.**
- **`pytest -q`:** 70 passed. That is the 63 Phase 2 tests plus 7 new ones.

The manual iPhone steps are at the end of this report.

## What was built

| File | Purpose |
|---|---|
| `web/phone/index.html`, `phone.css` | The phone page: fly status line with a small face, mood bars, a large sugar tap zone, shake and light cards, one "Enable shake + camera" button |
| `web/phone/controller.js` | All phone logic, with no browser APIs: shake detector, frame brightness, light send rule, status → display, eating-onset vibration, reconnect backoff. Node tests import this exact file |
| `web/phone/phone.js` | Browser glue: WebSocket with reconnect, pointer taps, iOS `DeviceMotionEvent.requestPermission`, camera sampling, vibration, screen wake lock, rendering |
| `web/dashboard/index.html` | Minimal Phase 3 dashboard: QR code, phone URL, a warning when the URL is not HTTPS, live sugar/bitter/MN9 rates, phone count. The full dashboard is Phase 4 |
| `server/web.py` | Serves the static pages and `/api/phone-url`, `/api/qr.svg`, `/api/phone-config`. Picks the phone URL |
| `server/config.py` | New `PhoneConfig` (every phone tunable), plus `certfile`/`keyfile`, `public_url` and the ngrok API address |
| `server/__main__.py` | `--certfile/--keyfile` for HTTPS, `--public-url`. Logs the phone URL at startup |
| `server/phone_page_check.py` | Phase 3 validation: `python -m server.phone_page_check --spawn` |
| `tests/js/controller.test.mjs` | 16 unit tests with mock motion samples and mock camera frames |
| `tests/js/mock_sensors.mjs` | Synthetic shake, walking, bright and covered-camera data |
| `tests/js/phone_e2e.mjs` | The mock-event scenario (used by pytest and by the check script) |
| `tests/js/browser_smoke.mjs` | The real page in headless Edge/Chrome over the DevTools protocol (manual; needs a browser) |
| `tests/test_phone_page.py` | 7 pytest tests: pages, QR, URL rules, config parity between Python and JS, Node unit tests, mock-event end-to-end on the toy brain |

The WebSocket protocol didn't change. The new HTTP endpoints and the messages the phone sends
are added at the end of `reports/MESSAGE_FORMAT.md`.

### How each PLAN.md item is covered

| PLAN.md Phase 3 item | Implementation |
|---|---|
| 1. Large tap zone = sugar | About 60% of the screen. Fires on `pointerdown`, not `click`, so there is no tap delay. Sends `{"type":"sugar"}` |
| 2. Shake with DeviceMotion + iOS permission button | The "Enable shake + camera" click handler calls `DeviceMotionEvent.requestPermission()` first, inside the user gesture. The shake detector sends `{"type":"bitter"}` |
| 3. Camera brightness a few times per second | Front camera, 4 samples/s. Mean Rec. 601 luma of a 32×24 downscaled frame. Sends `light` when the level changes by ≥ 0.05, or every 2 s |
| 4. Mood on the phone + vibrate when eating | Mood bars from `status.mood`, labelled as placeholders while `mood_rules_active` is false. Vibrates on each `eating: false → true` |
| 5. Dashboard QR code | `/dashboard/` shows `/api/qr.svg`, generated on the server with `segno` (pure Python, works offline) |

## Test results

Thresholds come from `reports/PHASE_3_PLAN.md` and were set before the first run:

- eating within 2 s of the tap
- a covered camera reports ≤ 0.05
- a bright frame reports ≥ 0.8
- one vibration per eating onset

### 1. Mock-event check on the reduced brain (`python -m server.phone_page_check --spawn`)

This runs `web/phone/controller.js`, the same module the phone page loads, in Node 24. It
connects to a spawned reduced-brain server (19,698 neurons) over a real WebSocket. Final run:

```
Pages and endpoints at http://127.0.0.1:8766:
  [OK] GET /phone/                200 text/html; charset=utf-8           2925 bytes
  [OK] GET /phone/phone.js        200 text/javascript; charset=utf-8     7764 bytes
  [OK] GET /phone/controller.js   200 text/javascript; charset=utf-8     7970 bytes
  [OK] GET /phone/phone.css       200 text/css; charset=utf-8            5541 bytes
  [OK] GET /dashboard/            200 text/html; charset=utf-8           5429 bytes
  [OK] GET /api/qr.svg            200 image/svg+xml                      1644 bytes
  [OK] GET /api/phone-config      200 application/json                    415 bytes
  phone URL for the QR code: http://192.168.0.176:8766/phone/ (source: lan, https: False)

Mock-event run (web/phone/controller.js in Node, real WebSocket):
  0.25 s  connected to ws://127.0.0.1:8766/ws/phone: brain 'reduced', 19698 neurons, light_is_brain_input=false
  0.25 s  [PASS] hello received, fly not eating at rest (eating=false)
  0.25 s  STEP 1: mock tap on the sugar zone
  0.25 s    phone -> {"type":"sugar"}
  0.26 s    phone <- {"type":"ack","event":"sugar","duration_ms":2000,"active_until_ms":4250,"t_ms":2250}
  0.26 s  [PASS] tap sent sugar and the server acked it (active_until_ms=4250)
  0.41 s    VIBRATE [80,60,80]
  0.41 s  [PASS] fly starts eating within 2000 ms of the tap (163 ms, MN9 28.0 Hz)
  0.41 s  [PASS] phone vibrated on the eating onset (1 vibration(s))
  2.80 s    sugar ran out, fly stopped eating
  2.80 s  STEP 2: mock DeviceMotion: 3 s of walking, then a hard shake
  2.80 s  [PASS] walking motion sends no bitter (0 shake(s) detected)
  2.80 s    phone -> {"type":"bitter"}
  2.80 s    phone <- {"type":"ack","event":"bitter","duration_ms":2000,"active_until_ms":6800,"t_ms":4800}
  2.80 s  [PASS] shake sent bitter once and the server acked it (1 shake(s), active_until_ms=6800)
  2.81 s    phone -> {"type":"sugar"}
  2.81 s    phone <- {"type":"ack","event":"sugar","duration_ms":2000,"active_until_ms":6800,"t_ms":4800}
  4.32 s    info: tap during bitter -> MN9 max 12.0 Hz over 7 status messages (eating in 0)
  4.32 s    phone -> {"type":"stop","stimulus":"all"}
  4.32 s    phone <- {"type":"ack","event":"stop","stimulus":"all","t_ms":6250}
  4.40 s  STEP 3: mock camera frames: bright room, then camera covered by a hand
  4.40 s    phone -> {"type":"light","level":0.882}
  4.41 s    phone <- {"type":"ack","event":"light","level":0.882,"t_ms":6400}
  4.41 s  [PASS] bright frame sends light >= 0.8 (measured 0.882, acked 0.882)
  4.41 s    phone -> {"type":"light","level":0.016}
  4.41 s    phone <- {"type":"ack","event":"light","level":0.016,"t_ms":6450}
  4.41 s  [PASS] covered camera sends light <= 0.05 (measured 0.016, acked 0.016)
  4.61 s  [PASS] status reports the dark level back; phone shows 'dark' (status.light=0.016)
  4.61 s    phone -> {"type":"light","level":0.882}
  4.61 s    phone <- {"type":"ack","event":"light","level":0.882,"t_ms":6600}
  4.61 s  STEP 4: second tap
  4.61 s    phone -> {"type":"sugar"}
  4.61 s    phone <- {"type":"ack","event":"sugar","duration_ms":2000,"active_until_ms":8650,"t_ms":6650}
  5.00 s    VIBRATE [80,60,80]
  5.60 s  [PASS] vibrations == eating onsets seen in the raw status stream (2 vibration(s), 2 onset(s))
  5.61 s  ping round trip 3.6 ms
10/10 checks passed

Phase 3 mock-event check: PASS
```

Across three runs on the reduced brain, the time from tap to `eating: true` on the phone was
251, 116 (HTTPS) and 163 ms. That includes up to one 50 ms chunk of waiting, the 500 ms
eating window crossing 20 Hz, and the 5 Hz status rate.

With bitter running, a tap never crossed the eating threshold. MN9 peaked at 12.0 Hz,
against 20 Hz needed. The phone has no bitter rule; this is the connectome's result.

### 2. The same check over HTTPS / WSS

I made a self-signed certificate with `openssl` and ran
`python -m server --certfile cert.pem --keyfile key.pem` (reduced brain). Then I ran
`node tests/js/phone_e2e.mjs https://127.0.0.1:8443` with certificate checks off for the
self-signed cert. Result: **10/10 checks passed** over `wss://`. `/api/phone-url` then
reported `https://192.168.0.176:8443/phone/` with `"https": true`.

### 3. The real page in a browser (`node tests/js/browser_smoke.mjs <url> <msedge.exe> <outdir>`)

The script runs headless Edge at 390×844 with a mobile viewport and drives it over the
DevTools protocol against the reduced brain:

```
[PASS] page connects to the server (connected · 1 ms)
[PASS] status shown (mood bars filled)
[PASS] mood marked as placeholder
[PASS] pointer tap -> fly eating on the phone (Eating!, MN9 80 Hz, sugar 1.4 s)
[PASS] vibrate called on the eating onset ([[80,60,80]])
[PASS] enable button: shake on (on)
[PASS] bright mock camera -> light level >= 0.8 (0.88)
[PASS] covered mock camera -> 'dark' level <= 0.05 (dark 0.01)
[PASS] server status reports the dark level (status.light=0.012; fly: Resting in the dark)
[PASS] shake -> bitter sent and shown on the phone (bitter 0.9 s, Yuck, bitter)
[PASS] no JS exceptions or console errors
11/11 browser checks passed
```

How each input was produced:

- **Tap:** a real pointer event.
- **Shake:** synthetic `DeviceMotionEvent`s, 25 m/s² at 5 Hz for 0.7 s.
- **Camera:** a canvas `captureStream` in place of `getUserMedia`, with a colour the test
  sets. The first try used Chromium's `--use-fake-device-for-media-stream`, but headless
  Edge ended that track at once. See the bug fix below.

I looked at the screenshots: the "Eating!" state after a tap and the dark state with the
camera covered both render correctly at phone size.

### 4. `pytest -q`

```
70 passed in 222.22s (0:03:42)
```

The 7 new tests in `tests/test_phone_page.py`:

1. pages served
2. the QR code is a valid SVG of the phone URL
3. phone URL priority (config → ngrok → LAN, `https` when a certificate is set, `/phone/` normalized)
4. a missing ngrok is handled
5. `/api/phone-config` == `PhoneConfig` == the `DEFAULTS` in `controller.js`
6. the 16 Node unit tests
7. the mock-event end-to-end run on the 10-neuron toy brain, with a real uvicorn and a
   real socket: 10/10

The 16 unit tests cover:

- a shake is detected once
- walking, rest and a single jolt are not shakes
- the cooldown (3.2 s of shaking gives exactly 2 events)
- gravity-only sensors
- bad samples are ignored
- frame brightness
- the light send rule
- the tap and shake messages
- a covered camera reads as dark
- one vibration per onset, and none for a fly already eating on connect or reconnect
- the status view
- ping RTT
- the backoff
- config merging

## Bug found and fixed during testing

The first browser run showed the camera stuck at "off", with no error. Two causes:

- `startCamera` awaited `video.play()` before it started the sampling loop.
- When the track ends, that promise can stay pending for good.

The fix:

- Sampling now starts without waiting for `play()`, and it reads frames only once
  `readyState ≥ 2`.
- A camera track that ends now shows "stopped" and turns the button into "Restart camera".
  iOS stops the camera when Safari goes to the background, so this matters there too.
- A guard stops "Try again" from adding a second motion listener, which would have
  doubled the shake events.

## Decisions made

1. **The phone logic is in its own module with injected `send`/`vibrate`/`now`.** Node
   tests and the check script run the exact code the phone runs, not a copy.
2. **Tap sends no duration.** The server default (2 s) applies, and a repeat tap extends
   the stimulus (server rule). `PhoneConfig.tap_duration_ms` can override it.
3. **Shake detector:** |linear acceleration| with ≥ 3 rising crossings of 15 m/s² within
   800 ms, then a 1.5 s cooldown. If `acceleration` is missing, it uses
   `accelerationIncludingGravity` minus a low-pass gravity estimate. The values are a
   first guess; Phase 6 tunes them on a device.
4. **Front camera, mean luma.** It is the camera the player covers while looking at the
   screen. `camera_facing` can switch to the back camera.
5. **Light stays game-only.** The page just reports brightness, and
   `light_is_brain_input` is still false. "Resting in the dark" on the phone is a display
   label from the light level, not fly behavior.
6. **Vibration:**
   - It uses `navigator.vibrate`.
   - iOS Safari has no Vibration API. There the page falls back to clicking a hidden
     `<input type="checkbox" switch>`, which gives a haptic tick on iOS 18+.
   - The screen always flashes as well.
7. **The QR code is made on the server with `segno`.** It needs no internet or CDN, and it
   is the one new Python dependency (added to `requirements.txt`).
8. **Phone URL priority:** `--public-url`/`FLY_PUBLIC_URL`, then a running ngrok tunnel
   (from its local API on port 4040), then the LAN IP. The ngrok probe runs in a thread so
   it can't stall the brain loop.
9. **HTTPS options:** `--certfile/--keyfile` (mkcert) or ngrok. I didn't add a self-signed
   certificate generator: iOS makes self-signed WSS painful, and mkcert or ngrok are the
   routes that work on a phone.
10. **The dashboard page is a minimal placeholder.** It shows only the QR code and a live
    table of input rates, to check that phone events arrive. The full dashboard is Phase 4.
11. **The Node tests run inside `pytest -q`**, and missing Node is a test **failure**, not
    a skip. The project needs Node 22+ from now on.

## Findings

**MN9 rebound after stopping sugar+bitter together.** In the HTTPS run, the phone sent
`stop` for both stimuli while sugar+bitter was running. For a moment afterwards,
`mn9_rate_hz` crossed 20 Hz, so the phone buzzed one extra time. This isn't a phone bug:
the vibration count still matched the onsets seen in the raw status stream (3 = 3).

My guess at the cause is that the bitter inhibition dies away while sugar-driven
excitation is still passing through the circuit. The other two runs didn't show it, so it
depends on timing.

In play, the fly may take a brief "bite" right after a bitter period ends. This comes from
the brain, and no rule was added. Phase 5 should know about it before it attaches hunger
to MN9.

## Open problems

1. **No real-iPhone test yet (the PLAN.md done-criterion).** Manual steps:
   1. On the laptop, run `python -m server`, then `ngrok http 8000` in a second terminal,
      then open `http://localhost:8000/`. The QR code should show the `https://…ngrok…`
      URL.
   2. Scan the QR code with the iPhone camera. If ngrok's free-tier warning page appears,
      tap "Visit Site".
   3. Tap the sugar zone. The phone should show "Eating!" and the dashboard's MN9 should
      rise.
   4. Tap "Enable shake + camera" and allow Motion and Camera.
   5. Shake the phone. The phone should show "Yuck, bitter" and the dashboard's bitter
      input should read 150.
   6. Cover the front camera. The light card should show "dark 0.0x" and the dashboard's
      light value should drop.
   7. Check whether the phone buzzes on an eating onset (iOS 18+ switch haptic; see 2).
2. **Vibration on iPhone is unverified.** Nobody documents whether the switch-haptic
   workaround fires outside a user gesture. The eating onset arrives from the network,
   not from a tap, so iOS may block it and leave only the screen flash.
3. **Camera auto-exposure.** Phones adjust exposure to the room, so a dim room may still
   read as mid-brightness. Covering the lens reads near 0, as the mock shows. Phase 6
   should measure real rooms and may need to tune `dark_below` (0.15).
4. **Shake thresholds are untested on hardware.** 15 m/s² and 3 peaks are guesses. They
   live in `PhoneConfig` and the page picks them up on reload, with no code change.
5. **Headless Edge's fake camera device** ended its track immediately. The mock camera in
   the smoke test replaces `getUserMedia`, so the real camera call is covered only by the
   iPhone test.
6. **`browser_smoke.mjs` isn't in `pytest -q`.** It needs Edge or Chrome and a free
   port 9333.
