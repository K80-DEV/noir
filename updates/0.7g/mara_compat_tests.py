"""Mara's compat + behaviour probes for the NOIR 0.7g build.

    usage: mara_compat_tests.py <abs-path-to-daemon.py> <abs-scratch-dir>

Why this file exists. The auditor's harness (unit_tests.py / proc_tests.py)
proves their 16 findings. It proves NOTHING about the thing K80 actually asked
for, which is "an existing install must be able to take this release without
its operator touching anything". That is a cross-lineage question: prod reads
CAIRN_*, the audited build reads NOIR_*, prod's unit is marahome.service while
the file is cairn.py, and the Agora import posts X-Cairn-Raw. Those get no
coverage in their suite, so they get probes here or they do not get believed.

Every check prints  ID | PASS/FAIL | detail  and nothing else about secrets.
Env is read at import time in this codebase, so cases that vary the
environment run in their own subprocess. Absolute paths only: proc-style
helpers here rmtree the scratch dir and then run with cwd=scratch, so a
relative source path deletes its own source and reports a false FAIL.
"""
import sys, os, json, shutil, subprocess, importlib.util, logging, tempfile

if len(sys.argv) < 3:
    print(__doc__); sys.exit(2)
SRC = os.path.abspath(sys.argv[1])
SCRATCH = os.path.abspath(sys.argv[2])
assert os.path.isabs(SRC) and os.path.isabs(SCRATCH), "absolute paths only"
assert os.path.exists(SRC), "source does not exist: " + SRC

RESULTS = []


def check(cid, ok, detail=""):
    RESULTS.append((cid, bool(ok)))
    print("%-6s | %s | %s" % (cid, "PASS" if ok else "FAIL", str(detail)[:400]))


def guard(cid, fn):
    try:
        fn()
    except Exception as e:
        check(cid, False, "EXC %s: %s" % (type(e).__name__, e))


# ---------------------------------------------------------------- subprocess probe helper
CHILD = r'''
import importlib.util, importlib.machinery, json, logging, os, sys
logging.disable(logging.CRITICAL)
spec = importlib.util.spec_from_file_location("noir_probe", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print("PROBE_JSON" + json.dumps({
    "SERVICE_UNIT": getattr(m, "SERVICE_UNIT", None),
    "SELF_NAME": getattr(m, "SELF_NAME", None),
    "DB_PATH": str(getattr(m, "DB_PATH", "")),
    "STATE_DIR": str(getattr(m, "STATE", getattr(m, "DATA_HOME", ""))),
    "F20_ALLOW": list(getattr(m, "_F20_ALLOW", [])),
    "HAS_HDR_ANY": hasattr(m, "_hdr_any"),
    "V1_IS_MINIMAL": (m._v1_system_prompt() == m.V1_MINIMAL_PROMPT) if hasattr(m, "_v1_system_prompt") else None,
    "V1_IS_FULL": (m._v1_system_prompt() == m.SYSTEM_PROMPT) if hasattr(m, "_v1_system_prompt") else None,
    "V1_MIN_LEN": len(getattr(m, "V1_MINIMAL_PROMPT", "")),
    "SYS_LEN": len(getattr(m, "SYSTEM_PROMPT", "") or ""),
    "PORT": getattr(m, "PORT", None),
}))
'''
_child_src = os.path.join(tempfile.gettempdir(), "mara_v1_probe_child.py")
with open(_child_src, "w", encoding="utf-8") as _f:
    _f.write(CHILD)


def import_probe(extra_env):
    """Import the daemon with a specific environment and read back the globals
    that decide where data lives and what restart text gets printed."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("CAIRN_") or k.startswith("NOIR_"):
            del env[k]
    root = tempfile.mkdtemp(prefix="maraprobe-")
    keyf = os.path.join(root, "vault.key")
    with open(keyf, "wb") as f:
        f.write(os.urandom(4096))
    env["VAULT_KEY_PATH"] = keyf
    env.update({k: (v.replace("@ROOT@", root) if isinstance(v, str) else v)
                for k, v in extra_env.items()})
    p = subprocess.run([sys.executable, _child_src, SRC], env=env, cwd=root,
                       capture_output=True, text=True, timeout=180)
    out = ""
    for line in (p.stdout or "").splitlines():
        if line.startswith("PROBE_JSON"):
            out = json.loads(line[len("PROBE_JSON"):])
    shutil.rmtree(root, ignore_errors=True)
    if not out:
        raise RuntimeError("child import failed rc=%s err=%s" % (p.returncode, (p.stderr or "")[-500:]))
    out["_root"] = root
    out["_env"] = dict(extra_env)
    return out


def scratch_env(home_var, home_val, extra=None):
    """A minimal, isolated set of env for one spelling of the config."""
    d = {home_var: home_val}
    if extra:
        d.update(extra)
    return d


# ============================================================ M1 legacy prod env, unmodified
def m1():
    """A prod unit as it exists today exports CAIRN_* only. Importing the
    release build with that environment must resolve the DATA HOME to the
    CAIRN_HOME value, not fall through to a default and silently start fresh.
    This is the one failure mode that would look like a successful update."""
    r = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/legacy-home",
                                 {"CAIRN_REGISTRY": "@ROOT@/legacy-reg.db",
                                  "CAIRN_PORT": "18971"}))
    ok = "legacy-home" in r["DB_PATH"]
    check("M1", ok, "CAIRN_* only -> DB_PATH=%s (must live under CAIRN_HOME)" % r["DB_PATH"])
guard("M1", m1)

# ============================================================ M2 new NOIR_* env
def m2():
    r = import_probe(scratch_env("NOIR_HOME", "@ROOT@/noir-home",
                                 {"NOIR_REGISTRY": "@ROOT@/noir-reg.db",
                                  "NOIR_PORT": "18972"}))
    check("M2", "noir-home" in r["DB_PATH"], "NOIR_* only -> DB_PATH=%s" % r["DB_PATH"])
guard("M2", m2)

# ============================================================ M3 both spellings: documented precedence
def m3():
    """Documented rule: NOIR_* wins when both are set (the shim only fills gaps).
    A silent flip of the data home between two set names would orphan an install."""
    r = import_probe({"NOIR_HOME": "@ROOT@/wins-noir", "CAIRN_HOME": "@ROOT@/loses-cairn",
                      "NOIR_REGISTRY": "@ROOT@/r1.db", "CAIRN_REGISTRY": "@ROOT@/r2.db"})
    check("M3", "wins-noir" in r["DB_PATH"] and "loses-cairn" not in r["DB_PATH"],
          "both set -> DB_PATH=%s (NOIR_* must win)" % r["DB_PATH"])
guard("M3", m3)

# ============================================================ M4 unit-name resolution (C2)
def m4():
    """prod's file is cairn.py but the systemd unit is marahome.service, so the
    printed rollback text names a unit that does not exist unless CAIRN_UNIT is
    honoured. B5's whole value depends on this."""
    a = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {"CAIRN_UNIT": "marahome"}))
    check("M4a", a["SERVICE_UNIT"] == "marahome", "CAIRN_UNIT=marahome -> SERVICE_UNIT=%r" % a["SERVICE_UNIT"])
    b = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {"NOIR_UNIT": "noir"}))
    check("M4b", b["SERVICE_UNIT"] == "noir", "NOIR_UNIT=noir -> SERVICE_UNIT=%r" % b["SERVICE_UNIT"])
    c = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {}))
    check("M4c", c["SERVICE_UNIT"] in ("noir-vA", "cairn", "noir", os.path.splitext(os.path.basename(SRC))[0]),
          "no unit env -> derived from filename: %r (file=%s)" % (c["SERVICE_UNIT"], os.path.basename(SRC)))
guard("M4", m4)

# ============================================================ M5 header dual-spelling helper (C1)
def m5():
    r = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {}))
    if not r["HAS_HDR_ANY"]:
        check("M5", False, "no _hdr_any helper in the module"); return
    env = dict(os.environ)
    root = tempfile.mkdtemp(prefix="marahdr-")
    env["NOIR_HOME"] = os.path.join(root, "h"); env["NOIR_REGISTRY"] = os.path.join(root, "r.db")
    env["VAULT_KEY_PATH"] = os.path.join(root, "k"); open(env["VAULT_KEY_PATH"], "wb").write(os.urandom(4096))
    hdr_src = (
        "import importlib.util, logging, sys, email.message\n"
        "logging.disable(logging.CRITICAL)\n"
        "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "def H(*kv):\n"
        "    h = email.message.Message()\n"
        "    for k, v in kv:\n"
        "        h[k] = v\n"
        "    return h\n"
        "n = ('X-Noir-Raw', 'X-Cairn-Raw')\n"
        "a = m._hdr_any(H(('X-Noir-Raw', '1')), *n)\n"
        "b = m._hdr_any(H(('X-Cairn-Raw', '1')), *n)\n"
        "c = m._hdr_any(H(('x-cairn-raw', '1')), *n)\n"
        "d = m._hdr_any(H(), *n)\n"
        "e = m._hdr_any(H(('X-Cairn-Restore', '1')), 'X-Noir-Restore', 'X-Cairn-Restore')\n"
        "f = m._hdr_any(H(('X-Cairn-Import-Secrets', '1')), 'X-Noir-Import-Secrets', 'X-Cairn-Import-Secrets')\n"
        "g = m._hdr_any(H(('X-Cairn-Restore-Identity', '1')), 'X-Noir-Restore-Identity', 'X-Cairn-Restore-Identity')\n"
        "print('HDR' + repr((a, b, c, d, e, f, g)))\n"
    )
    hf = os.path.join(tempfile.gettempdir(), "mara_hdr_child.py")
    with open(hf, "w", encoding="utf-8") as _hf:
        _hf.write(hdr_src)
    p = subprocess.run([sys.executable, hf, SRC], env=env, cwd=root,
                       capture_output=True, text=True, timeout=180)
    shutil.rmtree(root, ignore_errors=True)
    got = [l for l in (p.stdout or "").splitlines() if l.startswith("HDR")]
    if not got:
        check("M5", False, "hdr probe died: " + (p.stderr or "")[-400:]); return
    a, b, c, d, e, f, g = eval(got[0][3:])
    check("M5", all([a, b, c, e, f, g]) and not d,
          "raw=%s legacy=%s legacy_lowercase=%s absent=%s restore=%s secrets=%s identity=%s"
          % (a, b, c, d, e, f, g))
guard("M5", m5)

# ============================================================ M6 call-site coverage, by source scan
def m6():
    src = open(SRC, encoding="utf-8", errors="replace").read()
    doors = {"raw import door": ["X-Noir-Raw", "X-Cairn-Raw"],
             "restore door": ["X-Noir-Restore", "X-Cairn-Restore"],
             "restore identity": ["X-Noir-Restore-Identity", "X-Cairn-Restore-Identity"],
             "import secrets": ["X-Noir-Import-Secrets", "X-Cairn-Import-Secrets"],
             "export skipped hdr": ["X-Noir-Backup-Skipped", "X-Cairn-Backup-Skipped"],
             "export vault skipped": ["X-Noir-Backup-Vault-Skipped", "X-Cairn-Backup-Vault-Skipped"]}
    missing = [k for k, pair in doors.items() if pair[0] not in src or pair[1] not in src]
    check("M6a", not missing, "both spellings present for: %s" % ("all six" if not missing else "MISSING " + str(missing)))
    check("M6b", src.count("_hdr_any(") >= 5, "_hdr_any used %d times (>=5 = the doors, not just the definition)"
          % src.count("_hdr_any("))
    allow = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {}))["F20_ALLOW"]
    check("M6c", set(allow) == {"marahome.py", "cairn.py", "noir.py"},
          "_F20_ALLOW=%s (F19: noir.py must be accepted by the release that ships as cairn.py)" % (allow,))
guard("M6", m6)

# ============================================================ M7 G9: /v1 identity containment
def m7():
    """The whole point of the G9 change: holding the /v1 token must not be a way
    to read the owner's persona and memory files."""
    dflt = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {}))
    check("M7a", dflt["V1_IS_MINIMAL"] is True and dflt["V1_IS_FULL"] is False,
          "default /v1 prompt = minimal (%d B), NOT the owner prompt (%d B)" % (dflt["V1_MIN_LEN"], dflt["SYS_LEN"]))
    full = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {"NOIR_V1_IDENTITY": "full"}))
    check("M7b", full["V1_IS_FULL"] is True, "NOIR_V1_IDENTITY=full -> owner prompt (opt-in honoured)")
    leg = import_probe(scratch_env("CAIRN_HOME", "@ROOT@/h", {"CAIRN_V1_IDENTITY": "full"}))
    check("M7c", leg["V1_IS_FULL"] is True, "CAIRN_V1_IDENTITY=full -> owner prompt (legacy spelling too)")
    src = open(SRC, encoding="utf-8", errors="replace").read()
    check("M7d", '"content": SYSTEM_PROMPT})' not in src,
          "no /v1 path inserts the owner's SYSTEM_PROMPT unconditionally any more")
guard("M7", m7)

# ============================================================ M8 prod-lineage fixes not regressed
def m8():
    """Four fixes lived only on the running prod lineage. The audit lineage never
    had them, so shipping the auditor's file alone would have silently removed
    them. Each marker is the codebase's own annotation convention."""
    src = open(SRC, encoding="utf-8", errors="replace").read()
    want = {"CTXGUARD": "mid-turn context guard",
            "NOTHINK": "no-thinking title/short call",
            "reasoning_effort": "provider no-thinking parameter",
            "SHELLDASH": "dash is not bash - tool description + chip",
            "TIMER-RESYNC": "elapsed timer baseline resync",
            "_hdr_any": "compat header reader"}
    missing = {k: v for k, v in want.items() if src.count(k) == 0}
    check("M8", not missing, "prod-lineage markers present: %s" %
          ("all" if not missing else "MISSING " + json.dumps(missing)))
    for k in want:
        print("        count %-16s %d" % (k, src.count(k)))
guard("M8", m8)

# ============================================================ M9 real boot with the legacy unit env
def m9():
    """The end-to-end form of M1: actually start the process the way
    marahome.service starts it today (CAIRN_* only) and prove /health answers
    and the scratch home is the one that got written."""
    import time, http.client
    root = tempfile.mkdtemp(prefix="maraboot-")
    home = os.path.join(root, "prod-home")
    keyf = os.path.join(root, "vault.key")
    with open(keyf, "wb") as f:
        f.write(os.urandom(4096))
    s = socket_for_free_port()
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CAIRN_") or k.startswith("NOIR_"))}
    env.update({"CAIRN_HOME": home, "CAIRN_REGISTRY": os.path.join(root, "reg.db"),
                "CAIRN_PORT": str(s), "CAIRN_HOST": "127.0.0.1",
                "CAIRN_UNIT": "marahome", "VAULT_KEY_PATH": keyf})
    log = open(os.path.join(root, "boot.log"), "wb")
    proc = None
    try:
        proc = subprocess.Popen([sys.executable, SRC], env=env, cwd=root,
                                stdout=log, stderr=log)
        health = None
        for _ in range(250):
            if proc.poll() is not None:
                break
            try:
                c = http.client.HTTPConnection("127.0.0.1", s, timeout=1)
                c.request("GET", "/health")
                r = c.getresponse()
                health = r.status
                c.close()
                if health == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        wrote_home = os.path.isdir(home) and os.listdir(home)
        try:
            c = http.client.HTTPConnection("127.0.0.1", s, timeout=2)
            c.request("GET", "/health")
            body = c.getresponse().read().decode("utf-8", "replace")[:160]
            c.close()
        except Exception as e:
            body = "health read failed: %s" % e
        check("M9", health == 200 and bool(wrote_home),
              "legacy CAIRN_* boot: /health=%s home_created=%s body=%s" % (health, bool(wrote_home), body))
        tail = open(os.path.join(root, "boot.log"), "rb").read().decode("utf-8", "replace").strip().splitlines()[-6:]
        for l in tail:
            print("        boot| " + l[:200])
    finally:
        try:
            if proc and proc.poll() is None:
                proc.terminate(); time.sleep(0.4)
                if proc.poll() is None:
                    proc.kill()
        except Exception:
            pass
        try:
            log.close()
        except Exception:
            pass
        shutil.rmtree(root, ignore_errors=True)


def socket_for_free_port():
    import socket
    so = socket.socket(); so.bind(("127.0.0.1", 0)); p = so.getsockname()[1]; so.close(); return p


guard("M9", m9)

print("SUMMARY mara-compat build: %d/%d pass" % (sum(1 for _, ok in RESULTS if ok), len(RESULTS)))
bad = [c for c, ok in RESULTS if not ok]
if bad:
    print("FAILED: " + " ".join(bad))
sys.exit(1 if bad else 0)