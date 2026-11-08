# Match rules

Every `.py` file in this folder (and in `<DATA>/match_rules/`) is a matching
rule, used by **Pinout manager → Batch pinout review** (ICPin catalogs) and by
**Library → Run matching** (pin-library definitions). Files starting with `_`
are helpers, not rules. Rules load in file-name order.

A rule that fails to load, raises in `prepare`, `candidates` or `review`, or
returns a result of the wrong shape (see `rule_api.py`), is skipped for the whole scan: the scan is recomputed without it, so no partial
output of a broken rule remains. The error is reported once per rule
(`scan(...)['rule_errors']` for the library, `pinout_matcher.scan.rule_errors`
for batch review) and shown in the status line; matching continues without it.

**Site rules need trust on each computer (0.8.1).** Files in `<DATA>/match_rules/`
are Python programs on a shared folder. Before **Run matching** or a batch scan,
ICDB lists new or changed site rule files and asks: *Yes* trusts those exact
files (by SHA-256) on this computer, *No* runs without them, *Cancel* stops.
Editing a file makes it new again. Decisions are stored outside DATA in
`%LOCALAPPDATA%\IC_Tools\trusted_match_rules.json`; delete that file to be asked
again. Shipped rules (next to the application) are always used. Rules no longer
need `sys.path.insert(...)`: `from _shipped_helpers import ...` works directly.

Rules only *propose* or *flag* candidates. Nothing is linked until you accept it.
A row with a CAUTION (reason contains `CAUTION:`) starts unchecked and is never
in "Ready to accept".

## Built-in matches (not files)

| Rule id | Rank | What it does |
| --- | --- | --- |
| exact-v1 | 0 | Same part name. A different (known) manufacturer is a CAUTION, not a block: second sources share exact names. |
| 4000-prefix-v1 | 2 | Bare 4xxx device and CD/HEF/HCF/MC1/HD1 + same number. |
| prefix-suffix-v1 | 2 / 3 | Same number, suffix variant (rank 2: LM2902 → LM2902N) or nearby prefix (rank 3: LM2902 → L2902). |
| prefix-shared-number-v1 | 4 | Only the number is shared (BC547 → LM547): **Blocked** ("link manually if correct") unless both prefixes are known second-source prefixes (LM TL NE SA SE KA UA MC L AZ LMV TS NJM RC KIA), then CAUTION. In **Batch pinout review** these rows stay in the *Shared number only* queue as a CAUTION and never start checked (0.8.1). |

## Shipped rule files

| File | Rule | What it does |
| --- | --- | --- |
| 10_logic_family.py | Logic family | 74/54-series and 4000 CMOS: any part with the same function number as a device on the diagram (74HC14, SN74LS14N, DM7414, 9N14, DL014 -> 74xx14; CD4060B, MC14060 -> 4060). 74xx1G14 single gates and 54xx stay separate. 4000-series needs a CMOS prefix (CD, HEF, HCF, HCC, BU40xx; TC/NTE/ECG/SK/IW only with the B/UB suffix; bare 40xx) - TP4056, TC4054, UPC4558, MC4558, LM4040 are not CMOS logic. |
| 15_cmos_cross_family.py | CMOS cross family | 74HC40xx/45xx ↔ CD40xx/45xx with the same number (rank 3), always CAUTION. |
| 20_kicad_pattern.py | KiCad pattern | KiCad names with x wildcards: STM32F405RGTx fits STM32F405RGT6 and the base STM32F405. |
| 30_variant_guard.py | (blocks / flags) | If suffix variants of the target have a supply, ground or NC pin in different places in the same package (TJA1051T / T/3 / T/E pin 5 = NC / VIO / EN), all non-exact suggestions for the base part are Blocked and the differing pins are shown. If only one '/'-suffixed variant is in the library (TJA1051T/3), CAUTION. |
| 40_can_caution.py | (flags) | CAN bus transceivers (function text "CAN", "CAN FD" - case-sensitive - or "CAN transceiver/bus", "controller area network"; part prefixes TJA1, TCAN, MCP25xx, SN65HVD23x, ISO1042/1044/1050, LTC2875, MAX3301x ...) and LIN transceivers (TJA102x, TLIN, MCP2003/4, ATA663x, SN65HVDA195, NCV7329, L9637 - own LIN text) are marked CAUTION. |
| 50_package_suffix_guard.py | (flags / blocks) | Decodes the package from the component's ordering suffix (TI/onsemi/ST, NXP, Microchip `-I/P`, Maxim `CPA/ESA/EUA`). Different family than the definition → CAUTION; different pin-count class (SOT-23/SC-70 vs 8+ pin) → Blocked. Unclear suffixes are ignored. |
| 55_power_pin_sanity.py | (flags) | Logic-family / cross-family / 4000 / (logic-name) prefix-suffix suggestions on DIP/SOIC/TSSOP: CAUTION if V+ is not on pin N and V- on pin N/2 (7473, 7476, 7490, CD4049/4050), naming the actual pins. |
| 60_three_pin_caution.py | (flags) | SOT-23-3, SOT-89, SOT-223, TO-92, TO-220, TO-252, TO-247: every non-exact match, and exact matches with an unknown or different manufacturer, are CAUTION. |
| 70_second_source.py | Second source | Curated pin-compatible groups (NE555/SA555/.../ICM7555, LM358/LM258/LM158/LM2904, LM324 group, LM393 group, LM339 group, LM78xx/L78xx/MC78xx/UA78xx/KA78xx). Rank 2, always CAUTION. |
| 80_already_accepted.py | (blocks / flags) | Library only: Blocked when the component already has an accepted pinout in the same package with a different supply/NC layout; CAUTION "Duplicate definition" when the accepted one has the same canonical pins. |
| 90_definition_quality.py | (flags) | Library only: CAUTION for definitions without supply or ground pins (IC packages), only NC / P1.. placeholders, repeated signal names, or pin count ≠ pin table. |

## Writing a rule

```python
RULE_ID = 'my-rule-v1'      # stored with decisions; change it when the logic changes
LABEL = 'My rule'           # Match column / rule filter
RANK = 2                    # 0 exact ... 4 none

def prepare(ctx):            # optional, once per scan
    ctx.cache['my'] = ...

def candidates(source, ctx): # optional: propose targets
    # source.device / .name / .manufacturer / .package / .project / .pinout_id
    # ctx.components {id: {...}}, ctx.exact {PART: [...]}, ctx.sources, ctx.function(id), ctx.db
    return [(component_id, 'why'), ...]

def review(row, ctx):        # optional: flag or block any candidate row
    return None or ('caution', 'text') or ('block', 'text')
```

`row` always has `rule`, `target` (component part number), `source` (device on
the definition), `component_id`, `package`, `catalog_id`, `pinout_id`,
`source_manufacturer` and `target_manufacturer`. Library rows also have
`definition_id`, `project` (the definition's pin data) and `manufacturer`
(component manufacturer). For batch-review rows get the pin data with
`_shipped_helpers.row_project(row, ctx)` (it reads `ctx.mappings`).

Results must not depend on which rows are visible: Accept rescans the selection
and refuses if anything differs. Use `rule_api.canonical_pin`, `pin_class`,
`pins`, `pin_sort_key`, `differing_pins` for pin comparisons (1A = A1, VDD = VCC,
VSS = GND, /CS = ~{CS} = CS# = nCS = CS_N; classes V+ / V- / NC / PAD / SIG).
Pin numbers are `int` when numeric and `str` otherwise ('EP', 'A1', 'TAB'), so
sort with `key=rule_api.pin_sort_key`.
