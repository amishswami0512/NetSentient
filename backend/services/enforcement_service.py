"""Turns a computed priority into real Linux traffic shaping.

This is the only module that shells out to `tc`/`iptables`. It never
decides priority itself -- it takes a priority already produced by
priority_service.py and maps it onto one of a small number of
bandwidth tiers, backed by an HTB qdisc (tc) and packet marking
(iptables mangle).

Safe by default: Config.ENFORCEMENT_ENABLED is false unless explicitly
set, so out of the box every call here is a dry run -- it returns the
exact commands that *would* run without executing anything. This
matters because a config mistake here doesn't just misclassify a
label, it reconfigures a real network interface.
"""
import ipaddress
import logging
import subprocess
from typing import Any

from config import Config

logger = logging.getLogger(__name__)

# Ordered highest-priority-first: the first tier whose min_priority the
# score meets or exceeds wins. rate_percent/ceil_percent are shares of
# Config.ENFORCEMENT_BANDWIDTH_MBPS -- rate is the guaranteed floor,
# ceil is the most a tier may borrow when other tiers are idle (HTB's
# standard rate/ceil borrowing model).
_TIERS: list[dict[str, Any]] = [
    {"name": "critical", "min_priority": 7.5, "fwmark": 10, "rate_percent": 0.50, "ceil_percent": 0.90},
    {"name": "high", "min_priority": 5.0, "fwmark": 20, "rate_percent": 0.25, "ceil_percent": 0.60},
    {"name": "normal", "min_priority": 2.0, "fwmark": 30, "rate_percent": 0.15, "ceil_percent": 0.40},
    {"name": "low", "min_priority": 0.0, "fwmark": 40, "rate_percent": 0.05, "ceil_percent": 0.15},
]

_CHAIN = "NETSENTIENT_MARK"
_BENIGN_ERRORS = ("File exists", "Chain already exists", "RTNETLINK answers: File exists")
_VALID_PROTOCOLS = ("tcp", "udp")

# Whether the static qdisc/class/filter topology has been (re)created
# in this process. Set only after a real (non-dry-run) apply succeeds;
# reset_enforcement() clears it since that tears the qdisc down. A
# fresh process always starts False, which is correct even across a
# restart: `tc qdisc replace ... root` destroys the whole previous
# qdisc tree (and everything attached under it) before recreating it,
# so re-running base setup from scratch is always safe, never
# duplicative.
_base_applied = False


def _tier_for_priority(priority: float) -> dict[str, Any]:
    for tier in _TIERS:
        if priority >= tier["min_priority"]:
            return tier
    return _TIERS[-1]


def validate_dst_cidr(raw: str) -> str:
    """Raises ValueError on anything that isn't a real CIDR -- callers
    turn that into a 400. Also means this value can never carry
    anything a shell/argv wouldn't accept, on top of subprocess never
    using shell=True in the first place.
    """
    ipaddress.ip_network(raw, strict=False)
    return raw


def _exec(cmd: list[str], tolerate: tuple[str, ...] = ()) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if any(marker in stderr for marker in tolerate):
        return True, ""
    return False, stderr or f"exit code {proc.returncode}"


def _base_steps() -> list[tuple[list[str], list[str] | None]]:
    """The static topology: one HTB qdisc + one class + one filter per
    tier. Created at most once per process (see _base_applied) --
    these never change per-flow, so re-issuing them on every apply
    would either be wasted work (qdisc/class, which `replace` makes
    harmless) or actively wrong (the `u32` filter, which `add` would
    duplicate on every call since u32 has no natural per-mark handle
    to replace by, unlike the `fw` classifier).

    Uses `u32 match mark` rather than the `fw` classifier: `fw` needs
    the cls_fw kernel module, which isn't available on every kernel
    (confirmed missing on at least one real deployment target here);
    `u32` is effectively universal on Linux and matches the same
    fwmark just as well.
    """
    iface = Config.ENFORCEMENT_INTERFACE
    total_kbit = int(Config.ENFORCEMENT_BANDWIDTH_MBPS * 1000)

    steps: list[tuple[list[str], list[str] | None]] = [
        (["tc", "qdisc", "replace", "dev", iface, "root", "handle", "1:", "htb", "default", "40"], None),
    ]
    for t in _TIERS:
        rate = max(1, int(total_kbit * t["rate_percent"]))
        ceil = max(1, int(total_kbit * t["ceil_percent"]))
        steps.append((
            ["tc", "class", "replace", "dev", iface, "parent", "1:",
             "classid", f"1:{t['fwmark']}", "htb", "rate", f"{rate}kbit", "ceil", f"{ceil}kbit"],
            None,
        ))
        steps.append((
            ["tc", "filter", "add", "dev", iface, "parent", "1:", "protocol", "ip", "prio", "1",
             "u32", "match", "mark", str(t["fwmark"]), "0xff", "flowid", f"1:{t['fwmark']}"],
            None,
        ))
    return steps


def _mark_steps(protocol: str, port: int, tier: dict[str, Any], dst_cidr: str | None) -> list[tuple[list[str], list[str] | None]]:
    """Per-flow: ensure our chain exists and is hooked into OUTPUT
    (both idempotent via a `-C` probe run first), then mark this
    specific protocol/port/CIDR pattern. Safe to call on every apply.
    """
    steps: list[tuple[list[str], list[str] | None]] = [
        (["iptables", "-t", "mangle", "-N", _CHAIN], None),  # "-N" failure ("exists") tolerated at exec time
    ]

    jump = ["iptables", "-t", "mangle", "-A", "OUTPUT", "-j", _CHAIN]
    jump_probe = ["iptables", "-t", "mangle", "-C", "OUTPUT", "-j", _CHAIN]
    steps.append((jump, jump_probe))

    mark = ["iptables", "-t", "mangle", "-A", _CHAIN, "-p", protocol, "--dport", str(port)]
    if dst_cidr:
        mark += ["-d", dst_cidr]
    mark += ["-j", "MARK", "--set-mark", str(tier["fwmark"])]
    mark_probe = mark.copy()
    mark_probe[mark_probe.index("-A")] = "-C"
    steps.append((mark, mark_probe))

    return steps


def _describe(steps: list[tuple[list[str], list[str] | None]]) -> list[str]:
    return [" ".join(cmd) for cmd, _probe in steps]


def _execute(steps: list[tuple[list[str], list[str] | None]]) -> list[dict[str, str]]:
    errors = []
    for cmd, probe in steps:
        if probe is not None:
            ok, _ = _exec(probe)
            if ok:
                continue  # already in place -- skip the append
        ok, err = _exec(cmd, tolerate=_BENIGN_ERRORS)
        if not ok:
            errors.append({"command": " ".join(cmd), "error": err})
    return errors


def apply_flow_priority(protocol: str, port: int, priority: float, dst_cidr: str | None = None) -> dict[str, Any]:
    """Map `priority` to a bandwidth tier and (if Config.ENFORCEMENT_ENABLED)
    actually apply it via tc/iptables on Config.ENFORCEMENT_INTERFACE.
    Always returns the exact command plan, whether or not it was run --
    that's the point of a dry run being the safe default.

    A dry run always shows the full plan (base topology + this flow's
    mark rule), since nothing is actually tracked between dry-run
    calls. A real (enabled) run only re-executes the base topology
    once per process -- see _base_applied.
    """
    global _base_applied
    tier = _tier_for_priority(priority)
    base_steps = _base_steps()
    mark_steps = _mark_steps(protocol, port, tier, dst_cidr)
    dry_run = not Config.ENFORCEMENT_ENABLED

    result: dict[str, Any] = {
        "tier": tier["name"],
        "fwmark": tier["fwmark"],
        "interface": Config.ENFORCEMENT_INTERFACE,
        "dry_run": dry_run,
        "commands": _describe(base_steps if dry_run or not _base_applied else []) + _describe(mark_steps),
        "applied": False,
        "errors": [],
    }
    if dry_run:
        return result

    errors: list[dict[str, str]] = []
    if not _base_applied:
        errors += _execute(base_steps)
        if not errors:
            _base_applied = True
    errors += _execute(mark_steps)
    result["errors"] = errors
    result["applied"] = not errors
    return result


def get_status() -> dict[str, Any]:
    iface = Config.ENFORCEMENT_INTERFACE
    qdisc_ok, qdisc_out = _exec(["tc", "-s", "qdisc", "show", "dev", iface])
    class_ok, class_out = _exec(["tc", "-s", "class", "show", "dev", iface])
    mangle_ok, mangle_out = _exec(["iptables", "-t", "mangle", "-L", _CHAIN, "-n", "-v"])
    return {
        "enabled": Config.ENFORCEMENT_ENABLED,
        "interface": iface,
        "bandwidth_mbps": Config.ENFORCEMENT_BANDWIDTH_MBPS,
        "tiers": [{"name": t["name"], "min_priority": t["min_priority"], "fwmark": t["fwmark"]} for t in _TIERS],
        "qdisc": qdisc_out if qdisc_ok else None,
        "classes": class_out if class_ok else None,
        "mangle_rules": mangle_out if mangle_ok else None,
    }


def reset_enforcement() -> dict[str, Any]:
    global _base_applied
    iface = Config.ENFORCEMENT_INTERFACE
    commands = [
        ["iptables", "-t", "mangle", "-F", _CHAIN],
        ["tc", "qdisc", "del", "dev", iface, "root"],
    ]
    result: dict[str, Any] = {
        "interface": iface,
        "dry_run": not Config.ENFORCEMENT_ENABLED,
        "commands": [" ".join(c) for c in commands],
        "applied": False,
        "errors": [],
    }
    if not Config.ENFORCEMENT_ENABLED:
        return result

    tolerate = ("No such file or directory", "Cannot delete", "does not exist", "Bad rule")
    for cmd in commands:
        ok, err = _exec(cmd, tolerate=tolerate)
        if not ok:
            result["errors"].append({"command": " ".join(cmd), "error": err})
    result["applied"] = not result["errors"]
    _base_applied = False  # the qdisc del above wipes the topology -- next apply must recreate it
    return result
