# Sleep-EDF baseline, Fpz-Cz only

20 subjects, 20626 epochs, 5-fold leave-subjects-out, random forest (100 trees).

| Feature set | Accuracy | Macro F1 | Recall W | Recall N1 | Recall N2 | Recall N3 | Recall REM |
|---|---|---|---|---|---|---|---|
| Device pipeline (eegml) | 0.774 | 0.680 | 0.84 | 0.20 | 0.85 | 0.83 | 0.68 |
| MNE tutorial features | 0.729 | 0.621 | 0.74 | 0.13 | 0.82 | 0.76 | 0.66 |

Published MNE tutorial (2 EEG channels, 1 train / 1 test subject): accuracy 0.687, macro F1 0.57.

REQ-ML-02 passes if the device pipeline's macro F1 >= the MNE-tutorial feature set's under this same split: **PASS**
