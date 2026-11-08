"""Classify part names into 74xx / 4000-series function groups.

group_key(name) -> ("74", "14") | ("74", "1G14") | ("54", "14") | ("40", "4060") | None
heading(key)    -> "74xx14" | "74xx1G14" | "54xx14" | "4060"
"""
import re

TECH = r"(?:ALVC|ALVT|AHCT|AHC|ACT|AC|ALS|AS|AUC|AUP|AVC|ABT|BCT|FCT|HCT|HCU|HC|HS|LVC|LVT|LVX|LV|LS|L|S|F|H|C|G|VHC|VCX|LCX|LPT|FST|CBT|CBTLV|AXP|AXC|LVQ|AC|ACQ|ACTQ|FCT|GTL|HCT|LVTH|ABTH|ALB|ALVCH|U)?"
VENDOR = r"(?:SN|DM|HD|MC|MM|CD|IDT|PI|NLV|NL|NC7S|NC7SZ|N|S|M|TC|SL|ITT|MIC|ZN|UPB|UPD|HEF|GD|KS|K|IN|T|MB|HA|HN|AM|DL|TL|IC|U|UT|ECG|NTE|SK|FD|FJ|FL|FLH|FZH|MH|CDB|UCY|SFC|SN74|X)?"

RX_74 = re.compile(rf"^{VENDOR}(54|74){TECH}((?:[123]G)?)(\d{{2,5}})")
RX_74_ANY = re.compile(rf"(54|74){TECH}((?:[123]G)?)(\d{{2,4}})")
# 4000-series CMOS. Only CMOS vendor prefixes: 4xxx numbers are shared by many
# unrelated parts (TP4056 / TC4054 Li-ion chargers, UPC4558 / MC4558 op-amps,
# LM4040 references). Cross-reference and Toshiba/Integral prefixes need the CMOS
# "B"/"UB" suffix (TC4013BP, NTE4011B); a bare 45xx (4558 = dual op-amp) needs a
# CMOS prefix; Rohm BU40xx analog switches/muxes are CMOS-compatible.
RX_40 = re.compile(r"^(CD|HEF|HCF|HCC|TC|NTE|ECG|SK|IW|BU)?(4[05]\d{2,3})((?:[A-Z].*)?)$")
CMOS_ALWAYS = {"CD", "HEF", "HCF", "HCC"}
CMOS_NEEDS_B = {"TC", "NTE", "ECG", "SK", "IW"}
RX_14K = re.compile(r"^(?:MC|HEF|HD|TC|HCF|CD)?14(\d{3})(?:[A-Z].*|$)")   # MC14001 -> 4001, MC14160 -> 40160
RX_9N = re.compile(r"^9N(\d{2,3})[A-Z]*$")                         # Fairchild 9N14 = 7414
RX_DL = re.compile(r"^DL(\d)(\d{2,3})[A-Z]*$")                     # East German DL000 = 7400

def _clean(name):
    return re.sub(r"[^0-9A-Z]", "", name.upper())

def group_key(name):
    c = _clean(name)
    if not c:
        return None
    m = RX_9N.match(c)
    if m:
        return ("74", m.group(1))
    m = RX_DL.match(c)
    if m:
        num = (m.group(1) + m.group(2)).lstrip("0").rjust(2, "0")
        return ("74", num)
    m = RX_74.match(c)
    if m and c.startswith("M5") and not re.match(r"M5[4]" + TECH[:-1] + r"[A-Z]", c):
        m = None                       # Mitsubishi M54xxx / M74xxx custom ICs
    if m and re.match(r"^M(54|74)\d", c):
        m = None
    if m and not c[m.end():m.end()+1].isdigit():
        fam = m.group(1)
        return (fam, m.group(2) + m.group(3))
    m = RX_14K.match(c)
    if m:
        d = m.group(1)
        return ("40", ("40" + d) if d[0] == "1" else ("4" + d))
    m = RX_40.match(c)
    if m and _cmos_40(*m.groups()):
        return ("40", m.group(2))
    return None


def _cmos_40(prefix, number, suffix):
    if not (len(number) == 4 or (len(number) == 5 and number.startswith("40"))):
        return False
    b_suffix = suffix.startswith(("B", "UB"))
    if prefix in CMOS_ALWAYS:
        return True
    if prefix in CMOS_NEEDS_B:
        return b_suffix
    if prefix == "BU":
        return number.startswith("40") or b_suffix
    return number.startswith("40")          # bare 4013 / 4013BE; bare 45xx is ambiguous

def group_key_loose(name):
    """For cross-reference names (NTE74LS132, ECG74C00, UPB74LS00...): find an
    embedded 74/54 number anywhere."""
    k = group_key(name)
    if k:
        return k
    c = _clean(name)
    if re.match(r"^M(54|74)\d", c):
        return None
    for m in RX_74_ANY.finditer(c):
        if not c[m.end():m.end()+1].isdigit():
            return (m.group(1), m.group(2) + m.group(3))
    return None

def heading(key):
    fam, num = key
    if fam == "40":
        return num
    return f"{fam}xx{num}"
