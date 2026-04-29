from __future__ import annotations

from pathlib import Path
import ssl
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.poolmanager import PoolManager
from urllib3.util.ssl_ import create_urllib3_context
import urllib3

import re

from .sources import ac_numbers, form20_url, voter_roll_url, voter_roll_part_list_url


class LegacySslAdapter(HTTPAdapter):
    """Adapter for legacy government servers that require unsafe renegotiation."""

    def __init__(self, verify_ssl: bool = True, *args: object, **kwargs: object) -> None:
        self.verify_ssl = verify_ssl
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: object) -> None:
        context = create_urllib3_context()
        legacy_option = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        context.options |= legacy_option
        if not self.verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=context,
            **pool_kwargs,
        )


def make_session(legacy_ssl: bool = True, verify_ssl: bool = True) -> requests.Session:
    session = requests.Session()
    if legacy_ssl:
        session.mount("https://ceowestbengal.wb.gov.in", LegacySslAdapter(verify_ssl=verify_ssl))
    return session


def download_form20_pdfs(
    out_dir: Path,
    acs: Iterable[int] | None = None,
    overwrite: bool = False,
    timeout: int = 45,
    legacy_ssl: bool = True,
    verify_ssl: bool = True,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    session = make_session(legacy_ssl=legacy_ssl, verify_ssl=verify_ssl)
    if not verify_ssl:
        urllib3.disable_warnings(InsecureRequestWarning)
    for ac_no in acs or ac_numbers():
        target = out_dir / f"{ac_no}_Form20.pdf"
        if target.exists() and not overwrite:
            saved.append(target)
            continue

        response = session.get(form20_url(ac_no), timeout=timeout, verify=verify_ssl)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
            raise ValueError(f"AC {ac_no} did not return a PDF: {content_type}")
        target.write_bytes(response.content)
        saved.append(target)
    return saved


def get_voter_roll_parts(
    ac_no: int,
    session: requests.Session | None = None,
    timeout: int = 30,
    verify_ssl: bool = False,
) -> list[tuple[int, str]]:
    """Scrape the list of (part_no, booth_name) for a given AC from CEO WB."""
    if session is None:
        session = make_session(legacy_ssl=True, verify_ssl=verify_ssl)
    url = voter_roll_part_list_url(ac_no)
    response = session.get(url, timeout=timeout, verify=verify_ssl)
    response.raise_for_status()
    html = response.text

    # Each row: <td>{part_no}</td><td>{booth_name}</td>
    rows = re.findall(
        r"<tr>\s*<td>(\d+)</td>\s*<td>([^<]+)</td>",
        html,
        re.S,
    )
    return [(int(part), name.strip()) for part, name in rows]


def download_voter_roll_pdfs(
    out_dir: Path,
    acs: Iterable[int] | None = None,
    overwrite: bool = False,
    timeout: int = 60,
    verify_ssl: bool = False,
) -> list[Path]:
    """Download per-part voter roll PDFs for given ACs from CEO West Bengal (2026 final roll).

    Files are saved as ``{out_dir}/ac{ac_no:03d}/AC{ac_no:03d}PART{part_no:03d}.pdf``.
    Returns paths of all successfully downloaded PDFs.
    """
    session = make_session(legacy_ssl=True, verify_ssl=verify_ssl)
    if not verify_ssl:
        urllib3.disable_warnings(InsecureRequestWarning)

    saved: list[Path] = []
    for ac_no in acs or range(1, 295):
        ac_dir = out_dir / f"ac{ac_no:03d}"
        ac_dir.mkdir(parents=True, exist_ok=True)

        parts = get_voter_roll_parts(ac_no, session=session, timeout=timeout, verify_ssl=verify_ssl)
        if not parts:
            continue

        for part_no, _booth_name in parts:
            target = ac_dir / f"AC{ac_no:03d}PART{part_no:03d}.pdf"
            if target.exists() and not overwrite:
                saved.append(target)
                continue

            url = voter_roll_url(ac_no, part_no)
            response = session.get(url, timeout=timeout, verify=verify_ssl)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
                continue
            target.write_bytes(response.content)
            saved.append(target)

    return saved
