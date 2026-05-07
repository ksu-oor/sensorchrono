# Shimmer LSL Bridge

Stream ECG (and EMG) data from a Shimmer device to Lab Streaming Layer (LSL), record it with Lab Recorder, and examine the recorded data.

---

## Requirements

- Python 3.9 or later
- A Shimmer3 ECG unit with Bluetooth adapter
- Lab Recorder (portable, no installation needed — run `LabRecorder.exe`)

**If also using EMOTIV:**
- An EMOTIV headset (Insight 2 or other Cortex-supported model)
- EMOTIV Launcher installed and running in the background
- An EMOTIV developer account with a registered app — get credentials at [emotiv.com/developer](https://www.emotiv.com/developer/)

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

## Step 2 — EMOTIV setup (skip if not using EMOTIV)

### 2a — Install EMOTIV Launcher

Download and install **EMOTIV Launcher** from [emotiv.com/emotiv-launcher](https://www.emotiv.com/emotiv-launcher/). This app must be running in the background whenever you stream EMOTIV data — it handles the headset connection and exposes the Cortex API that the bridge talks to.

### 2b — Create a developer account and get credentials

1. Go to [emotiv.com](https://www.emotiv.com) and create a free account if you don't have one.
2. Log in and navigate to **My Account → Developer → My Apps**.
3. Click **Create New App**.
4. Fill in a name (anything works, e.g. `LSL Bridge`) and submit.
5. Your **Client ID** and **Client Secret** will appear on the app page. Copy both.

### 2c — Create your credentials file

Create a plain text file called `credentials.txt` in the project folder:

```
CLIENT_ID=your_client_id_here
CLIENT_SECRET=your_client_secret_here
```

### 2d — Approve data access in EMOTIV Launcher

The first time you run the bridge, EMOTIV Launcher will show a popup asking you to approve data access for your app. Click **Accept**. You only need to do this once per app registration.

---

## Step 3 — Start the LSL bridge

Open a terminal in the project folder and run:

```
python run_lsl_streams.py
```

When prompted, choose what to stream:

| Option | What it runs |
|---|---|
| Shimmer: `ecg` | ECG only |
| Shimmer: `emg` | EMG only |
| Shimmer: `both` | ECG + EMG |
| Shimmer: `none` | Skip Shimmer |
| EMOTIV: `app1` | One EMOTIV headset |
| EMOTIV: `none` | Skip EMOTIV |

Enter the Shimmer COM port when asked (e.g. `COM6`). If running EMOTIV, enter the path to your `credentials.txt` when asked.

You can also pass everything as flags to skip the prompts:

```
# Shimmer ECG only
python run_lsl_streams.py --shimmer ecg --ecg-port COM6 --emotiv none

# Shimmer ECG + EMOTIV together
python run_lsl_streams.py --shimmer ecg --ecg-port COM6 --emotiv app1 --credentials-file credentials.txt
```

The script will configure the devices and start streaming to LSL. You will see output like:

```
[COM6] Sync: offset=3, error=0.2 ticks
[COM6] LSL outlet: ShimmerECG @ 256 Hz
Open LabRecorder, wait for ShimmerECG and ShimmerMarkers, then press Enter here.
```

Leave the terminal open and do not press Enter yet.

---

## Step 4 — Record with Lab Recorder

1. Open `LabRecorder.exe`.
2. Click **Update** — you should see the available streams appear:

| Stream | Present when |
|---|---|
| `ShimmerECG` | Shimmer ECG is running |
| `ShimmerEMG` | Shimmer EMG is running |
| `ShimmerMarkers` | Always (timing events) |
| `EmotivEEG` | EMOTIV headset connected |
| `EmotivMOT` | EMOTIV motion data |

3. Check all the streams you want to record.
4. Set the output file path under **Filename** (e.g. `recording.xdf`).
5. Click **Start** to begin recording.

---

## Step 5 — Begin data capture

Go back to the terminal and press **Enter**.

The script will wait 2 seconds, then start the recording window. You will see:

```
[COM6] Recording started...
```

The default recording duration is 120 seconds. The script stops automatically when done and saves a filtered CSV and plot next to itself.

---

## Step 6 — Stop Lab Recorder

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
