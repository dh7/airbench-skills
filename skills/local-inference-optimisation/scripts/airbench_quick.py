#!/usr/bin/env python3
"""airbench quick test from an orchestrating agent. Standard library only.

  register --name NAME [--source SRC]     get a test key (stored, never printed)
  start [--setup FILE] [--name N] --out DIR   start a quick test; writes DIR/instructions.md
  score --out DIR [--wait] [--ledger FILE]    read the score; appends a ledger line

The quick test must be solved by a harness running the LOCAL model, never by you:
hand DIR/instructions.md verbatim to that harness.
"""
import argparse
import hashlib
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("AIRBENCH_URL", "https://airbench.ai").rstrip("/")
KEY_FILE = os.path.expanduser(os.environ.get("AIRBENCH_KEY_FILE", "~/.config/airbench/test-key"))
UA = "airbench-skill-local-inference-optimisation/1"


def call(method, path, body=None, key=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        payload.setdefault("retry_after", e.headers.get("retry-after"))
        return e.code, payload


def leading_zero_bits(hex_digest):
    bits = 0
    for ch in hex_digest:
        v = int(ch, 16)
        if v == 0:
            bits += 4
            continue
        return bits + (4 - v.bit_length())
    return bits


def solve(nonce, difficulty):
    for i in itertools.count():
        answer = str(i)
        if leading_zero_bits(hashlib.sha256((nonce + answer).encode()).hexdigest()) >= difficulty:
            return answer


def read_key():
    try:
        with open(KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        sys.exit(f"no test key at {KEY_FILE}: run `register` first")


def die(status, payload):
    sys.exit(f"HTTP {status}: {json.dumps(payload)}")


def cmd_register(a):
    if os.path.exists(KEY_FILE) and not a.force:
        print(f"a test key already exists at {KEY_FILE} (use --force to replace it)")
        return
    s, ch = call("GET", "/api/agents/register/challenge")
    if s != 200:
        die(s, ch)
    answer = solve(ch["nonce"], ch["difficulty"])
    body = {"name": a.name, "pow": {"nonce": ch["nonce"], "answer": answer}}
    if a.source:
        body["source"] = a.source
    s, r = call("POST", "/api/agents/register", body)
    if s != 201:
        die(s, r)
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(r["testKey"] + "\n")
    print(f"registered '{a.name}'; key saved to {KEY_FILE} (mode 600), expires {r.get('expiresAt')}")


def cmd_start(a):
    body = {"kind": "quick"}
    if a.setup:
        with open(a.setup) as f:
            body.update(json.load(f))  # may hold "agent", "setup", "agentConfig"
    if a.name:
        body.setdefault("agent", {})["name"] = a.name
    body["kind"] = "quick"
    s, r = call("POST", "/api/checkups", body, key=read_key())
    if s not in (200, 201):
        die(s, r)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "instructions.md"), "w") as f:
        f.write(r["instructions"])
    meta = {
        "checkupId": r["checkupId"],
        "agent": (body.get("agent") or {}).get("name"),
        "config": ((body.get("agent") or {}).get("meta") or {}).get("config"),
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(os.path.join(a.out, "checkup.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"quick test started: checkup {r['checkupId']}. The clock is running (1 hour).")
    print(f"Hand {os.path.join(a.out, 'instructions.md')} verbatim to the harness running the LOCAL model.")


def cmd_score(a):
    with open(os.path.join(a.out, "checkup.json")) as f:
        meta = json.load(f)
    key = read_key()
    while True:
        s, r = call("GET", f"/api/checkups/{meta['checkupId']}/score", key=key)
        if s == 409 and a.wait:
            time.sleep(30)
            continue
        break
    if s != 200:
        die(s, r)
    line = {"kind": "airbench_quick", **{k: meta.get(k) for k in ("checkupId", "agent", "config")}, **r}
    with open(a.ledger, "a") as f:
        f.write(json.dumps(line) + "\n")
    print(f"passed {r['passed']}/{r['total']} in {r['wallTimeMs'] / 1000:.0f}s  (logged to {a.ledger})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--name", required=True, help="3-40 chars, e.g. the model + quant")
    r.add_argument("--source", default="inference-optimisation", help="where you found airbench")
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_register)
    s = sub.add_parser("start")
    s.add_argument("--setup", help="JSON file with agent / setup / agentConfig")
    s.add_argument("--name", help="agent name for this run (overrides the file)")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_start)
    c = sub.add_parser("score")
    c.add_argument("--out", required=True)
    c.add_argument("--wait", action="store_true", help="poll until the test is over")
    c.add_argument("--ledger", default="ledger.jsonl")
    c.set_defaults(fn=cmd_score)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
