"""CAN bus transceivers: suffixes change pin 5 and pin 8 (NC / VIO / EN / STB / S),
and a wrong pinout can damage the bus or the ECU. Every CAN transceiver
suggestion - including exact names - starts unchecked and is listed in the
Caution queue. Confirm the full part number and package marking before accepting.

LIN transceivers (TJA1021, TLIN1029, MCP2003, ATA6631...) get their own caution:
their pin 1/7 (RXD / INH / WAKE / EN) vary between families.

The function text is matched case-sensitively for the abbreviation (CAN, CAN FD,
LIN) so ordinary English ("can drive 2 kOhm", "linear") does not trigger it.
"""
import re

RULE_ID = 'can-caution-v1'
LABEL = 'CAN caution'
RANK = 3

CAN_TEXT = ('CAN transceiver: pins 5/8 differ between suffix variants. '
            'Check the full part number and marking against this diagram.')
LIN_TEXT = ('LIN transceiver: INH / WAKE / EN / VBAT pins differ between families and suffixes. '
            'Check the full part number and marking against this diagram.')

FUNCTION = re.compile(r'\bCAN\b(?:[- ]?FD)?')                     # case-sensitive abbreviation
FUNCTION_PHRASE = re.compile(r'\bCAN[- ]?(?:FD[- ]?)?(?:transceiver|bus)\b|controller area network', re.I)
LIN_FUNCTION = re.compile(r'\bLIN\b')
LIN_PHRASE = re.compile(r'\bLIN[- ]?(?:transceiver|bus)\b|local interconnect network', re.I)
PART = re.compile(r'^(?:TJA1\d{3}|TJF1\d{3}|TCAN\d|MCP25(?:5|6)\d|MCP2542|SN65HVD(?:23|25|10)\d|SN65HVDA(?:54|10)|'
                  r'TLE(?:6250|6251|7250|925\d)|ATA65\d\d|L9616|UJA1\d{3}|NCV734\d|AMIS-?4\d|MAX(?:3051|1305\d|3301\d)|'
                  r'ISO10(?:4\d|50)|LTC2875|ADM305\d|IFX1050|PCA82C25\d|82C25\d|SIT10\d\d)')
LIN_PART = re.compile(r'^(?:TJA102\d|TJA1027|TLIN\d|MCP200[34]|ATA663\d|SN65HVDA195|NCV7329|L9637|TLE7259|TLE726\d)')


def review(row, ctx):
    part = re.sub(r'[^0-9A-Z-]', '', (row['target'] or '').upper())
    if LIN_PART.match(part):
        return ('caution', LIN_TEXT)
    if PART.match(part):
        return ('caution', CAN_TEXT)
    text = ctx.function(row['component_id'])
    if FUNCTION.search(text) or FUNCTION_PHRASE.search(text):
        return ('caution', CAN_TEXT)
    if LIN_FUNCTION.search(text) or LIN_PHRASE.search(text):
        return ('caution', LIN_TEXT)
    return None
