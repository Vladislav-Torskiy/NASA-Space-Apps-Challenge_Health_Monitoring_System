# Demo Sample Images (`data/demo_samples/`)

These synthetic medical demo images allow immediate offline or online testing of all three CV modes on `POST /api/vision/analyze`:

1. `sample_ultrasound.png` — Simulated lung ultrasound sector frame with vertical B-line artifacts (`mode="ultrasound"`).
2. `sample_skin_eye.png` — Simulated close-up skin patch showing a localized erythematous (redness) region (`mode="skin_eye"`).
3. `sample_device_ocr.png` — Simulated digital glucometer LCD screen displaying `138` (`mg/dL`) (`mode="device_ocr"`).

Regenerate anytime via:
```bash
python3 scripts/generate_demo_images.py
```
