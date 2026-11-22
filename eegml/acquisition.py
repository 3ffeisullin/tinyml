"""ADS1115 settings and unit conversion (REQ-HW-02/03, REQ-ACQ-01/02).

The firmware uses these exact config words and LSB sizes (generated into
firmware/eeg_node/eeg_config.h by scripts/export_test_vectors.py). Bit layout of the
ADS1115 config register (datasheet, register 0x01):
  15 OS | 14:12 MUX | 11:9 PGA | 8 MODE | 7:5 DR | 4 COMP_MODE | 3 COMP_POL | 2 COMP_LAT | 1:0 COMP_QUE
ALERT/RDY becomes a conversion-ready pulse when Hi_thresh MSB = 1, Lo_thresh MSB = 0 and
COMP_QUE != 11.
"""
from .config import ADC_FALLBACK_PGA_FS_V, ADC_PGA_FS_V, ADC_SPS, PILL_GAIN

REG_CONVERSION, REG_CONFIG, REG_LO_THRESH, REG_HI_THRESH = 0x00, 0x01, 0x02, 0x03
LO_THRESH_RDY, HI_THRESH_RDY = 0x0000, 0x8000

MUX = {"diff_a0_a1": 0b000, "single_a0": 0b100}
PGA = {6.144: 0b000, 4.096: 0b001, 2.048: 0b010, 1.024: 0b011, 0.512: 0b100, 0.256: 0b101}
DR = {8: 0b000, 16: 0b001, 32: 0b010, 64: 0b011, 128: 0b100, 250: 0b101, 475: 0b110, 860: 0b111}


def config_word(mux: str, pga_fs_v: float, sps: int = ADC_SPS) -> int:
    """Continuous conversion, ALERT/RDY active low after every conversion (COMP_QUE = 00)."""
    return (MUX[mux] << 12) | (PGA[pga_fs_v] << 9) | (0 << 8) | (DR[sps] << 5) | 0b00000


CONFIG_DIFF = config_word("diff_a0_a1", ADC_PGA_FS_V)
CONFIG_SINGLE = config_word("single_a0", ADC_FALLBACK_PGA_FS_V)


def lsb_uv(pga_fs_v: float) -> float:
    """One ADC count in microvolts at the ADC input (16-bit signed: FS / 32768)."""
    return pga_fs_v * 1e6 / 32768


def counts_to_uv(counts, pga_fs_v: float = ADC_PGA_FS_V, gain: float = PILL_GAIN):
    """ADC counts -> microvolts at the electrode (REQ-ACQ-01)."""
    return counts * lsb_uv(pga_fs_v) / gain
