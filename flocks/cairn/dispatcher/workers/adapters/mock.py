from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import tempfile

from flocks.cairn.dispatcher.config import WorkerConfig, resolve_mock_behavior
from flocks.cairn.dispatcher.workers.base import DirectExecuteResult, DriverResult, SeedSessionDriver

LOG = logging.getLogger(__name__)

_SCRIPT = """
import base64,json,random,sys,time

def _dbg(*a):
    print("[mock]",*a,flush=True,file=sys.stderr)

_dbg("argv count", len(sys.argv))
for _i in range(min(len(sys.argv), 4)):
    _v = sys.argv[_i]
    _dbg(f"argv[{_i}] len={len(_v)} first={repr(_v[:80])} last={repr(_v[-40:])}")

try:
    raw1 = sys.argv[1]
    dec1 = base64.b64decode(raw1)
    cfg = json.loads(dec1)
except Exception as exc:
    print(f"mock setup failed at cfg decoding: {exc}", file=sys.stderr, flush=True)
    _dbg("cfg decode failed", "raw_len="+str(len(raw1)), "exc="+str(exc))
    raise SystemExit(1)

try:
    raw2 = sys.argv[2]
    dec2 = base64.b64decode(raw2)
    prompt = json.loads(dec2)
except Exception as exc:
    print(f"mock setup failed at prompt decoding: {exc}", file=sys.stderr, flush=True)
    _dbg("prompt decode failed", "raw_len="+str(len(raw2)), "exc="+str(exc))
    raise SystemExit(1)

phase=prompt["phase"]
_dbg("phase", phase, "cfg keys", list(cfg.keys()))
phase_cfg=cfg[phase]
delay=phase_cfg["delay"]
time.sleep(random.uniform(delay["min"],delay["max"]))

weights=dict(phase_cfg["outcomes"])
if phase=="reason":
    if not prompt.get("open_intents"):
        weights.pop("noop",None)
    if not prompt.get("fact_ids"):
        weights.pop("complete",None)
        weights.pop("intent",None)
choices=[(name,weight) for name,weight in weights.items() if weight>0]
if not choices:
    print(f"mock {phase} has no legal outcomes for prompt context", file=sys.stderr)
    raise SystemExit(2)

def _rule_matches(rule, prompt):
    fact_ids = prompt.get("fact_ids") or []
    open_intents = prompt.get("open_intents") or []
    if "fact_ids_gte" in rule and len(fact_ids) < rule["fact_ids_gte"]:
        return False
    if "fact_ids_lte" in rule and len(fact_ids) > rule["fact_ids_lte"]:
        return False
    if "open_intents_empty" in rule and (len(open_intents) == 0) != rule["open_intents_empty"]:
        return False
    return True

rules = phase_cfg.get("rules") or []
forced = None
for rule in rules:
    if _rule_matches(rule, prompt):
        forced = rule["force"]
        break

if forced is not None:
    outcome = forced
else:
    pick=random.uniform(0,sum(weight for _,weight in choices))
    total=0
    outcome=choices[-1][0]
    for name,weight in choices:
        total+=weight
        if pick<=total:
            outcome=name
            break

if phase=="healthcheck":
    raise SystemExit(0 if outcome=="ok" else 1)
if outcome=="command_fail":
    print(f"mock {phase} command failed", file=sys.stderr)
    raise SystemExit(1)
if outcome=="invalid_json":
    print("{invalid json")
    raise SystemExit(0)
if phase=="reason":
    fact_ids=prompt.get("fact_ids") or []
    max_i=prompt.get("max_intents",3)
    from_ids=[random.choice(fact_ids)] if fact_ids else []
    if outcome=="complete":
        print(json.dumps({"accepted":True,"data":{"complete":{"from":from_ids,"description":f"mock complete from {from_ids[0]}"}}}, ensure_ascii=False))
    elif outcome=="intent":
        count=random.randint(1,max(1,max_i))
        intents=[]
        for idx in range(count):
            fi=[random.choice(fact_ids)] if fact_ids else []
            intents.append({"from":fi,"description":f"mock intent {idx+1} from {fi[0] if fi else 'none'}"})
        print(json.dumps({"accepted":True,"data":{"intents":intents}}, ensure_ascii=False))
    elif outcome=="noop":
        print(json.dumps({"accepted":True,"data":{}}, ensure_ascii=False))
    elif outcome=="rejected":
        print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
    else:
        print(json.dumps({"accepted":True,"data":{"complete":{"description":"mock invalid payload"}}}, ensure_ascii=False))
    raise SystemExit(0)

if phase=="bootstrap":
    if outcome=="complete":
        print(json.dumps({"accepted":True,"data":{"fact":{"description":"mock fact for bootstrap"},"complete":{"description":"mock bootstrap complete from fact"}}}, ensure_ascii=False))
    elif outcome=="fact":
        print(json.dumps({"accepted":True,"data":{"fact":{"description":"mock fact-only bootstrap result"}}}, ensure_ascii=False))
    elif outcome=="rejected":
        print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
    else:
        print(json.dumps({"accepted":True,"data":{"fact":{"description":"mock invalid payload"}}}, ensure_ascii=False))
    raise SystemExit(0)

if phase=="bootstrap_conclude":
    if outcome=="fact":
        print(json.dumps({"accepted":True,"data":{"fact":{"description":"mock fact for bootstrap_conclude"}}}, ensure_ascii=False))
    elif outcome=="rejected":
        print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
    else:
        print(json.dumps({"accepted":True,"data":{"complete":{"description":"mock invalid payload"}}}, ensure_ascii=False))
    raise SystemExit(0)

if outcome=="fact":
    label = prompt.get("intent_id") or phase
    print(json.dumps({"accepted":True,"data":{"description":f"mock fact for {label}"}} , ensure_ascii=False))
elif outcome=="rejected":
    print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
else:
    print(json.dumps({"accepted":True,"data":{}}, ensure_ascii=False))
""".strip()


class MockDriver(SeedSessionDriver):
    type_name = "mock"

    @staticmethod
    def _argv(worker: WorkerConfig, prompt: str) -> list[str]:
        behavior = resolve_mock_behavior(worker.name, worker.env)
        return ["python3", "-c", _SCRIPT, json.dumps(behavior, ensure_ascii=False), prompt]

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self._argv(worker, '{"phase":"healthcheck"}')

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        return DriverResult(argv=self._argv(worker, prompt), session=session)

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        return self._argv(worker, prompt)

    def can_execute_direct(self) -> bool:
        return True

    def execute_direct(
        self,
        worker: WorkerConfig,
        prompt: str,
        *,
        phase: str,
        timeout_seconds: float = 300,
        cancellation: object | None = None,
        session_id: str | None = None,
    ) -> DirectExecuteResult:
        behavior = resolve_mock_behavior(worker.name, worker.env)
        behavior_json = json.dumps(behavior, ensure_ascii=False)
        behavior_b64 = base64.b64encode(behavior_json.encode("utf-8")).decode("ascii")
        prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")

        LOG.warning("mock execute_direct worker=%s phase=%s behavior_json_len=%s prompt_len=%s", worker.name, phase, len(behavior_json), len(prompt))
        LOG.warning("mock execute_direct b64 behavior_b64_len=%s prompt_b64_len=%s behavior_b64_preview=%s", len(behavior_b64), len(prompt_b64), behavior_b64[:60])

        fd, script_path = tempfile.mkstemp(suffix=".py", prefix="mock_")
        try:
            os.write(fd, _SCRIPT.encode("utf-8"))
            os.close(fd)

            argv = [sys.executable, script_path, behavior_b64, prompt_b64]
            LOG.warning("mock execute_direct argv=%s", [sys.executable, script_path, f"<behavior_b64:{len(behavior_b64)}>", f"<prompt_b64:{len(prompt_b64)}>"])
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                if result.returncode != 0:
                    LOG.warning("mock execute_direct stderr worker=%s phase=%s code=%s stderr=%s", worker.name, phase, result.returncode, result.stderr[:3000])
                else:
                    LOG.warning("mock execute_direct ok worker=%s phase=%s stdout_len=%s", worker.name, phase, len(result.stdout))
                return DirectExecuteResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    returncode=result.returncode,
                )
            except subprocess.TimeoutExpired as e:
                return DirectExecuteResult(
                    stdout=e.stdout or "",
                    stderr=e.stderr or "",
                    returncode=-1,
                    timed_out=True,
                )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass