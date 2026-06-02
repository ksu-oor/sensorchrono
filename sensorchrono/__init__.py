"""sensorchrono — multi-modal sync suite for LSL.

See outputs/PRD_lsl_sync_suite.md (in the repo root) for the full design.

Layout:
    bridges/       device-specific LSL producers (shimmer_exg, shimmer_accel,
                   video, audio, keyboard, emotiv)
    fiducials/     producers of timed reference events (audio_pulse,
                   keyboard_event, led_flash)
    detectors/     consumers that find fiducial events in recorded streams
                   (audio_onset, accel_onset, frame_diff)
    postprocess/   dejitter, drift correct, lag subtract, MP4 remux, validate

Each item above corresponds to a top-level script in the repo today
(shimmer_lsl_bridge.py, video_lsl_bridge.py, etc.). Those scripts will be
incrementally migrated into this package as the v1 MVP comes together.
"""

__version__ = "0.0.1"
