# WebSocket Message Format (Phase 2)

Server: `python -m server` (port 8000; `--brain full` for the full brain).
All messages are JSON text frames. The examples are real output from the reduced brain,
with long lists shortened to `"..."`.

| Endpoint | Who connects | Sends | Receives |
|---|---|---|---|
| `/ws/phone` | iPhone controller | `sugar`, `bitter`, `light`, `stop`, `ping` | `hello`, `ack`, `error`, `pong`, `status` (5 Hz) |
| `/ws/dashboard` | Laptop dashboard | `ping`, `reset_brain` | `hello`, `tick` (≤ 20 Hz), `ack`, `error`, `pong` |
| `GET /health` | anyone | | server status (JSON) |
| `GET /api/brain` | anyone | | the `brain` object from `hello` |

## Conventions

- **Neuron IDs are strings.** FlyWire root IDs exceed 2^53, the largest integer JavaScript
  can hold exactly.
- **`t_ms` is simulated time** in ms since the brain started or was last reset. The loop
  keeps it close to wall-clock time. `server_time_ms` is Unix wall-clock time in ms.
- **Events take effect at the next 50 ms chunk boundary.** An `ack`'s `t_ms` is the
  simulated time the event takes effect.
- **Per-client queues.** Each client has its own queue of 8 messages. If a client reads too
  slowly, its oldest messages are dropped; the brain never waits for a client.
- **Brain vs game.** Anything under `game.mood` is a placeholder until Phase 5
  (`mood_rules_active: false`). `eating` is a pure readout of MN9 spikes.

---

## Phone → server

### `sugar` / `bitter`: turn a taste input on

```json
{"type": "sugar", "duration_ms": 2000}
{"type": "bitter", "duration_ms": 2000}
```

- The event drives the group's GRNs with 150 Hz Poisson input for `duration_ms` of
  simulated time.
  - `sugar` drives `sugar_grn` (21 neurons).
  - `bitter` drives `bitter_grn` (21 neurons).
- `duration_ms` is optional:
  - The default is 2000.
  - It must be a number ≥ 0.
  - It is capped at 10000.
- A new event extends a running stimulus to `max(current end, now + duration_ms)`. It
  never shortens one.
- The server has no bitter rule. Bitter lowers MN9 only through the connectome.

### `light`: camera brightness (game-only)

```json
{"type": "light", "level": 0.2}
```

`level` is from 0 (dark) to 1 (bright). It is stored as game state only and does **not**
drive any neurons (`brain.light_is_brain_input: false`). The R7/R8 groups are saved for
later but marked partial.

### `stop`: end stimuli now

```json
{"type": "stop", "stimulus": "all"}
```

`stimulus` is `"sugar"`, `"bitter"` or `"all"` (the default).

### `ping`: latency check

```json
{"type": "ping", "t": 123}
```

`t` is any value; it is echoed back in the `pong`.

---

## Dashboard → server

| Message | Effect |
|---|---|
| `{"type": "ping", "t": ...}` | `pong` reply |
| `{"type": "reset_brain"}` | Between chunks, every neuron returns to rest, stimuli stop and `t_ms` restarts at 0 |

Any other type gets an `error`.

---

## Server → client

### `hello`: sent once on connect (both roles)

```json
{
 "type": "hello",
 "role": "dashboard",
 "brain": {
  "mode": "reduced",
  "backend": "numba",
  "n_neurons": 19698,
  "chunk_ms": 50.0,
  "groups": {
   "sugar_grn":   {"count": 21, "ids": ["720575940624963786", "720575940630233916", "..."]},
   "bitter_grn":  {"count": 21, "ids": ["720575940621778381", "720575940602353632", "..."]},
   "mn9":         {"count": 2,  "ids": ["720575940660219265", "720575940645521262"]},
   "mn9_primary": {"count": 1,  "ids": ["720575940660219265"]}
  },
  "stimuli": {
   "sugar":  {"group": "sugar_grn",  "rate_hz": 150.0},
   "bitter": {"group": "bitter_grn", "rate_hz": 150.0}
  },
  "light_is_brain_input": false
 },
 "game": { "...": "same object as in tick.game" }
}
```

`brain.groups` lists only the groups present in the running brain:

- **Reduced brain:** the four groups above.
- **Full brain:** also `photoreceptor_R7` and `photoreceptor_R8`, which are partial and not
  used as inputs.

`mn9_primary` is the MN9 used for every readout in the paper and in our validation.

### `ack`: an event was accepted

```json
{"type": "ack", "event": "sugar", "duration_ms": 2000.0, "active_until_ms": 2000.0, "t_ms": 0.0}
{"type": "ack", "event": "light", "level": 0.2, "t_ms": 1050.0}
{"type": "ack", "event": "stop", "stimulus": "all", "t_ms": 9050.0}
{"type": "ack", "event": "reset_brain"}
```

### `error`: an event was rejected (the connection stays open)

```json
{"type": "error", "error": "level must be a number from 0 to 1", "received": {"type": "light", "level": 1.5}}
```

### `pong`

```json
{"type": "pong", "t": 123, "server_time_ms": 1790234155315.57}
```

### `tick`: dashboard, at most `broadcast_hz` (20) per second

One tick covers one window of whole chunks: 50 ms at 20 Hz, or 100 ms if
`broadcast_hz = 10`.

```json
{
 "type": "tick",
 "seq": 2,
 "t_ms": 100.0,
 "window_ms": 50.0,
 "server_time_ms": 1790234155197.46,
 "group_counts":   {"sugar_grn": 149, "bitter_grn": 0, "mn9": 8, "mn9_primary": 5},
 "group_rates_hz": {"sugar_grn": 141.9, "bitter_grn": 0.0, "mn9": 80.0, "mn9_primary": 100.0},
 "total_spikes": 565,
 "n_spiking": 248,
 "spiking_ids": ["720575940605658033", "720575940606607234", "720575940606866377", "..."],
 "spiking_ids_truncated": false,
 "inputs_hz": {"sugar": 150.0, "bitter": 0.0},
 "game": {
  "stimuli_remaining_ms": {"sugar": 1900.0, "bitter": 0.0},
  "light": 1.0,
  "mn9_rate_hz": 50.0,
  "eating": true,
  "mood": {"hunger": 0.5, "happiness": 0.5, "energy": 1.0},
  "mood_rules_active": false
 },
 "perf": {"compute_ms": 15.5, "lag_ms": 0.0}
}
```

| Field | Meaning |
|---|---|
| `seq` | Tick number, 1, 2, …; gaps mean this client dropped messages |
| `t_ms` | Simulated time at the **end** of the window |
| `window_ms` | Simulated time covered by this tick |
| `group_counts` | Spikes per group in the window (sum over the group's neurons) |
| `group_rates_hz` | `group_counts / group size / window seconds` |
| `total_spikes` | All spikes in the brain in the window |
| `n_spiking` | Number of distinct neurons that spiked |
| `spiking_ids` | Those neurons, randomly sampled down to `max_spike_ids` (500) when there are more; for the 3D view |
| `spiking_ids_truncated` | `true` if the sample was cut |
| `inputs_hz` | Poisson input rate per stimulus during the window |
| `game.stimuli_remaining_ms` | Simulated ms left for each stimulus |
| `game.light` | Last light level from the phone (game-only) |
| `game.mn9_rate_hz` | Rate of `mn9_primary` averaged over the last 500 ms (`eating_window_ms`) |
| `game.eating` | `mn9_rate_hz >= 20` (`eating_threshold_hz`, the same threshold as the Phase 1 sugar test); a readout only |
| `game.mood` | Placeholder values; Phase 5 adds rules |
| `perf.compute_ms` | Mean wall time to simulate one 50 ms chunk in this window |
| `perf.lag_ms` | How far the loop is behind real time |

### `status`: phone, at most `phone_status_hz` (5) per second

```json
{
 "type": "status",
 "t_ms": 200.0,
 "stimuli_remaining_ms": {"sugar": 1800.0, "bitter": 0.0},
 "light": 1.0,
 "mn9_rate_hz": 70.0,
 "eating": true,
 "mood": {"hunger": 0.5, "happiness": 0.5, "energy": 1.0},
 "mood_rules_active": false
}
```

The same fields as `tick.game`, plus `t_ms`.

---

## `GET /health`

```json
{"ok": true, "mode": "reduced", "backend": "numba", "n_neurons": 19698, "t_ms": 200.0,
 "chunks": 4, "last_compute_ms": 13.7, "lag_ms": 0.0, "clients": {"phone": 1, "dashboard": 1}}
```

All values in this file come from `server/config.py`.

---

## Phase 3 additions (HTTP only; the WebSocket messages above are unchanged)

| Path | Returns |
|---|---|
| `GET /` | Redirect to `/dashboard/` |
| `GET /phone/` | The phone controller page (`web/phone/`) |
| `GET /dashboard/` | Phase 3 dashboard: QR code and a live input check (`web/dashboard/`) |
| `GET /api/phone-url` | `{"url": "https://…/phone/", "source": "config" \| "ngrok" \| "lan", "https": true, "note": null}` |
| `GET /api/qr.svg` | QR code (SVG) of that URL |
| `GET /api/phone-config` | `PhoneConfig` from `server/config.py` (shake, camera, light, vibration, reconnect values) |

What the phone page sends:

| Input | Message |
|---|---|
| Tap on the sugar zone (pointerdown) | `{"type": "sugar"}` (server default duration) |
| Shake (≥ 3 peaks of ≥ 15 m/s² within 800 ms, 1.5 s cooldown) | `{"type": "bitter"}` |
| Camera, 4 checks/s: mean brightness of a 32×24 frame | `{"type": "light", "level": 0.016}`, sent when the level changes by ≥ 0.05 or every 2 s |
| Every 3 s | `{"type": "ping", "t": <performance.now()>}` |

It vibrates when `status.eating` goes from `false` to `true`.
