# Deep sleep (N3): what it is, how well it can be measured, and where we stand

Research note for the first demo (2026-12-04, moved from 11-27), where deep sleep is the lead topic. By Claude Code (laptop),
2026-11-22. Results from this repo are reproducible with the scripts named; outside facts carry a source.

## 0. Why deep sleep is the lead topic

The project exists because the Oura Ring's nightly deep-sleep number is
unreliable. The ring has no EEG: it infers stages from heart rate, HRV,
temperature and movement, while deep sleep is defined by frontal slow waves
(§1). In healthy adults it is right on average but agrees poorly night by
night (ICC 0.32, Robbins et al., Sensors 2024). In adolescents it
over-estimated deep sleep by 31.5–46.8 min per night (Chee et al., 2021);
an earlier study found it under-estimated by about 20 min (de Zambotti et
al., 2017). The AASM position statement on consumer sleep technology (lead
author Seema Khosla, a pulmonologist and sleep physician) says these devices
are not validated for diagnosis or treatment. Oura is still among the
better-validated consumer trackers; the gap this project targets is the
per-night deep-sleep total, which is also where our own model is weakest
(§3). Full study list with links: README.md, "Why this project".

## 1. What scorers call deep sleep

- **The rule (AASM, 2007 onward):** a 30 s epoch is N3 when **slow waves** (0.5–2 Hz, larger than **75 µV
  peak-to-peak**, measured on a **frontal** lead against the opposite mastoid) fill **at least 20 % of the epoch**
  (6 s). It is an *absolute amplitude* rule. [AASM summary in 3]
- **Sleep-EDF uses the older Rechtschaffen & Kales rules**, where stages 3 and 4 (20–50 % and > 50 % slow waves) are
  merged into N3 here, scored on Fpz–Cz. AASM scoring with frontal leads gives a little more N3 than R&K: about
  +9 min per night in one comparison of 72 recordings, and +10.6 min from the electrode change alone in another. [3]
- **Spindles** (11–16 Hz bursts of 0.5–2 s) mark N2; slow waves mark N3. Most scoring errors on deep sleep are about
  where N2 ends and N3 begins.
- **Age matters a lot.** Slow-wave sleep falls steadily with age in adults (meta-analysis of 65 studies, 3,577
  people). [4] Our 20 training nights are all from people aged **25–34** (Sleep-EDF SC subjects 0–19), so the model
  has never seen an older sleeper's smaller slow waves.

## 2. How well anyone can measure it

| Who / what | Deep-sleep agreement | Source |
|---|---|---|
| Human experts (AASM inter-scorer programme, > 2,500 scorers) | On epochs the majority called N3, **67.4 %** of scorers agreed; nearly all the rest (32.3 %) said N2. N3 and N1 had the lowest agreement of all stages. | [1] |
| Five expert scorers vs each other's consensus | N3 F1 **78.3 %** (SD 23.8) | [2] |
| Dreem headband (frontal dry EEG, forehead + occipital) | N3 F1 **76.4 %** (SD 22.9), close to the experts | [2] |
| Oura ring Gen3 (no EEG: heart rate, HRV, temperature, motion), 35 adults aged 20–50 | Deep sleep 95 min on average for both ring and PSG (no bias), per-epoch sensitivity 79.5 %, precision 77.0 %, but **per-night agreement poor (ICC 0.32)** and the ring's spread is narrower (SD 21 vs 35 min). | [5] |
| Oura ring (earlier study), 53 adolescents aged 15–19 | Deep sleep **over-estimated by 31.5–46.8 min** per night | [5] |
| **This project, int8 model on the XIAO** (20 nights, cross-validated) | Per epoch: N3 recall **0.80**, precision **0.76**; 482 of 2,981 deep-sleep epochs missed as N2, 671 N2 epochs called N3. | `reports/sleep_model.md`, `reports/sleep_model_cv_predictions.npz` |

**Reading:** per epoch, our deep-sleep calls are about as good as expert scorers agree with each other. The
weakness is **per night** (§3), and that is what a user sees ("you had 45 min of deep sleep"). The Oura ring shows
the same pattern in its own validation (right on average, poor night-by-night agreement, compressed spread), so
"deep-sleep minutes per night that track the experts" is a fair place for an EEG headband to beat a ring.

## 3. Where we stand per night

From `reports/stage_minutes.md` (20 cross-validated nights):

- Deep sleep is right **on average** (bias +4.1 min), but off by **25.2 min on a typical night** (worst −63 min) and
  tracks the experts only moderately (r 0.60).
- The model **pulls every night toward the average**: experts' deep sleep ranges 0.6–43 % of sleep, the model's
  8.6–34 %. Light-sleep nights get too much deep sleep, deep-sleep nights too little.
- Held-out night SC20 on the board: 45.0 min deep sleep against the experts' 2.0 min.

## 4. New finding: the model can't see absolute slow-wave size

The scoring rule is about absolute amplitude (> 75 µV), but our model sees each night's features standardised by
that night's own running mean/SD (REQ-FEAT-10). A night with few large slow waves therefore still has "its most
delta-heavy epochs", and they get called N3. That would explain the compression in §3 and why the random forest,
which sees raw µV features, has the lower deep-sleep error (18.4 vs 25.2 min).

Test (`scripts/deep_sleep_scale_ablation.py`, `reports/deep_sleep_scale_ablation.md`): same 20 nights and folds, float
net, only the input scaling changes.

| Input scaling | Macro F1 | Deep sleep: typical error per night | Deep sleep: r | Deep sleep % of sleep, range | REM error | Total sleep error |
|---|---|---|---|---|---|---|
| Per night, running (as deployed) | 0.717 | 24.6 min | 0.65 | 8.7–35.5 % | 18.1 min | 22.6 min |
| Fixed, from training people (keeps absolute µV) | 0.720 | **20.4 min** | **0.82** | 4.9–48.2 % (experts 0.6–43.2) | 28.0 min | 28.1 min |
| Both side by side | 0.725 | 24.2 min | 0.69 | 3.0–46.6 % | 15.7 min | 31.4 min |

**Reading:** keeping the absolute level makes deep-sleep minutes track the experts much better (r 0.65 → 0.82) with
no loss of macro F1, but REM and total sleep get worse, which is why per-night scaling was chosen in the first place
(it copes with different people and electrodes). One seed per variant, so treat differences of a few minutes as
noise. The likely best design is **per-night scaling for most features plus a few calibrated absolute-µV slow-wave
features**, which is exactly REQ-FEAT-12.

**Consequence for the hardware:** absolute µV only means something after the bench calibration of `PILL_GAIN`
(`docs/bringup.md` step 5, the 100 µV p-p 10 Hz signal). That calibration is on the critical path for deep sleep.
Also, our headband reads Fp1–mastoid, which shows *larger* slow waves than Sleep-EDF's Fpz–Cz (shorter, more
central pair), so an amplitude mapping is needed before Sleep-EDF thresholds apply to the headband.

## 5. Detecting slow waves and spindles (REQ-FEAT-12)

Reference detectors, from the open-source YASA toolbox (Vallat & Walker, eLife 2021), whose defaults follow
Massimini et al. 2004 and Carrier et al. 2011 for slow waves and Lacourse et al. 2018 for spindles. [6, 7, 8] These
parameters are reference points to read, not code to copy; ours go in `eegml/config.py`.

| | YASA default | Plan for us (causal, device-friendly) |
|---|---|---|
| Slow waves | Band 0.3–1.5 Hz; negative half-wave 0.3–1.5 s; trough 40–200 µV; peak-to-peak 75–350 µV | Low-pass the filtered signal below 2 Hz; detect negative half-waves between zero crossings; per epoch: count, mean peak-to-peak µV, and fraction of the epoch in waves > 75 µV (the AASM quantity itself) |
| Spindles | Band 12–15 Hz; 0.5–2 s; thresholds on relative sigma power (0.2), correlation with the broadband signal (0.65), RMS above mean + 1.5 SD; merge bursts < 0.5 s apart | Sigma band 11.5–15.5 Hz (our band, REQ-FEAT-02); envelope RMS over 0.3 s; threshold relative to the night's running sigma level; per epoch: count (density) and mean amplitude |

Both are cheap on the XIAO (two extra biquads plus a few counters per sample).

## 6. Order of work for deep sleep

1. **Before the demo (no hardware needed):** show deep sleep on replayed Sleep-EDF nights with the per-night error
   stated honestly ("typically within about 25 min of sleep experts; experts themselves disagree on a third of
   deep-sleep epochs"). The display already shows the replayed hypnogram.
2. **REQ-FEAT-12 slow-wave and spindle features** on Sleep-EDF; judge on deep-sleep minutes and macro F1; then decide
   on the mixed scaling of §4.
3. **Bench calibration of `PILL_GAIN`** when the parts arrive (Tuesday 2026-12-01), so device µV are real.
4. **Oura comparison** (task 5): Oura's sleep periods give deep-sleep seconds and a 5-minute hypnogram
   (`deep_sleep_duration`, `sleep_phase_5_min` with 1 = deep), so a night on the headband can be compared with the
   ring's deep sleep. The ring is not the reference (see §2), and Oura's API terms restrict AI processing of its data
   (REQ-OURA-09), so compare, don't train, until that is reviewed.
5. HMM state features (REQ-FEAT-11) after REQ-FEAT-12.
6. Later: nights from older sleepers (Sleep-EDF has people up to 101), since deep sleep shrinks with age.

## Sources

1. Rosenberg RS, Van Hout S. The American Academy of Sleep Medicine inter-scorer reliability program: sleep stage
   scoring. *J Clin Sleep Med* 2013;9(1):81–87. https://pmc.ncbi.nlm.nih.gov/articles/PMC3525994
2. Arnal PJ et al. The Dreem Headband compared to polysomnography for electroencephalographic signal acquisition and
   sleep staging. *Sleep* 2020;43(11):zsaa097. https://pmc.ncbi.nlm.nih.gov/articles/PMC7751170
3. Moser D et al. Sleep classification according to AASM and Rechtschaffen & Kales: effects on sleep scoring
   parameters. *Sleep* 2009;32(2):139–149. https://pmc.ncbi.nlm.nih.gov/articles/PMC2635577 (AASM N3 rule as
   summarised there; electrode-placement effect from a separate study cited in the same search).
4. Ohayon MM et al. Meta-analysis of quantitative sleep parameters from childhood to old age in healthy individuals.
   *Sleep* 2004;27(7):1255–1273. https://pubmed.ncbi.nlm.nih.gov/15586779/
5. Oura validation. Adults: "Accuracy of Three Commercial Wearable Devices for Sleep Tracking in Healthy Adults",
   2024, https://pmc.ncbi.nlm.nih.gov/articles/PMC11511193 (PubMed 39460013). Adolescents: "Multi-Night Validation
   of a Sleep Tracking Ring in Adolescents Compared with a Research Actigraph and Polysomnography",
   https://pmc.ncbi.nlm.nih.gov/articles/PMC7894804 . Some Oura studies are company-funded.
6. Vallat R, Walker MP. An open-source, high-performance tool for automated sleep staging. *eLife* 2021;10:e70092.
   https://elifesciences.org/articles/70092
7. YASA `sw_detect`: https://yasa-sleep.org/generated/yasa.sw_detect.html
8. YASA `spindles_detect`: https://yasa-sleep.org/generated/yasa.spindles_detect.html
