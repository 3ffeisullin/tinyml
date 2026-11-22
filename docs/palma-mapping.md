# Palma et al. (2024): what this project uses, and why

Review of the paper and its code against this project as it stands on 2026-11-22. By Claude Code (laptop), for
Farid and the cloud session.

- **Paper:** G. R. Palma, C. Thornberry, S. Commins, R. A. Moral, "Understanding learning from EEG data: combining
  machine learning and feature engineering based on hidden Markov models and mixed models", *Neuroinformatics*
  22(4):487–497, 2024, DOI 10.1007/s12021-024-09690-6. Open copies: arXiv 2311.08113, PMC11579152.
- **Code:** `3ffeisullin/EEG-Time-Series-Models` (Farid's copy of `GabrielRPalma/UnderstandingLearningWithML`, MIT
  licence), commit `96ae7c6`. It was read, not run: R scripts `00_source.r`, `02_HmmFeaturesExtraction/`, and the
  notebooks in `04_MlClassification/`. The published feature tables in `output_data/` were checked with pandas.

## 1. What the study is

| | Palma et al. | This project |
|---|---|---|
| Question | Can EEG plus movement tell people who learned a virtual maze from people who didn't? | What stage of sleep (and, later, what wake state) is a person in, every 30 s, on a wearable |
| People | 50 adults (25 learners, 25 non-learners; 47 in the published feature tables), awake | Sleep-EDF: 20 + 1 adults, asleep at home |
| EEG | BioSemi, 32 channels at 1024 Hz → 512 Hz; frontal midline theta = mean of F3/Fz/F4, 4–8 Hz Morlet wavelet envelope, about 128 samples/s | One channel, Fpz-Cz (training) / Fp1–mastoid (our headband), 250 Hz |
| Unit of analysis | One maze trial of up to 60 s (trials 1 and 12 only) → **one feature vector per person** | 30 s epochs → **about 1,000 feature vectors per night** |
| Labels | Group membership (learner or not), set by the experiment | Sleep stage per epoch, scored by technicians |
| Features | Per person: HMM fitted to the theta envelope (2–5 states: state means, SDs, time in each state = 42 features), mean peak height and curvature, two mixed-model random effects; plus four movement features | Per epoch: 6 band powers, their shares, skew, kurtosis, signal quality, summarised over 29 one-second windows |
| Models | SVMs, random forest, 1-nearest-neighbour, lasso/elastic net, 8-layer dense network (88,307 weights) | 3,525-weight dense network, int8, on a microcontroller |
| Validation | Leave-one-person-out (one vector per person, so person-wise) | 5-fold, split by person |
| Main result | Movement features classify well. EEG alone: only the dense network exceeded AUROC 0.8, on trial 12, with z-scored data | Macro F1 0.707 across 5 stages; board = PC on 100 % of a held-out night |

The paper is about a different question, on awake people, with one sample per person. **Its data and models can't
be reused here; its feature-engineering ideas can.** That's the conclusion the cloud session also reached on
2026-11-16 (requirements D-4).

## 2. Decision, item by item

| Palma element | Relevant now? | Decision |
|---|---|---|
| **HMM state features** (fit a Gaussian HMM to a person's signal; use state means, SDs and time in each state) | **Yes, the main idea to take.** Sleep is itself a hidden-state process, and REQ-FEAT-11 already calls for this. | Evaluate on Sleep-EDF (REQ-FEAT-11): HMM on the per-second band-power series, per night. Two changes from Palma's code: **sort states by mean** so "state 1" means the same thing for everyone (their code doesn't, see §3), and choose the number of states by BIC. Fitting runs on the PC/hub after the night. On the board, at most a fixed, pre-trained HMM's forward pass (cheap). Judge by macro F1 **and deep-sleep minutes error**. |
| **Peak features** (count of local peaks per second, mean peak height, mean curvature, on a band envelope) | **Yes, and better suited to sleep than to the maze.** Sleep's defining events are envelope peaks: spindles (sigma bursts, N2) and slow waves (large delta, N3). | Propose new features: sigma-envelope peak rate (≈ spindle density) and delta-envelope peak height/rate (≈ slow-wave activity), per epoch. Cheap on the board. Aimed directly at the N2 ↔ N3 confusion that inflates deep-sleep time (§5). Needs Farid's OK as a new requirement. |
| **Mixed-effects models** (per-person random intercept and slope) | **Not as model features. Yes for analysis later.** | When we have several nights per person (Phase D, Oura comparison), use mixed models to separate person-to-person from night-to-night variation, e.g. "is this person's deep sleep lower than their own baseline?". Fit them on all data properly, not per group (§3). |
| **Frontal midline theta** as a marker of learning / spatial memory | **Not for sleep staging.** A possible future wake-state capability. | Our electrode is Fp1, not Fz, and it's dominated by eye movements when awake, so we can't reproduce their measure. Park it as an idea for a "focus / learning" capability; revisit with a second channel near Fz. |
| **Morlet wavelet envelope** (fine time resolution) | Partly. | Our 1 s FFT windows are enough for 30 s staging. Wavelet or Hilbert envelopes would be needed for the peak features above; compute them on the PC first, then decide on the board. |
| **z-score vs min-max vs raw comparison** | Already covered. | Our calibration ablation (`reports/calibration_ablation.md`) compared normalisations and chose per-night running standardisation, which the board can do live. Palma's scaling is per group, not per person (§3), so it's not the source of our design. |
| **LIME explanations** | Useful later. | For explaining stages to users ("why did it call this deep sleep?"), use permutation importance or SHAP on the PC. Not needed for the demo. |
| **Leave-one-person-out validation** | Same principle we use. | Keep 5-fold by person (more stable with 20 nights); add leave-one-night-out when there are many nights per person. |
| Movement (maze) features, the trained Keras models, the dataset, the 8-layer network | **No.** | No maze, different inputs and labels, and the network has 88,307 weights for 47 samples of 46 features. Already out of scope (D-4). |

## 3. Things in the code to know before reusing it

These were found by reading the code and checking the published tables. They matter only if we copy code or
compare numbers; they don't affect anything we've built. None of the notebooks were re-run, so their effect on the
paper's results isn't measured here.

1. **The "z-scored" HMM features are min-max features.** `get_hmm_statistics` (`00_source.r`) checks for the
   names `'RawMidline'` and `'Scaled'`, but the caller passes `'ZscoredScaled'`, which falls through to the min-max
   branch. In `output_data/New_data/SplitDatasets/`, all 42 HMM columns of the "ZscoredScaled" tables are identical
   to the "Minmaxscale" ones, for both trials (checked). Only the 4 peak and mixed-model columns differ.
2. **Scaling is per group, not per person.** The z-score and min-max are computed over each group's whole file
   (all its participants and trials), separately for learners and non-learners
   (`02_obtaining_HMM_features.r`, lines 17–20). The cloud session's note that we "kept per-session standardisation"
   from Palma is therefore inaccurate: our per-night running standardisation came from our own ablation (2026-11-21).
   Corrected in `docs/STATUS.md` §6.
3. **Preprocessing depends on the label and sees the test person.** Group-wise scaling, and the mixed model fitted
   separately per group and on all participants before leave-one-out, mean each person's features depend on their
   group's statistics. For our use: compute any normalisation per person (or from training people only).
4. **HMM states aren't sorted.** The EM fit numbers states arbitrarily, so `hmm4_mean.1` can be a low-theta state
   for one person and a high-theta state for another. Sort by state mean before using them as features.
5. **Exploratory notebook slips.** `EEGData/DNN/dnn.ipynb` loads the trial-1 table for its "trial 12" variable and
   uses the test split as validation data. The paper's numbers come from the leave-one-out notebooks, which don't
   share these slips.
6. The paper reports 50 participants; the feature tables have 47 (25 non-learners, 22 learners).

If useful, items 1 and 4 could be reported to the authors as issues on the original repository.

## 4. What changes in this project

- **REQ-FEAT-11 (HMM features)** stays Open, with the two fixes above (sorted states, BIC), and is judged on macro F1
  and deep-sleep minutes.
- **Proposed new requirement** (for Farid's OK): spindle- and slow-wave-style envelope peak features, from Palma's
  peak/curvature idea.
- **Provenance:** `docs/model-provenance.md` now says the shipped model uses no Palma code, data or models.
- **Record corrected:** the 2026-11-16 STATUS note credited per-session standardisation to Palma; it isn't from there.

## 5. Why deep sleep is where to start

On the held-out night (subject 20), the board's stages give **45.0 min of N3 against the experts' 2.0 min**; REM is
44.5 vs 88.5 min (`reports/replay_sc20.csv`). Across all 20 cross-validated people, the totals are close (3,146 epochs
predicted N3 vs 2,981 true), so the error is per night rather than a systematic bias. Most of it is N2 epochs called
N3. Slow-wave and spindle features (the Palma-derived peak idea) and HMM state features are the two cheapest
experiments aimed at exactly that confusion. The next step adds a per-night "minutes per stage" error report so each
experiment is judged on it.
