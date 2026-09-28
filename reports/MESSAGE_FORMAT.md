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
| `GET /api/positions` | dashboard | | neuron positions for the 3D view (Phase 4, see below) |
| `GET /api/atlas`, `/api/atlas.bin` | dashboard | | every annotated neuron's position, the brain backdrop (see below) |
| `GET /api/atlas/neuron/{index}` | dashboard | | FlyWire annotation of one atlas entry (tooltip) |
| `GET /api/fly_model.glb`, `/api/fly_model_low.glb` | dashboard | | the 3D fly, built by `python -m server.fly_model` (404 until built) |
| `GET /dashboard/` | browser | | the dashboard page (`web/dashboard/`); `/` redirects here |

## Conventions

- **Neuron IDs are strings.** FlyWire root IDs exceed 2^53, the largest integer JavaScript
  can hold exactly.
- **`t_ms` is simulated time** in ms since the brain started or was last reset. The loop
  keeps it close to wall-clock time. `server_time_ms` is Unix wall-clock time in ms.
- **Events take effect at the next 50 ms chunk boundary.** An `ack`'s `t_ms` is the
  simulated time the event takes effect.
- **Per-client queues.** Each client has its own queue of 8 messages. If a client reads too
  slowly, its oldest messages are dropped; the brain never waits for a client.
- **Brain vs game.** `eating` is a pure readout of MN9 spikes. `game.mood`, `dark` and
  `fainted` come from the Phase 5 game rules (`server/game.py`, values in
  `server/config.py` `GameRules`), which react to brain readouts but never decide eating.
  Before Phase 5, `mood` was a placeholder (`mood_rules_active: false`).

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
| `{"type": "reset_brain"}` | Between chunks, every neuron returns to rest, stimuli stop, `t_ms` restarts at 0 and the fly starts fresh (Phase 5 start mood) |
| `{"type": "revive"}` | Phase 5, game only: mood back to the start values and not fainted; the brain keeps running |

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
  "light_is_brain_input": false,
  "eating": {"group": "mn9_primary", "threshold_hz": 20.0, "window_ms": 500.0},
  "game_rules": {"start_hunger": 0.5, "hunger_rise_per_s": 0.004167, "dark_below": 0.15, "...": "every GameRules field"}
 },
 "game": { "...": "same object as in tick.game" }
}
```

`brain.eating` says how `game.eating` is read out: the mean rate of `group` over the last
`window_ms` must reach `threshold_hz`. The dashboard draws this threshold on its MN9 meter.

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
{"type": "ack", "event": "revive"}
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
 "inputs_hz": {"sugar": 90.0, "bitter": 0.0},
 "game": {
  "stimuli_remaining_ms": {"sugar": 1900.0, "bitter": 0.0},
  "light": 1.0,
  "dark": false,
  "mn9_rate_hz": 50.0,
  "eating": true,
  "mood": {"hunger": 0.5, "happiness": 0.7, "energy": 1.0},
  "mood_rules_active": true,
  "fainted": false,
  "starving_s": 0.0
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
| `inputs_hz` | Poisson input rate per stimulus during the window. Phase 5: sugar = 150 Hz × (0.2 + 0.8 × hunger) when `hunger_scales_sugar` is on |
| `game.stimuli_remaining_ms` | Simulated ms left for each stimulus |
| `game.light` | Last light level from the phone (game-only) |
| `game.mn9_rate_hz` | Rate of `mn9_primary` averaged over the last 500 ms (`eating_window_ms`) |
| `game.eating` | `mn9_rate_hz >= 20` (`eating_threshold_hz`, the same threshold as the Phase 1 sugar test); a readout only |
| `game.dark` | `light < game_rules.dark_below` (0.15); the one dark threshold for server, phone and dashboard |
| `game.mood` | `hunger`, `happiness`, `energy` in [0, 1] from the Phase 5 rules |
| `game.mood_rules_active` | `true` since Phase 5 |
| `game.fainted` | Starved (hunger 1.0) for `faint_after_s`; mood frozen until `revive` or `reset_brain` |
| `game.starving_s` | Seconds at hunger 1.0 so far (0 below it) |
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
 "dark": false,
 "mood": {"hunger": 0.5, "happiness": 0.7, "energy": 1.0},
 "mood_rules_active": true,
 "fainted": false,
 "starving_s": 0.0
}
```

The same fields as `tick.game`, plus `t_ms`.

---

## `GET /health`

```json
{"ok": true, "mode": "reduced", "backend": "numba", "n_neurons": 19698, "t_ms": 200.0,
 "chunks": 4, "last_compute_ms": 13.7, "lag_ms": 0.0, "clients": {"phone": 1, "dashboard": 1}}
```

## `GET /api/positions` (Phase 4)

```json
{"units": "um", "axes": "FlyWire voxel axes scaled to um (x, y = EM image plane, y grows down; z = section axis)",
 "source": "flyconnectome/flywire_annotations@8587524:supplemental_files/Supplemental_file1_neuron_annotations.tsv columns pos_x, pos_y, pos_z (4x4x40 nm voxels); v630 IDs unchanged in v783 only",
 "n_neurons": 19698, "n_placed": 17101,
 "ids": ["720575940602313952", "..."],
 "xyz": [558.3, 333.9, 193.8, "..."],
 "groups_unplaced": {"sugar_grn": ["..."], "bitter_grn": ["..."], "mn9": ["..."], "mn9_primary": []}}
```

`xyz` is flat: neuron `ids[i]` is at `xyz[3i : 3i+3]`. Neurons missing from `ids` have no
position (their root ID changed between v630 and v783) and are not drawn. The WebSocket
messages did not change in Phase 4.

All values in this file come from `server/config.py`.

---

## Phase 3 additions (HTTP only; the WebSocket messages above are unchanged)

| Path | Returns |
|---|---|
| `GET /` | Redirect to `/dashboard/` (served by `server/dashboard.py`) |
| `GET /phone/` | The phone controller page (`web/phone/`) |
| `GET /dashboard/` | The Phase 4 dashboard (`web/dashboard/`); its "Connect a phone" panel shows the QR code below |
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

## `GET /api/atlas`, `/api/atlas.bin`, `/api/atlas/neuron/{index}` (dashboard redesign)

The brain view's backdrop: every neuron with a position in the FlyWire annotation table.

`/api/atlas` (JSON header):

```json
{"units": "um", "scale_um": 0.1, "n": 139248, "n_sim": 17101,
 "left_x_um": 323.3, "right_x_um": 721.8, "source": "flyconnectome/flywire_annotations@8587524:..."}
```

- `/api/atlas.bin` is `n` × (x, y, z) little-endian int16, in steps of `scale_um` µm.
- The first `n_sim` entries are the running brain's placed neurons, in the same order as
  `/api/positions` `ids`. The rest are not simulated and never spike.
- `left_x_um` / `right_x_um` are the mean x of neurons whose `side` is left / right; the
  page places its L / R labels from them.

`/api/atlas/neuron/{index}` returns the annotation row of one entry (404 outside `0..n-1`):

```json
{"index": 0, "root_id": "720575940602313952", "simulated": true, "cell_type": "CB1937",
 "side": "right", "top_nt": "glutamate", "super_class": "central", "cell_class": null}
```
