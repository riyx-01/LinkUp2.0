"""Freeze/approval record that gates the confirmatory phase.

``python main.py freeze --approver "<name>"`` writes
``configs/confirmatory.approval.json`` containing hashes of the resolved
confirmatory config, the experiment matrix and the simulation source code.
``run --phase confirmatory`` refuses to start unless the record exists and all
hashes still match, so a pilot or edited config can never be mistaken for the
approved one. Changing any of them requires a new, deliberate approval.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path

from simulator.config import CONFIG_DIR, full_config_hash, load_config, validate_config

from .provenance import code_version, source_hash

APPROVAL_PATH = CONFIG_DIR / "confirmatory.approval.json"


class ApprovalError(RuntimeError):
    pass


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def current_fingerprint() -> dict:
    cfg = load_config(CONFIG_DIR / "confirmatory.json")
    validate_config(cfg)
    return {
        "confirmatory_config_sha256": full_config_hash(cfg),
        "experiments_sha256": _file_sha(CONFIG_DIR / "experiments.json"),
        "source_sha256": source_hash(),
        "code_version": code_version(),
        "seeds": cfg["seeds"],
        "alpha": cfg["statistics"]["alpha"],
        "h2_noninferiority_margin_pp": cfg["statistics"]["h2_noninferiority_margin_pp"],
        "planned_repetitions": cfg["statistics"]["planned_repetitions"],
        "h4_model": cfg["statistics"]["h4_model"],
        "zero_variance_rule": cfg["statistics"].get("zero_variance_rule"),
        "meaningful_target_effects_pp": cfg["statistics"].get("meaningful_target_effects_pp"),
    }


def freeze(approver: str, note: str = "", force: bool = False) -> dict:
    if not approver.strip():
        raise ApprovalError("An approver name is required.")
    if APPROVAL_PATH.exists() and not force:
        raise ApprovalError(f"{APPROVAL_PATH.name} already exists. Use --force only for a deliberate re-approval.")
    fp = current_fingerprint()
    if len(fp["seeds"]) != fp["planned_repetitions"]:
        raise ApprovalError("Number of confirmatory seeds differs from planned_repetitions.")
    targets = fp.get("meaningful_target_effects_pp") or {}
    missing = [k for k in ("H1", "H5") if targets.get(k) is None]
    if missing:
        raise ApprovalError(f"Meaningful target effects for {missing} are not set. Agree them with the mentor, "
                            "write them in configs/confirmatory.json -> statistics.meaningful_target_effects_pp, "
                            "then freeze again.")
    if APPROVAL_PATH.exists():  # keep every previous approval for the audit trail
        history = APPROVAL_PATH.with_name("confirmatory.approval_history.jsonl")
        with open(history, "a", encoding="utf-8") as fh:
            fh.write(APPROVAL_PATH.read_text(encoding="utf-8").replace("\n", " ") + "\n")
    record = {"approved_by": approver.strip(), "approved_at_utc":
              _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "note": note, **fp}
    APPROVAL_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def verify_approval() -> dict:
    if not APPROVAL_PATH.exists():
        raise ApprovalError(
            "The confirmatory configuration has not been frozen/approved. Review the pilot report, "
            "then run: python main.py freeze --approver \"<researcher name>\"")
    record = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    fp = current_fingerprint()
    mismatched = [k for k in ("confirmatory_config_sha256", "experiments_sha256", "source_sha256")
                  if record.get(k) != fp[k]]
    if mismatched:
        raise ApprovalError(f"Approval record does not match the current {', '.join(mismatched)}. "
                            "The config, experiment matrix or code changed after approval.")
    return record
