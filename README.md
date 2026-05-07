# Shimmer LSL Bridge

Stream ECG (and EMG) data from a Shimmer device to Lab Streaming Layer (LSL), record it with Lab Recorder, and examine the recorded data.

---

## Requirements

- Python 3.9 or later
- A Shimmer3 ECG unit with Bluetooth adapter
- Lab Recorder (portable, no installation needed — run `LabRecorder.exe`)

Install Python dependencies:

```
pip install -r requirements.txt
```

---

## Step 1 — Pair the Shimmer via Bluetooth

1. Power on the Shimmer device.
2. Open **Windows Settings → Bluetooth & devices → Add device**.
3. Select the Shimmer from the list and pair it. Use PIN `1234` if prompted.
4. Once paired, Windows assigns it a COM port. To find it:
   - Open **Device Manager → Ports (COM & LPT)**
   - Look for an entry like `Standard Serial over Bluetooth link (COM6)`
   - Note that port number — you will need it in the next step.

---

## Step 2 — Start the LSL bridge

Open a terminal in the project folder and run:

```
python run_lsl_streams.py
```

When prompted:
- Choose `ecg` for ECG only, `emg` for EMG only, or `both`.
- Enter the COM port (e.g. `COM6` for ECG).

The script will configure the Shimmer and start streaming to LSL. You will see output like:

```
[COM6] Sync: offset=3, error=0.2 ticks
[COM6] LSL outlet: ShimmerECG @ 256 Hz
Open LabRecorder, wait for ShimmerECG and ShimmerMarkers, then press Enter here.
```

Leave the terminal open and do not press Enter yet.

---

## Step 3 — Record with Lab Recorder

1. Open `LabRecorder.exe`.
2. Click **Update** — you should see `ShimmerECG` and `ShimmerMarkers` appear in the stream list.
3. Check both streams.
4. Set the output file path under **Filename** (e.g. `recording.xdf`).
5. Click **Start** to begin recording.

---

## Step 4 — Begin data capture

Go back to the terminal and press **Enter**.

The script will wait 2 seconds, then start the recording window. You will see:

```
[COM6] Recording started...
```

The default recording duration is 120 seconds. The script stops automatically when done and saves a filtered CSV and plot next to itself.

---

## Step 5 — Stop Lab Recorder

Once the terminal prints `All done.`, click **Stop** in Lab Recorder. Your `.xdf` file is now saved.

---

## Examining the recorded data

### Option A — Quick plot from the terminal output

When the script finishes it automatically saves two files next to itself:

| File | Contents |
|---|---|
| `ecg_synchronized.csv` | Timestamped Lead I, II, III values (millivolts) |
| `ecg_synchronized.png` | Plot of all three leads over time |

Open the PNG to get a quick look at the signal.

### Option B — Full XDF viewer

To inspect everything inside the `.xdf` file Lab Recorder saved (signals + marker events):

```
python plot_xdf_streams.py
```

A file picker dialog opens — select your `.xdf` file. The script will:

1. Print a summary of all streams and sample counts.
2. Print every marker event with its timestamp (session start, recording start/stop, etc.).
3. Export each stream to a CSV next to the XDF file.
4. Show an interactive plot of all channels with red lines marking marker events.

### Understanding the CSV columns

| Column | Description |
|---|---|
| `lsl_time_s` | Absolute LSL timestamp (seconds) |
| `time_rel_s` | Time relative to the first sample (seconds) |
| `Lead_I_mV` | Lead I voltage (millivolts) |
| `Lead_II_mV` | Lead II voltage (millivolts) |
| `Lead_III_mV` | Lead III (computed as Lead II − Lead I) |

### Understanding the marker events

The `ShimmerMarkers` stream contains JSON events logged throughout the session:

| Event | Meaning |
|---|---|
| `session_started` | Script launched |
| `stream_ready` | LSL outlet created, device configured |
| `recording_armed` | Enter pressed, recording countdown started |
| `recording_started` | Data capture began |
| `recording_stopped` | Data capture ended |
| `session_finished` | Script completed normally |

---

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

---

## Technical reference

<details>
<summary>Packet structure and timing details</summary>

### ECG packet structure

One sample packet is 14 bytes:
- 3 bytes timestamp
- 11 bytes payload (Lead II and Lead I each as a 24-bit signed integer)
- Lead III is computed as `Lead II - Lead I`

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

The serial input is a raw byte stream with no framing. On startup the code reads an initial buffer and tests every possible byte offset (0 to packet_size−1). For each offset it measures the timestamp difference between consecutive packets and compares it to the expected delta. The offset with the smallest error is used as the packet boundary.

</details>
