"""Plain-text report of everything Oura has for one day (used by `day` and the demo display)."""


def _get(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def hm(minutes) -> str:
    """Minutes as '7 h 05 min' (or '44 min' under an hour)."""
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _hm_sec(sec):
    """Seconds as hm() text, or None."""
    return None if sec is None else hm(sec / 60)


def _num(x, decimals=0):
    """Number with thousands separators and fixed decimals ('12,345', '1.2'); other values unchanged."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return x
    return f"{x:,.{decimals}f}"


def day_lines(v) -> list[tuple[str, str]]:
    """(label, value) rows for everything in a day_view; missing values are skipped."""
    s, n, rows = v["summary"] or {}, v["night"] or {}, []

    def add(label, val, unit=""):
        if val is not None and val != "":
            rows.append((label, f"{val}{unit}"))

    if s:
        add("Bed → up (local)", f"{s['start_local']} → {s['end_local']}")
        add("In bed", hm(s["in_bed_min"]))
        add("Asleep", hm(s["sleep_min"]))
        add("Deep", f"{hm(s['deep_min'])} ({s['deep_pct']:.0f} % of sleep)")
        add("Light", hm(s["light_min"]))
        add("REM", hm(s["rem_min"]))
        add("Awake", hm(s["awake_min"]))
    add("Sleep efficiency", n.get("efficiency"), " %")
    add("Time to fall asleep", _hm_sec(n.get("latency")))
    add("Average heart rate", n.get("average_heart_rate") and round(n["average_heart_rate"]), " bpm")
    add("Lowest heart rate", n.get("lowest_heart_rate"), " bpm")
    add("Average HRV", n.get("average_hrv"), " ms")
    add("Breathing rate", _num(n.get("average_breath"), 1), " /min")
    add("Restless periods", n.get("restless_periods"))
    add("Sleep score", _get(v, "daily_sleep", "score"))
    for k, x in (_get(v, "daily_sleep", "contributors") or {}).items():
        add(f"  sleep: {k.replace('_', ' ')}", x)
    add("Readiness score", _get(v, "daily_readiness", "score"))
    add("Temperature deviation", _get(v, "daily_readiness", "temperature_deviation"), " °C")
    for k, x in (_get(v, "daily_readiness", "contributors") or {}).items():
        add(f"  readiness: {k.replace('_', ' ')}", x)
    add("Activity score", _get(v, "daily_activity", "score"))
    add("Steps", _num(_get(v, "daily_activity", "steps")))
    add("Active calories", _num(_get(v, "daily_activity", "active_calories")), " kcal")
    add("Total calories", _num(_get(v, "daily_activity", "total_calories")), " kcal")
    add("Stress (day summary)", _get(v, "daily_stress", "day_summary"))
    add("High stress", _hm_sec(_get(v, "daily_stress", "stress_high")))
    add("High recovery", _hm_sec(_get(v, "daily_stress", "recovery_high")))
    add("Resilience", _get(v, "daily_resilience", "level"))
    add("SpO2 average", _get(v, "daily_spo2", "spo2_percentage", "average"), " %")
    add("Cardiovascular age", _get(v, "daily_cardiovascular_age", "vascular_age"), " years")
    add("VO2 max", _get(v, "vO2_max", "vo2_max"), " ml/kg/min")
    add("Heart-rate samples in the night", len(v["hr_samples"]) or None)
    return rows


def print_day(v):
    if not v["day"]:
        print("No nights stored yet: run `pull` first.")
        return
    print(f"Oura, day {v['day']}  (stored days: {', '.join(v['days'])})")
    for label, val in day_lines(v):
        print(f"  {label:34s} {val}")
