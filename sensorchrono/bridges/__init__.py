"""Real-time capture bridges (one LSL stream per modality).

Intentionally empty: do NOT import the submodules here. Each bridge pulls a
heavy, platform-specific capture dependency (``serial`` / ``cv2`` /
``sounddevice`` / ``pynput``) that is absent on a dev box and on CI, so they are
imported lazily — only when actually run, either via ``python -m
sensorchrono.bridges.<module>`` (dev) or the frozen ``--run-bridge`` dispatch.
"""
