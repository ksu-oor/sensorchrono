# Hardware reference

Wiring, pairing, and the Shimmer packet/timing reference for the devices
SensorChrono records. The app discovers and drives these for you — this document
is the underlying reference for setup and troubleshooting.

## Supported devices

| Modality | Device | Connection | LSL stream(s) |
|---|---|---|---|
| ECG / EMG | Shimmer3 EXG | Bluetooth (COM port) | `ShimmerECG` / `ShimmerEMG`, `ShimmerMarkers`, `ShimmerDiagnostics_ECG` |
| Video | Logitech BRIO | USB (UVC) | `VideoFrames` (+ `.mp4` + `frames.csv`) |
| Audio | BRIO microphone | USB | `Audio` (48 kHz) |
| Fiducial | USB HID keyboard | USB | `KeyboardFiducial` |

> Requirements: a Shimmer3 EXG unit with a Bluetooth adapter; a BRIO (or any UVC
> camera + audio input); a USB keyboard. SensorChrono's installer bundles
> LabRecorder, so no separate LSL recorder install is needed.

## Pair the Shimmer via Bluetooth

1. Power on the Shimmer device.
2. Open **Windows Settings → Bluetooth & devices → Add device**.
3. Select the Shimmer and pair it. Use PIN `1234` if prompted.
4. Windows assigns it a COM port. To find it:
   - Open **Device Manager → Ports (COM & LPT)**.
   - Look for an entry like `Standard Serial over Bluetooth link (COM6)`.
   - Note that port number — SensorChrono's setup page lets you pick it (or it
     auto-detects).

## ECG electrode placement

| Electrode | Color | Placement |
|---|---|---|
| RA | White | Right arm |
| LA | Black | Left arm |
| LL | Red | Left leg |

Lead derivations:

- Lead I = LA − RA
- Lead II = LL − RA
- Lead III = LL − LA = Lead II − Lead I

## The calibration block (required)

A valid calibrated recording must include a **30-second calibration block**:
**10–20 firm spacebar presses spaced ~2 s apart**, in a quiet moment. Each
keystroke is a free multi-modal fiducial — the HID timestamp is the system-clock
reference, the click is audible in the BRIO mic, and the nearest video frame
gives a video-clock measurement. This is what makes audio/video absolute lag
measurable *in-situ*, with no external hardware. **Skip it and lag values come
back null.**

## Shimmer marker events

The `ShimmerMarkers` stream carries JSON events logged through the session:

| Event | Meaning |
|---|---|
| `session_started` | Bridge launched |
| `stream_ready` | LSL outlet created, device configured |
| `recording_armed` | Recording countdown started |
| `recording_started` | Data capture began |
| `recording_stopped` | Data capture ended |
| `session_finished` | Bridge completed normally |

## Technical reference — Shimmer packet structure & timing

<details>
<summary>Packet structure, sampling rates, and packet alignment</summary>

### ECG packet structure

One sample packet is 14 bytes:

- 3 bytes timestamp
- 11 bytes payload (Lead II and Lead I each as a 24-bit signed integer)
- Lead III is computed as `Lead II − Lead I`

### EMG packet structure

One sample packet is 13 bytes:

- 1 byte packet type
- 3 bytes timestamp
- 9 bytes payload (EMG_CH1 and EMG_CH2 each as a 24-bit signed integer)

### Sampling rates

| Stream | Rate | Timestamp delta |
|---|---|---|
| ECG | 256 Hz | 128 ticks |
| EMG | 512 Hz | 64 ticks |

The Shimmer timestamp clock runs at 32768 ticks/second.

### Packet alignment

The serial input is a raw byte stream with no framing. On startup the bridge
reads an initial buffer and tests every possible byte offset (0 to
`packet_size − 1`). For each offset it measures the timestamp difference between
consecutive packets and compares it to the expected delta; the offset with the
smallest error is used as the packet boundary.

</details>

## How the timing correction works

**Drift correction.** The `ShimmerDiagnostics_ECG` stream (1 Hz) carries the
bridge's per-packet `last_observed_s = lsl_time − dev_ts`. Bluetooth transport
adds bimodal jitter, but the underlying crystal drift is a clean linear function
of time. `analysis/shimmer_clock_model.py` extracts it via one-way-delay minimum
filtering (10 s bins → minimum per bin → Theil-Sen line fit), yielding `(a, b)`
with `corrected_lsl_ts = a + b·dev_ts`, reproducible from the XDF alone.

**Absolute lag.** `analysis/insitu_lag_calibration.py` turns every calibration
keystroke into a fiducial and computes the median per-modality delta (with 95%
bootstrap CI) as the recording's `lag_ms`.

> **Known limitation:** `ShimmerECG` absolute lag is only a *lower bound* (the
> Bluetooth one-way minimum); it excludes internal ADC/filter delay. Audio and
> video lag are fully measured; ECG is not. Don't claim sub-ms ECG-to-physical
> sync.
