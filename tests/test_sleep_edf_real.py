"""REQ-ML-01 on a real Sleep-EDF night, when one is already downloaded.

Skipped (not failed) on machines without the data, e.g. the cloud session.
This is the test that would have caught the channel-name bug.
"""
import numpy as np
import pytest

from eegml.sleep_edf import cached_night, find_channel, load_subject, subject_features

NIGHT = cached_night(0)


def test_find_channel_accepts_both_spellings_and_rejects_missing():
    assert find_channel(["Fpz-Cz", "Pz-Oz"], "EEG Fpz-Cz") == "Fpz-Cz"
    assert find_channel(["EEG Fpz-Cz"], "EEG Fpz-Cz") == "EEG Fpz-Cz"
    with pytest.raises(ValueError, match="available"):
        find_channel(["Pz-Oz"], "EEG Fpz-Cz")


@pytest.mark.skipif(NIGHT is None, reason="Sleep-EDF subject 0 not downloaded")
def test_subject0_loads_and_matches_mne_tutorial_epoch_count():
    x, fs, anns = load_subject(0)
    assert fs == 100.0 and x.ndim == 1 and np.isfinite(x).all()
    ours, mne_f, y = subject_features(x, fs, anns)
    # The MNE sleep tutorial reports 841 epochs for this night with the same trimming.
    assert len(y) == 841 and len(ours) == len(mne_f) == 841
    assert set(np.unique(y)) == {0, 1, 2, 3, 4}
