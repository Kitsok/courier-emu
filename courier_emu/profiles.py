"""Named, reproducible analog board configurations for normal operation."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from .panel import DEFAULT_BOARD_ID
from .timers import SUGGESTED_TICK_MS


ROOT = Path(__file__).resolve().parent.parent
ANALOG403_IMAGE = Path("artifacts/courier-board-21210-capture-403/courier-board.rom")
ANALOG403_SHA256 = "f1c91621fbf14aad34547056feb4425e64fcf0b38ec5d57f86c9f432ca999db6"
PROFILE_NAMES = ("analog403",)


def resolve_run_profile(args: argparse.Namespace) -> None:
    """Fill omitted board settings and validate the selected firmware.

    Explicit image runs retain their diagnostic defaults. A named profile
    binds a captured image to its board and EEPROM configuration; selecting
    another image requires an explicit-image run instead.
    """
    if args.profile:
        image = ROOT / ANALOG403_IMAGE
        if args.image is not None and Path(args.image).resolve() != image.resolve():
            raise ValueError("--profile analog403 selects its own firmware; omit IMAGE")
        if args.force_online or args.dsp_acquisition_assist:
            raise ValueError("analog403 cannot use forced online or DSP acquisition assist")
        if args.nvram_fixture not in (None, "idsdl403-lapm"):
            raise ValueError("analog403 requires the idsdl403-lapm EEPROM fixture")
        if args.board_id not in (None, "7") or args.tick_ms not in (None, 5):
            raise ValueError("analog403 requires board ID 7 and a 5 ms timer tick")
        if args.dip is not None or args.dip_preset not in (None, "default"):
            raise ValueError("analog403 requires the default DIP switch preset")
        try:
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
        except FileNotFoundError:
            raise ValueError(f"analog403 firmware is missing: {image}") from None
        if digest != ANALOG403_SHA256:
            raise ValueError(f"analog403 firmware checksum mismatch: {image}")
        args.image = str(image)
        args.with_dsp = True
        args.exchange = True
        args.board_id = "7"
        args.tick_ms = 5
        args.dip_preset = "default"
        if args.nvram is None:
            args.nvram_fixture = "idsdl403-lapm"
    elif args.image is None:
        raise ValueError("run requires IMAGE or --profile analog403")
    if args.board_id is None:
        args.board_id = str(DEFAULT_BOARD_ID)
    if args.tick_ms is None:
        args.tick_ms = SUGGESTED_TICK_MS
