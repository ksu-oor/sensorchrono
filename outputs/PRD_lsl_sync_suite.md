# PRD: LSL Sync Suite

**Working title:** Sync Suite (alternatives to consider: *ChronoLink*, *LSLSync*, *AlignLab*, *SyncBench*)
**Author:** Feynman (collaboratively with project owner)
**Status:** Draft v0.1 — 2026-06-02
**Related artifacts:** `outputs/lsl_sync_experiment_plan.md`, `outputs/post_processing_design.md`

---

## 1. Vision

A deployable software suite that lets any LSL-equipped research lab achieve **sample-level synchronization** between physiological sensors (EEG/ECG/EMG/IMU/etc.) and multimedia capture (video, audio) — at recording time *and* in post-processing — with quantitative, auditable evidence of the sync quality achieved.

The lab should be able to plug in *any* combination of LSL-compatible sensors and a UVC camera, run a one-time calibration session, and from then on get analysis-ready, time-aligned datasets from every recording with a single command.

## 2. Target users

| Role | Need |
|---|---|
| **Recording technician** | Run sessions confidently; know in real time if sync is degrading; recover from problems without restarting |
| **Lab PI / sponsor** | Trust that the data delivered to analysts is sync-certified; have audit trail for grant reporting and replication |
| **Data analyst** | Receive a single, time-indexed dataset (e.g. unified Parquet + frame-aligned video) without doing alignment work themselves |
| **Equipment owner** | Add new sensors/cameras by writing a small device profile, not by patching core code |

## 3. Problem statement

LabRecorder solves the "record many LSL streams to one file" problem. It does **not** solve:

1. **Sync quality visibility.** Did this 3-hour recording stay aligned, or did the BT puck drop out at minute 47? Today: no way to know without manual post-hoc inspection.
2. **Device-specific timing lag.** Every sensor has a fixed lag from "physical event happens" to "byte arrives at LSL." LabRecorder records the byte-arrival time. It has no concept of the underlying physical-event time.
3. **Cross-modal mating.** Video files and LSL streams live in different time systems. The MP4 player and the EEG viewer are not the same tool. Mating them is the analyst's manual problem.
4. **Reproducible certification.** "Is the sync good enough for my analysis?" is asked per-paper, manually, in MATLAB scripts that nobody publishes.

Sync Suite solves all four. It does not replace LabRecorder; it *wraps* it (or replaces only the recording-and-monitoring shell while delegating the XDF-writing internals to a known-good library).

## 4. Goals and non-goals

### Goals

- G1. Capture **any** LSL stream + paired video/audio with one command.
- G2. Emit a live `SyncQuality` LSL stream that other tools (or the suite's own monitor) can consume to flag problems within seconds.
- G3. Provide a one-time per-device calibration routine that measures fixed lag and clock-drift characteristics.
- G4. Post-process recordings into analysis-ready, time-aligned datasets in one command.
- G5. Produce a machine-readable **sync certificate** with every processed dataset (pass/fail per criterion, numerical evidence).
- G6. Never silently lose, modify, or fabricate data — only emit derived artifacts beside originals.
- G7. Extensible by config: new sensors via YAML device profiles; new fiducial sources via plugin functions.
- G8. Cross-platform: Windows + Linux (macOS best-effort).

### Non-goals (explicitly)

- N1. **Replacing the LSL protocol or pylsl library.** We build on them.
- N2. **Replacing LabRecorder's XDF format.** XDF stays the on-disk format; we add metadata channels but don't break compatibility.
- N3. **Hard-real-time sync.** Sync Suite assumes software clocks and best-effort transport. Hardware sync (TTL/photodiode/parallel port) is out of scope but we leave hooks for it.
- N4. **Subject safety analysis.** This is a data tool. Medical device certification, electrical isolation, etc. remain the user's responsibility.
- N5. **Annotation / labeling UI.** Use existing tools (EEGLAB, MNE, ELAN). We just provide them with synced data.

## 5. Components

```
┌──────────────────────────────────────────────────────────┐
│                   SYNC SUITE                             │
│                                                          │
│   ┌──────────────┐    ┌────────────────┐                 │
│   │  Recorder    │    │   Monitor      │                 │
│   │              │    │   (live UI)    │                 │
│   │  - XDF write │◄───┤                │                 │
│   │  - SyncQual  │    │  - dashboards  │                 │
│   │    stream    │    │  - alarms      │                 │
│   └──────┬───────┘    └────────────────┘                 │
│          │                                               │
│          ▼                                               │
│   ┌──────────────┐    ┌────────────────┐                 │
│   │ Calibrator   │    │ Device profiles│                 │
│   │  - fiducial  │◄──►│   *.yaml       │                 │
│   │    detection │    │                │                 │
│   │  - fit lags  │    │  shimmer3.yaml │                 │
│   │  - emit cal  │    │  brio.yaml     │                 │
│   │    profile   │    │  emotiv.yaml   │                 │
│   └──────┬───────┘    └────────────────┘                 │
│          │                                               │
│          ▼                                               │
│   ┌──────────────┐    ┌────────────────┐                 │
│   │ Postprocessor│    │   Validator    │                 │
│   │  - dejitter  │───►│  - re-detect   │                 │
│   │  - drift fix │    │    fiducials   │                 │
│   │  - lag sub   │    │  - cert pass/  │                 │
│   │  - MP4 remux │    │    fail        │                 │
│   │  - unify     │    │  - sign report │                 │
│   └──────┬───────┘    └────────────────┘                 │
│          │                                               │
│          ▼                                               │
│      Analysis-ready dataset + sync certificate           │
└──────────────────────────────────────────────────────────┘
```

### 5.1 Recorder

Wraps LabRecorder (or a thin equivalent) to:
- Subscribe to user-selected LSL streams and write a standard XDF.
- Discover and spawn bridge processes for any device whose profile says it has one (Shimmer, Emotiv, video, audio, keyboard).
- Compute and **publish its own LSL stream** named `SyncQuality_<stream>` (1 Hz, float32) per recorded stream, with channels: `effective_rate`, `mapper_offset_s`, `observed_min_latency_s`, `residual_ms`, `samples_dropped_cum`.
- Honor per-device "safety" hooks from the profile (max sample rate, required pre-flight checks).

### 5.2 Monitor

Standalone desktop UI (web-based or Qt) that:
- Lists every LSL stream visible on the network with its current health (green/yellow/red).
- Plots `SyncQuality` channels live for selected streams.
- Triggers alarms on configurable thresholds (e.g. `effective_rate deviates >0.5% for >30 s`).
- Shows the calibration status (last calibration timestamp, age, whether validity-window has expired).
- Can be left running unattended during long recordings.

### 5.3 Calibrator

Standalone tool that runs a **calibration session** (typically 5–10 min) and produces a `calibration.yaml`.

For each device-under-calibration:
1. Records a session with a known fiducial source (operator-selected: keystroke / earbud-click / LED flash / TTL).
2. Detects the fiducial in each stream using the device profile's detector function.
3. Fits the fixed lag and its uncertainty.
4. Writes calibration data to a YAML that lives alongside the device profile, with metadata: date, operator, fiducial source, sample count, residual stddev.

A calibration is *valid* for a configurable window (default 30 days, or until any hardware change is logged). The suite refuses to post-process without a valid calibration *unless* the user passes `--no-calibration` (explicit override, logged in the certificate).

### 5.4 Postprocessor

Takes a raw recording directory and a calibration profile. Produces:
- `unified.parquet` — single time-indexed table, all modalities aligned, drift-corrected, lag-calibrated.
- `synced.mp4` (optional, with `--remux`) — video file with PTS rewritten so playback timeline matches the unified time axis.
- `synced_audio.wav` (optional) — audio resampled to the unified time axis.
- `processing.log` — full log of operations performed.
- `processing_metadata.json` — git SHA of suite, calibration file used, dejitter parameters, etc.

**Pipeline stages** (see `post_processing_design.md` for detail):
1. pyxdf dejitter per stream
2. Clock-offset (drift) correction from XDF clock_offsets records
3. Per-modality fixed-lag subtraction (from calibration)
4. Video remux / audio resample to unified time axis
5. Validator handoff (see below)

### 5.5 Validator

Runs **after** the postprocessor. Re-detects fiducials on the *processed* output and emits a `sync_certificate.json`:

```json
{
  "suite_version": "0.4.2",
  "input_recording_sha256": "...",
  "calibration_profile": "rig_ngoldbla_2026-06-02.yaml",
  "fiducial_source": "keyboard_keystroke",
  "n_fiducials_used": 358,
  "per_pair_residuals_ms": {
    "ecg__keystroke":   {"median": 0.4, "p95": 1.8, "max": 2.3},
    "accel__keystroke": {"median": 0.5, "p95": 1.9, "max": 2.4},
    "audio__keystroke": {"median": 1.1, "p95": 4.2, "max": 6.8},
    "video__keystroke": {"median": 14.6, "p95": 31.2, "max": 33.0},
    "emotiv_eeg__keystroke": {"median": 1.9, "p95": 4.6, "max": 8.1}
  },
  "drift_slopes_ppm": {
    "ecg": 36.5, "accel": 36.5, "video": -0.1, "emotiv_eeg": 22.4
  },
  "passes": ["ecg", "accel", "audio", "video", "emotiv_eeg"],
  "fails": [],
  "verdict": "PASS",
  "signed_at": "2026-06-02T17:42:10Z"
}
```

The certificate is the contractual deliverable to analysts. If `verdict: FAIL`, the suite *still emits* the processed dataset (it doesn't withhold data) but the certificate explicitly says which pair failed.

## 6. Device profile schema

Adding support for a new sensor/camera = writing one YAML and (if needed) one fiducial-detector function.

```yaml
# profiles/shimmer3_exg_sr47-5-1.yaml
profile_id: shimmer3_exg_sr47-5-1
device_type: biosignal
bridge:
  module: lslsync.bridges.shimmer_exg
  defaults:
    sampling_rate_hz: 256
    mode: ecg
    com_port: auto    # autoresolve via BT MAC
streams_emitted:
  - name: ShimmerECG
    type: ECG
    channels: 4
    rate_hz: 256
    timestamping: lsl_mapper_cristian
  - name: ShimmerDiagnostics
    type: Diagnostics
    channels: 5
    rate_hz: 1
fiducial_detectors:
  - source: keystroke      # detect: desk-vibration in accel z-axis
    detector: lslsync.detectors.accel_onset
    detector_args: {axis: 2, threshold_sd: 5.0, refractory_ms: 200}
  - source: audio_pulse
    detector: lslsync.detectors.accel_onset
    detector_args: {axis: 2, threshold_sd: 5.0, refractory_ms: 200}
safety:
  preflight_checks:
    - check: battery_voltage_min
      threshold_v: 3.4
    - check: bt_link_quality_min
      threshold_db: -75
  max_continuous_minutes: 240   # battery limit
```

A camera profile is similar but with different detectors (`led_brightness_onset`, `frame_region_motion`) and bridge module.

**Hot-add path:** dropping a new YAML into `profiles/` causes the suite to discover it next time the recorder is launched. No code changes needed unless the device requires a new bridge.

## 7. Safety: "don't damage anything"

I'm interpreting this as four things:

### 7.1 Don't damage the data

- Recorder only writes new files; never modifies the XDF after closure.
- Postprocessor always writes to a separate output directory; input is read-only.
- Every output is hash-tagged with the input it was derived from.
- A `--dry-run` mode exists for the postprocessor that emits the certificate without writing the dataset.

### 7.2 Don't damage the analysis

- Validator certificate is the trust contract. Analysis tools should refuse to consume a dataset whose certificate says `verdict: FAIL` (or at least surface a warning).
- No silent "best-effort" alignment. If calibration is stale or absent, the suite either refuses or requires `--accept-unverified` (logged).
- Certificate is digitally signed (HMAC with a per-rig key) so analysts can detect tampering.

### 7.3 Don't damage the device

- Profile-declared `preflight_checks` run before recording (battery, link quality, max session length).
- Recorder refuses to start a session that would exceed declared device limits unless explicitly overridden.
- For devices where a calibration would require electrical injection (Shimmer EXG inputs), the calibrator refuses unless `--electrical-injection-allowed` is set *and* a separate signed waiver is present. Default fiducials are mechanical/acoustic.

### 7.4 Don't damage the subject

- Out of scope as a feature — but the suite must not actively introduce risk. No commands that override device safety firmware (e.g. disabling Shimmer current limiting).
- A `subject_present: true` flag in the recording session config triggers stricter defaults (no electrical injection, conservative `max_continuous_minutes`).

## 8. Key workflows

### 8.1 First-time setup (per lab, per rig)

```bash
syncsuite setup --rig-id mylab_room201
# Detects connected LSL-capable devices + UVC cameras
# Generates draft profiles in profiles/
# Operator reviews and edits
syncsuite calibrate --duration 600 --fiducial keystroke --rig mylab_room201
# Writes calibration.yaml for mylab_room201
syncsuite calibrate --verify
# Re-runs a short session, confirms calibration produces in-spec residuals
```

### 8.2 Per-recording (the routine case)

```bash
syncsuite record --rig mylab_room201 --session demo_subj01 \
                 --duration 1800 --output recordings/2026-06-15_subj01/
# Monitor window opens automatically
# Recording stops at duration or Ctrl+C
syncsuite process recordings/2026-06-15_subj01/ \
                  --output processed/2026-06-15_subj01/
# Validator emits sync_certificate.json; verdict shown in terminal
```

### 8.3 Resync after analyst-side change

```bash
syncsuite process recordings/2026-06-15_subj01/ \
                  --calibration calibration_v2.yaml \
                  --output processed_v2/2026-06-15_subj01/ \
                  --remux  # this time also produce synced.mp4
```

## 9. Non-functional requirements

| # | Requirement |
|---|---|
| NF1 | Recorder must never drop samples it has acknowledged. If transport fails, the session aborts with a clear error rather than silently losing data. |
| NF2 | Postprocessor is deterministic: same input + calibration + suite version → bit-identical output (modulo timestamps in metadata). |
| NF3 | All operations are journaled: every write logs source files, parameters, and output paths. |
| NF4 | Suite has zero network egress unless explicitly enabled (some sites are air-gapped). |
| NF5 | Memory footprint: postprocess a 3-hour, 6-modality recording on 16 GB RAM. |
| NF6 | Throughput: postprocess at >= 10x real-time on a modern desktop (1 hour of data in <6 min). |
| NF7 | Localization: all user-visible strings via `gettext` or equivalent. |
| NF8 | Licensing: BSD or MIT, with all dependencies compatible. |

## 10. Open questions

1. **Does Sync Suite replace LabRecorder's GUI or just wrap it?** Replacing requires building a recorder UI; wrapping means we run LabRecorder as a child process and add our streams. *Recommendation:* wrap initially, replace incrementally if needed.
2. **How are calibration profiles versioned and shared?** Per-rig, per-lab, or per-installation? If a lab has 5 identical rigs, do they share one calibration? *Recommendation:* per-rig calibration, with an explicit `inherits_from:` field for shared baselines.
3. **What's the fiducial canon?** For a sensor with no obvious fiducial path (e.g. a non-acoustic, non-vibrating sensor), what do we fall back to? *Recommendation:* require at least one detectable path per modality; reject device profiles that don't declare one.
4. **Does the certificate need cryptographic signing for the v1 release?** For research deployment, HMAC is enough. For regulated environments, X.509 + timestamp authority. *Recommendation:* HMAC v1, document path to X.509 v2.
5. **What is the validator's authority over the recorder?** Can the recorder refuse to start a session if the calibration is expired? *Recommendation:* yes, with `--allow-stale-calibration` override that's logged in the certificate.

## 11. Phasing / roadmap

| Phase | Scope | Deliverable |
|---|---|---|
| **0 — Prototype (current)** | Single rig, hand-coded bridges, manual launchers | Working sync demonstrated end-to-end. We are here. |
| **1 — MVP** | One executable that takes a profile + runs the calibration + records + post-processes | Single rig, two devices. Ship as `syncsuite` CLI. |
| **2 — Multi-device** | Profile system, plugin detectors, 3+ device types supported | Add Emotiv, add a second camera profile, test on a second rig |
| **3 — Monitor UI** | Live dashboard, alarms, multi-stream view | Replaces watching cmd-line output for long recordings |
| **4 — Validator hardening** | Cryptographic certificates, formal pass/fail spec | Trust contract for analysts |
| **5 — Open release** | Documentation, examples, profile contributions process | Other labs can adopt |

## 12. Success criteria for v1 (MVP)

The MVP is considered shipped when **a researcher unfamiliar with the suite can**, given a lab with a Shimmer and a webcam:

1. Install in <10 min via `pip install syncsuite`.
2. Run `syncsuite calibrate` and produce a calibration profile in <30 min.
3. Run `syncsuite record --duration 30m` and get a clean XDF + MP4 + WAV.
4. Run `syncsuite process` and get a unified Parquet + sync certificate.
5. Open the Parquet in pandas/MNE and have all modalities visibly aligned (eyeball test passes).

…all without writing custom code or consulting the source.

## 13. What we are doing right now to get there

The current `LSL_synchronization_multi` repo is the **phase 0 prototype**. Every experiment we've run is generating two things:

1. **Calibration constants** that will live in the first device profiles (`shimmer3_exg_sr47-5-1.yaml`, `logitech_brio.yaml`, etc.).
2. **Algorithmic recipes** that become the bridge / detector / postprocessor modules in the future package.

The 3-hour validation is the **acceptance test** that proves the prototype's calibration is stable enough to extract into a reusable system. If the 3-hour test passes, we have evidence that the v1 MVP design will work; if it fails, we learn what to fix before productizing.
