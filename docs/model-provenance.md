# Where the sleep model comes from

A plain-language account of the sleep-stage model that runs on the XIAO: who made it, from what data, how it
was tested, and what hasn't been tested yet. Written for readers who aren't machine-learning engineers.
Last updated 2026-11-22.

> This is a hobby/research tool. It makes no medical or diagnostic claims (REQ-SAFE-04).

## In one paragraph

We trained the model **from scratch with our own scripts**. We did not start from, download or fine-tune
anyone else's model. The training data is a public, research-grade sleep dataset (Sleep-EDF, published on
PhysioNet), in which sleep experts labelled every 30 seconds of each night by hand. We trained on 20 people and
measured accuracy only on people the model hadn't seen. The board was checked against our reference software on a
21st person's night that was never used for training, and it gave the same answer for every 30-second epoch.
The model has **not** yet seen any data from our own headband.

## 1. The model on the board

| Question | Answer |
|---|---|
| Built from scratch or pre-trained? | **From scratch.** A small neural network (3,525 numbers, about 6 KB after compression), trained by our own script. No pre-trained or downloaded model was used. TensorFlow is used only as the toolkit that trains and compresses it. |
| Which script? | `scripts/train_sleep_model.py`, which uses `eegml/` (the signal-processing and model-input code). It reads features computed by `scripts/sleep_edf_baseline.py` from the raw recordings. |
| Which file is on the board? | `firmware/eeg_node/sleep_model.h` (model version 2), SHA-256 `8e2369762f902464438fac6a1ecd1d4c746ca96fa89657177772d9477975e4de`. |
| Which commit produced it? | **`2fb6c77`** (2026-11-21, "Run the int8 sleep model on the XIAO …"). That commit's code was run to generate the file, and the file hasn't changed since. Later commits added firmware around it but never retrained the model. **Checked 2026-11-22:** re-running `scripts/train_sleep_model.py` (fixed random seed 241) on the same 20 nights rebuilt a byte-identical file (same SHA-256), so the result is reproducible. |
| What does it do? | Every 30 seconds it takes 30 numbers describing the brain signal in that epoch (power in 6 frequency bands, their shares, how spiky the signal is, quality measures), plus the same 30 numbers from the previous two epochs, and outputs one of five stages: Wake, N1 (light), N2, N3 (deep) or REM (dreaming). |
| Why "int8"? | The network was compressed from 32-bit numbers to 8-bit integers so it fits and runs fast on the small chip. The compressed model agrees with the uncompressed one on 98.68 % of test epochs. |

## 2. The data

| Question | Answer |
|---|---|
| Dataset | **Sleep-EDF Database Expanded** (`sleep-edfx`), version 1.0.0, "sleep cassette" part. |
| Who published it | PhysioNet (MIT Laboratory for Computational Physiology). Recordings from the study by Kemp, Zwinderman, Tuk, Kamphuisen and Oberyé (Leiden, the Netherlands). Dataset DOI 10.13026/C2X676. |
| Where we downloaded it | `https://physionet.org/physiobank/database/sleep-edfx/sleep-cassette/`, via the MNE-Python library's Sleep-EDF downloader (`mne.datasets.sleep_physionet.age.fetch_data`). Files are stored on the laptop only and are never committed to the repo. |
| Licence | **Open Data Commons Attribution License v1.0** (free to use, including commercially, with attribution). |
| Who the people are | The sleep-cassette recordings come from a 1987–1991 study of age effects on sleep in healthy Caucasian adults aged 25–101, taking no sleep-related medication, recorded at home. |
| Which people and nights we used | **Training:** subjects 0–19, the first night of each (20 nights, files `SC4001`…`SC4191`), 20,626 labelled 30-second epochs. **Held-out check on the board:** subject 20, first night (`SC4201`). |
| Which EEG channel | **Fpz-Cz** only (forehead to top of head), the closest public match to our headband's forehead lead. Recorded at 100 Hz; we resample it to 250 Hz, our board's rate, before any processing. |
| Who labelled the sleep stages, and how | **Trained sleep technicians, by hand**, using the standard 1968 Rechtschaffen & Kales scoring manual, looking at the full recording (EEG, eye movement and chin muscle channels). Each 30-second epoch got one label: Wake, 1, 2, 3, 4, REM, Movement or "?". We merge stages 3 and 4 into N3 (the modern convention) and skip Movement and "?" epochs when training. We also trim long stretches of wake: we keep only 30 minutes before the first and after the last sleep. |

Note that the labels come from experts who saw more channels than our model gets (it only sees one forehead
channel). That's one reason REM and quiet wake are hard for it to tell apart.

## 3. How the data was split

| Purpose | In simple terms |
|---|---|
| **Measuring accuracy** (the headline numbers) | The 20 people were divided into 5 groups of 4. Five times over, the model was trained on 16 people and tested on the other 4, **who it had never seen**. Every person was tested exactly once, always by a model that never saw them during training. No person's night was ever split between training and testing. Result: accuracy 0.768, macro F1 0.707 (`reports/sleep_model.md`). |
| **Deciding when to stop training** (validation) | Inside each round, 3 of the 16 training people were set aside to watch for over-training, and training stopped when results on them stopped improving. |
| **The model on the board** | After the 5 rounds, one final model was trained on **all 20 people**, for 19 passes over the data (the typical stopping point from the 5 rounds). So subjects 0–19 are all in its training data. Its accuracy estimate is the 5-round result above. |
| **Calibrating the 8-bit compression** | Compression needs examples of typical inputs to set its number ranges: 1,000 randomly chosen epochs from the training data. In the 5 test rounds they came only from that round's training people; for the final model, from all 20. Test people were never used. |
| **Per-person normalisation** | Each night is normalised using a running average of that night so far, exactly as the board does it live. No information from later in the night is used. |

## 4. What the board itself was tested on

| Test | Data | Were these people in training? |
|---|---|---|
| Whole chain on a replayed night (task 6b, `reports/replay_sc20.md`) | Subject 20's first night (8.5 h, 1,023 epochs), streamed to the board over USB | **No.** Subject 20 was never used in training. The board's stages matched our reference software on 100 % of epochs. Against the experts' labels it scored accuracy 0.670 / macro F1 0.466 on this one night. |
| Model check (task 4b, `reports/xiao_bench_2026-11-21.txt`) | 5 epochs built into the firmware, one per stage | **Yes,** taken from subject 0. This test only checks that the board computes the same numbers as the PC (5/5 identical); it says nothing about accuracy. |
| Signal-processing check (task 6, `reports/xiao_feature_parity_2026-11-21.txt`) | A synthetic 12-second test signal (made-up alpha, delta and spindle waves plus noise and mains hum) | Not real EEG from anyone. Checks the board's filters and features against the PC. |
| Live path (task 7a, `reports/xiao_live_fake_2026-11-22.txt`) | The same synthetic signal, fed through the live acquisition path by a timer | Not real EEG. Checks timing and that no samples are lost. |

## 5. What hasn't been tested yet

- **Our own headband.** Every result so far uses Sleep-EDF recordings or synthetic signals. The BioAmp EXG Pill and
  ADS1115 front end hasn't recorded anything yet (parts due Tuesday 2026-12-01).
- **Our electrode placement.** We plan Fp1 (forehead, left) to mastoid (behind the ear); the training data is Fpz-Cz.
  These see somewhat different signals, so accuracy on our recordings is unknown until we measure it.
- **Our environment.** Sleep-EDF was recorded in Europe (50 Hz mains) with 1980s–90s equipment; we record in the US
  (60 Hz), with different amplifiers and gel electrodes.
- **Real nights with the headband.** No overnight recording yet (Phase D), and so no comparison with the Oura ring,
  whose own stages are estimates from heart rate, movement and temperature, not EEG.
- **People outside the dataset.** The training people were healthy Caucasian adults without sleep medication; how
  the model does for anyone else is unknown.
- **Artefacts.** Movement, electrode pops and sweat aren't filtered out by a dedicated detector yet (REQ-ML-05);
  epochs the experts marked "movement" were simply skipped in training.
- **Accuracy on more than one held-out night.** The board was checked on one unseen night; the cross-validated
  estimate covers 20 people.

## 6. Relation to Palma et al. (2024)

The project's foundational reference is Palma, Thornberry, Commins & Moral, *Understanding learning from EEG
data*, Neuroinformatics 2024 (code: `3ffeisullin/EEG-Time-Series-Models`). **The model on the board uses no code,
data or trained model from that work.** Their study classifies maze learners from awake EEG, one sample per
person, with no sleep labels, so its data and models can't train a sleep stager. Its feature-engineering ideas
(HMM state features, envelope peak features, mixed models) are being evaluated as additions; see
`docs/palma-mapping.md` for what is used, what isn't, and why.

## Sources

- Dataset page and licence: <https://physionet.org/content/sleep-edfx/1.0.0/>
- Sleep-cassette files: <https://physionet.org/content/sleep-edfx/1.0.0/sleep-cassette/>
- Registry entry (licence): <https://registry.opendata.aws/sleep-edfx/>
- Repo files: `scripts/train_sleep_model.py`, `eegml/sleep_edf.py`, `eegml/sleep_model.py`, `reports/`.
