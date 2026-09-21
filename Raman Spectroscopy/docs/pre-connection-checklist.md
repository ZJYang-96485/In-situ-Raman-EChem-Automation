# Raman pre-connection checklist

The current Raman package is intentionally connection-free. Complete and
record these checks before replacing `MockRamanBackend` with a live backend.

1. Confirm each component's model and serial number at the bench. The current
   JSON profile is a transcription from photos, not a verified inventory.
2. Identify the exact computer, operating system, Andor camera driver/SDK, and
   spectrograph driver/SDK that are approved for the setup. Keep SDK versions
   and DLL locations outside the repository until they are validated.
3. Verify the detector, spectrograph, gratings, calibration source, and dark
   acquisition independently in the vendor software before automating them.
4. Record the excitation wavelength and optical configuration only after they
   are verified. The scaffold deliberately leaves this value unset. Store a
   wavelength-calibration record before applying `WavelengthCalibration` or
   calculating a Raman-shift axis.
5. Keep the laser power controller disabled. Do not implement laser enable,
   power, shutter, internal-fire-pulse, or external-TTL actions without a
   reviewed interlock/wiring diagram and laboratory laser-safety approval.
6. Treat planned electrochemistry/Raman timing as software best-effort until a
   validated shared hardware trigger and timestamp path exists. A correlation
   ID is metadata, not proof of simultaneous acquisition.
7. Exercise the mock tests before every live-backend development change:

   ```sh
   cd "Raman Spectroscopy"
   python -B -m unittest discover -s tests -v
   ```
