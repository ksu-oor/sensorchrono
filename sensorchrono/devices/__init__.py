"""Device adapters — one per capture modality.

Each adapter conforms to :class:`sensorchrono.devices.base.DeviceAdapter` and
either drives a real bridge subprocess (Phase 2: ``shimmer_exg``, ``camera``,
``microphone``, ``keyboard``) or synthesizes data for hardware-free dry-run
(``simulated``). The orchestration layer iterates over adapters generically,
so adding the accelerometer or EMOTIV later is one new file here.
"""
