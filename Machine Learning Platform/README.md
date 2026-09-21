# Machine Learning Platform

This folder is reserved for post-experimental data analysis, feature analysis,
machine learning, and model evaluation.

Raman diagnostics, despiking, smoothing, baseline correction, normalization,
and calibration remain in the `Raman Spectroscopy` module. This workspace
accepts only data with a recorded Raman preprocessing reference, preventing a
second and potentially inconsistent cleaning pipeline.

The current code provides configuration and readiness contracts only—no model
is fitted and no data is modified.

Run its checks with:

```sh
python -B -m unittest discover -s tests -v
```
