"""Shared JSON-lines event logger used by job.py (training) and harness.py (injection).

One event per line: {"ts": <unix epoch float>, "event": <str>, ...fields}
Append-only so it survives job respawns across the same run directory.
"""
import json
import os
import time


def log_event(path, event, **fields):
    record = {"ts": time.time(), "event": event}
    record.update(fields)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_events(path):
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
