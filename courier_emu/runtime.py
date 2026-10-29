"""Configuration-driven analog Courier launcher, shared by source and service."""
from __future__ import annotations

import argparse
import configparser
import ipaddress
import os
from pathlib import Path
import sys

from . import cli, dsp, x86_native
from .nvram import CourierNvram


KEYS = {
    "modem": {"profile", "tty", "nvram"},
    "sip": {"server", "target", "username", "password_env", "bind", "advertise",
            "port", "rtp_port", "codec"},
}


def read_config(path: Path) -> tuple[list[str], Path]:
    config = configparser.ConfigParser(interpolation=None)
    with path.open() as source:
        config.read_file(source)
    if config.defaults():
        raise ValueError("configuration must not contain DEFAULT values")
    if not set(KEYS) <= set(config.sections()) or set(config.sections()) - set(KEYS) - {"logging"}:
        raise ValueError("configuration requires [modem] and [sip], with optional [logging]")
    for section, keys in KEYS.items():
        if set(config[section]) != keys:
            raise ValueError(f"[{section}] requires these keys: {', '.join(sorted(keys))}")
    modem, sip = config["modem"], config["sip"]
    if modem["profile"] != "analog403":
        raise ValueError("only the analog403 profile is supported")
    for field in ("bind", "advertise"):
        ipaddress.IPv4Address(sip[field])
    for field in ("port", "rtp_port"):
        if not 1 <= sip.getint(field) <= 65535:
            raise ValueError(f"[sip] {field} must be between 1 and 65535")
    if sip["codec"] not in ("pcmu", "pcma"):
        raise ValueError("codec must be pcmu or pcma")
    if not sip["server"].strip():
        raise ValueError("SIP server must not be empty")
    if "{number}" not in sip["target"]:
        raise ValueError("SIP target must contain {number}")
    paths = {}
    for field in ("tty", "nvram"):
        if not modem[field].strip():
            raise ValueError(f"[modem] {field} must not be empty")
        value = Path(modem[field]).expanduser()
        paths[field] = value if value.is_absolute() else path.parent / value
    if paths["tty"].absolute() == paths["nvram"].absolute():
        raise ValueError("tty and nvram must be different paths")
    arguments = ["run", "--profile", modem["profile"], "--serial-pty",
                 "--serial-link", str(paths["tty"]), "--nvram", str(paths["nvram"])]
    for key, flag in (("server", "--sip-server"), ("target", "--sip-target"),
                      ("username", "--sip-username"), ("password_env", "--sip-password-env"),
                      ("bind", "--sip-bind"), ("advertise", "--sip-advertise"),
                      ("port", "--sip-local-port"), ("rtp_port", "--rtp-local-port"),
                      ("codec", "--sip-codec")):
        arguments.extend((flag, sip[key]))
    logging = config["logging"] if config.has_section("logging") else {}
    if set(logging) - {"level", "report"}:
        raise ValueError("[logging] accepts only level and report")
    level = logging.get("level", "normal")
    if level not in ("quiet", "normal", "debug"):
        raise ValueError("logging level must be quiet, normal or debug")
    arguments.extend(("--log-level", level))
    if logging.get("report", "").strip():
        report = Path(logging["report"]).expanduser()
        if not report.is_absolute():
            report = path.parent / report
        arguments.extend(("--diagnostic-report", str(report)))
    return arguments, paths["nvram"]


def seed_nvram(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(CourierNvram.idsl403_lapm_fixture().data)
    except FileExistsError:
        CourierNvram.load(path)  # Validate an existing file; never overwrite it.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        arguments, nvram = read_config(args.config.absolute())
        # Resolve and verify firmware without booting the emulator.
        cli._worker_command(cli.build_parser().parse_args(arguments))
        os.environ["COURIER_EMU_NO_BUILD"] = "1"
        x86_native.build_library()
        dsp.build_library()
        if args.check_config:
            if nvram.exists():
                CourierNvram.load(nvram)
            print("Analog Courier configuration and native build: OK")
            return 0
        seed_nvram(nvram)
        return cli.main(arguments)
    except (OSError, ValueError, RuntimeError, configparser.Error) as exc:
        print(f"courier-emu: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
