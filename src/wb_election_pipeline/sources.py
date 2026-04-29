from __future__ import annotations

import base64

FORM20_URL_TEMPLATE = (
    "https://ceowestbengal.wb.gov.in/Downloads/Election/GE2021/Form20/{ac_no}_Form20.pdf"
)

VOTER_ROLL_URL_TEMPLATE = (
    "https://ceowestbengal.wb.gov.in/RollPDF/GetDraft?acId={ac_no}&key={key}"
)

VOTER_ROLL_PART_LIST_TEMPLATE = (
    "https://ceowestbengal.wb.gov.in/Roll_ps/{ac_no}"
)


def ac_numbers() -> range:
    return range(1, 295)


def form20_url(ac_no: int) -> str:
    if ac_no < 1 or ac_no > 294:
        raise ValueError(f"Assembly constituency number out of range: {ac_no}")
    return FORM20_URL_TEMPLATE.format(ac_no=ac_no)


def voter_roll_url(ac_no: int, part_no: int) -> str:
    """Return the direct download URL for a voter roll PDF (2026 final roll)."""
    if ac_no < 1 or ac_no > 294:
        raise ValueError(f"Assembly constituency number out of range: {ac_no}")
    filename = f"AC{ac_no:03d}PART{part_no:03d}.pdf"
    key = base64.b64encode(filename.encode("utf-8")).decode("ascii")
    return VOTER_ROLL_URL_TEMPLATE.format(ac_no=ac_no, key=key)


def voter_roll_part_list_url(ac_no: int) -> str:
    """Return the URL listing all parts (polling stations) for a given AC."""
    return VOTER_ROLL_PART_LIST_TEMPLATE.format(ac_no=ac_no)

