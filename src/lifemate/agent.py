"""Shared session runner. Jaz owns iteration; SDK alone owns app state."""

import copy
import json
import os
import time

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import jaz
from jaz.hooks import Hook
from jaz.llm import BaseLLM, LLMResponse, ModelInfo, RetryPolicy
from jaz.protocol import BaseProtocol
from jaz.repl import BaseREPL, Continue, Return

from .config import Budget, ContextLimit, TokenLimit
from .store import RecoveryRequired, fingerprint
from .submission import submission_row


def observe(state, trace, event, **data):
    try:
        trace.write(event, **data)
    except OSError as exc:
        state["trace_error"] = f"{event}: {type(exc).__name__}: {exc}"
        raise OSError("Trace write failed at " + state["trace_error"]) from exc


def emit(state, trace, event, **data):
    data["active_seconds"] = state["elapsed_base"] + time.monotonic() - state["started"]
    state["events"].append({"event": event, **data})
    if state.get("store"):
        try:
            state["store"].append(event, **data)
        except OSError as exc:
            raise RecoveryRequired(f"Journal write failed at {event}: {exc}") from exc
    observe(state, trace, event, **data)


def context():
    return {"pairs": [], "messages": [], "query_messages": [], "pending": None,
            "resume_pairs": [], "elapsed_base": 0, "started": time.monotonic(),
            "store": None, "run_id": "session", "events": [], "trace_error": None}


class LocalBackend(BaseLLM):
    def __init__(self, model, tools, deadline, trace, state=None, budget=None):
        super().__init__(retry_policy=RetryPolicy(max_retries=0))
        self.model, self.tools = model, tools
        self.deadline, self.trace = deadline, trace
        self.state = state if state is not None else context()
        self.budget = budget or Budget()
        self.calls = 0

    @property
    def model_info(self):
        return ModelInfo(name="local-backend", max_input_tokens=self.budget.context_tokens)

    def complete(self, messages):
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Session deadline reached before inference")
        if self.budget.output_tokens <= 0:
            raise TokenLimit("Output token budget is zero")
        self.calls += 1
        self.state["query_messages"] = copy.deepcopy(messages)
        emit(self.state, self.trace, "model_input", step=self.calls, messages=messages)
        started = time.monotonic()
        try:
            response = self.model.generate(
                messages, self.tools, deadline=self.deadline,
                max_context_tokens=self.budget.context_tokens,
                max_new_tokens=self.budget.output_tokens,
            )
        except (Exception, KeyboardInterrupt) as exc:
            emit(self.state, self.trace, "model_error", step=self.calls,
                 error=f"{type(exc).__name__}: {exc}",
                 backend_wall_seconds=time.monotonic() - started)
            raise
        self.state["pending"] = response
        emit(self.state, self.trace, "model", step=self.calls, **response,
             backend_wall_seconds=time.monotonic() - started)
        if response.get("timed_out"):
            raise TimeoutError("Backend reached session deadline")
        return LLMResponse(content=response["assistant_text"],
            prompt_tokens=response.get("input_tokens"),
            completion_tokens=response.get("output_tokens"), raw_response=response)


class ToolProtocol(BaseProtocol):
    def __init__(self, messages):
        self.messages = messages

    @property
    def response_format_description(self):
        return "Use supplied tools in the backend's native representation."

    def render_initial_message_list(self, inputs, scope, repl, **kwargs):
        return copy.deepcopy(self.messages)

    def parse(self, llm_response):
        return json.dumps(llm_response.raw_response, ensure_ascii=False)

    def render_observation(self, exec_result):
        return json.loads(exec_result.output)


class ToolRuntime(BaseREPL[dict]):
    def __init__(self, env, deadline, trace, state=None):
        self.env, self.deadline, self.trace = env, deadline, trace
        self.state = state if state is not None else context()

    @property
    def description(self):
        return "Execute only calls through organizer ToolEnv."

    @property
    def repl_history_description(self):
        return None

    def initialize(self, inputs, subinvoke, session_id="", repl_history_withheld=False):
        return {}

    def get_namespace(self, state):
        return state

    def add_to_namespace(self, state, entries):
        state.update(entries)

    def drop_from_namespace(self, state, names, allow_missing=()):
        for name in names:
            if name in state:
                del state[name]
            elif name not in allow_missing:
                raise KeyError(name)

    def update_repl_history(self, state, llm_response, exec_result):
        pass  # The journal/trace already captures the actual interaction.

    def observation(self, packet, messages):
        next_messages = self.state["query_messages"] + [
            {"role": "assistant", "content": packet["assistant_text"]}
        ] + messages
        self.state["messages"] = next_messages
        self.state["pending"] = None
        self.state["resume_pairs"] = []
        emit(self.state, self.trace, "checkpoint", messages=next_messages)
        return Continue(json.dumps(messages, ensure_ascii=False))

    def exec(self, namespace, src, code_id):
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Session deadline reached before tool execution")
        packet = json.loads(src)
        if packet.get("hit_token_limit"):
            return Return({"status": "budget_exhausted", "reason": "token_limit", "final_text": None})
        if packet.get("parse_error"):
            return self.observation(packet, [{"role": "user",
                "content": "Lỗi parse tool call: " + packet["parse_error"] + ". Hãy gửi lại call đúng format."}])
        calls = packet["tool_calls"]
        if not calls:
            return Return({"status": "completed", "reason": "final_answer", "final_text": packet["content"]})
        done = self.state["resume_pairs"]
        observations = [{"role": "tool", "tool_call_id": p["call_id"],
                         "content": json.dumps(p["result"], ensure_ascii=False)} for p in done]
        for number, call in enumerate(calls):
            if number < len(done):
                if done[number]["call"] != call:
                    raise RecoveryRequired("Saved response no longer matches committed calls")
                if done[number]["result"].get("waiting_for_user") and done[number]["result"].get("ok"):
                    return Return({"status": "waiting_for_user", "reason": "missing_information", "final_text": None})
                continue
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Session deadline reached before next tool")
            call_id = f"{self.state['run_id']}/latest/{len(self.state['pairs'])}"
            emit(self.state, self.trace, "tool_intent", call_id=call_id, call=call)
            started = time.monotonic()
            result = self.env.call(call["name"], call["arguments"])
            seconds = time.monotonic() - started
            pair = {"call_id": call_id, "call": call, "result": result, "seconds": seconds}
            # Preserve returned evidence even if hash/journal/observer I/O fails next.
            self.state["pairs"].append(pair)
            if self.state.get("store"):
                pair["state_hash"] = self.env.get_state_hash()
            emit(self.state, self.trace, "tool", **pair)
            observations.append({"role": "tool", "tool_call_id": call_id,
                                 "content": json.dumps(result, ensure_ascii=False)})
            if result.get("ok") and result.get("waiting_for_user"):
                return Return({"status": "waiting_for_user", "reason": "missing_information", "final_text": None})
        return self.observation(packet, observations)


class JazTrace(Hook):
    def __init__(self, trace, state=None):
        self.trace = trace
        self.state = state if state is not None else context()

    def on_any(self, event):
        observe(self.state, self.trace, "jaz", name=type(event).__name__, iteration=getattr(event, "iteration", None))
        return []


def restore(state, events, env, trace):
    state["events"] = list(events)
    intents = {}
    last_kind = None
    for event in events[1:]:
        kind = event["event"]
        if kind == "model_input":
            state["query_messages"], state["pending"] = event["messages"], None
            state["messages"] = event["messages"]
            state["resume_pairs"] = []
            last_kind = "inflight_model"
        elif kind == "model":
            state["pending"] = {k: v for k, v in event.items()
                                if k not in ("event", "active_seconds", "backend_wall_seconds", "step")}
            last_kind = "response"
        elif kind == "tool_intent":
            intents[event["call_id"]] = event
        elif kind == "tool":
            if event["call_id"] not in intents:
                raise RecoveryRequired("Tool result has no matching intent")
            intents.pop(event["call_id"])
            state["pairs"].append({k: v for k, v in event.items() if k not in ("event", "active_seconds")})
            state["resume_pairs"].append(state["pairs"][-1])
        elif kind == "checkpoint":
            state["messages"], state["pending"] = event["messages"], None
            state["resume_pairs"] = []
            last_kind = "checkpoint"
        elif kind == "pause":
            last_kind = "known_pause"
        state["elapsed_base"] = event.get("active_seconds", state["elapsed_base"])
    if intents:
        raise RecoveryRequired("Tool intent without committed result; execution is ambiguous")
    if last_kind == "inflight_model":
        raise RecoveryRequired("Process died during inference; consumed time/output is unaccounted")
    for pair in state["pairs"]:
        result = env.call(pair["call"]["name"], pair["call"]["arguments"])
        if result != pair["result"] or env.get_state_hash() != pair["state_hash"]:
            raise RecoveryRequired("Ordered SDK replay differs from committed result/hash")
    observe(state, trace, "recovery", committed_calls=len(state["pairs"]), source="journal_ordered_replay")


def run_session(prepared, backend, env_factory, trace, *, store=None, budget=None,
                backend_identity, resume=False):
    budget = budget or Budget()
    identity = backend_identity
    signature = fingerprint({"input": {k: v for k, v in prepared.items() if k != "timings"},
                             "budget": budget.to_dict(), "backend": identity})
    sid = prepared["id"]
    state = context()
    state.update(messages=prepared["messages"], store=store, run_id=prepared["run_id"])
    result = None
    env = None
    environment_seconds = None
    recovery_seconds = 0
    preparation_seconds = prepared.get("timings", {}).get("preparation_seconds", 0)
    if store:
        existing = store.bind(signature, {"id": sid, "run_id": prepared["run_id"],
            "messages": prepared["messages"], "tools": prepared["tools"],
            "budget": budget.to_dict(), "backend": identity,
            "preparation_seconds": preparation_seconds})
        if existing:
            return existing
        events = store.events()
        preparation_seconds = events[0].get("preparation_seconds", 0)
        if len(events) > 1 and not resume:
            raise RecoveryRequired("Unfinished session exists; explicit resume is required")
    else:
        events = []
    state["elapsed_base"] = preparation_seconds
    started = time.monotonic()
    try:
        observe(state, trace, "input", run_id=prepared["run_id"], messages=prepared["messages"], tools=prepared["tools"],
                history_id_map=prepared.get("source", {}).get("history_id_map", {}),
                backend_kind=identity.get("kind"))
        environment_started = time.monotonic()
        env = env_factory()
        environment_seconds = time.monotonic() - environment_started
        if len(events) > 1:
            recover_start = time.monotonic()
            restore(state, events, env, trace)
            recovery_seconds = time.monotonic() - recover_start
        else:
            state["elapsed_base"] += environment_seconds
        state["started"] = time.monotonic()
        deadline = state["started"] + max(0, budget.seconds - state["elapsed_base"])
        runtime = ToolRuntime(env, deadline, trace, state)
        if time.monotonic() >= deadline:
            raise TimeoutError("Session budget exhausted")
        if state["pending"] is not None:
            recovered = runtime.exec({}, json.dumps(state["pending"], ensure_ascii=False), "recovery")
            if isinstance(recovered, Return):
                result = recovered.return_value
        if result is None:
            adapter = LocalBackend(backend, prepared["tools"], deadline, trace, state, budget)
            with JazTrace(trace, state), jaz.ConfigOverride(
                llm=adapter, repl=runtime, protocol=ToolProtocol(state["messages"]),
            ):
                result = jaz.invoke(request=prepared["messages"][-1]["content"])
    except ContextLimit as exc:
        result = {"status": "budget_exhausted", "reason": "context_limit", "final_text": None, "error": str(exc)}
    except TokenLimit as exc:
        result = {"status": "budget_exhausted", "reason": "token_limit", "final_text": None, "error": str(exc)}
    except TimeoutError as exc:
        result = {"status": "budget_exhausted", "reason": "time_limit", "final_text": None, "error": str(exc)}
    except KeyboardInterrupt:
        result = {"status": "externally_interrupted", "reason": "keyboard_interrupt", "final_text": None}
    except RecoveryRequired as exc:
        result = {"status": "recovery_required", "reason": str(exc), "final_text": None}
    except Exception as exc:
        result = {"status": "runner_error", "reason": "trace_io" if state["trace_error"] else "exception", "final_text": None,
                  "error": f"{type(exc).__name__}: {exc}"}
    active = state["elapsed_base"] + time.monotonic() - state["started"]
    deadline_exceeded = active > budget.seconds
    if result["status"] in ("completed", "waiting_for_user") and deadline_exceeded:
        result.update(status="budget_exhausted", reason="time_limit")
    # Intent/result gaps remain unresolved even when the exception was caught in-process.
    events_now = store.events() if store and result["status"] != "recovery_required" else []
    pending_ids = {e["call_id"] for e in events_now if e["event"] == "tool_intent"} - {
        e["call_id"] for e in events_now if e["event"] == "tool"}
    if pending_ids:
        result.update(status="recovery_required", reason="tool_intent_without_result")
    submission = None
    if env is not None and result["status"] != "recovery_required":
        submission = submission_row(sid, env)
    all_events = events_now or state["events"]
    def total(key, field=None):
        if any(e["event"] == "model_error" for e in all_events):
            return None
        values = [e.get(field, {}).get(key) if field else e.get(key) for e in all_events if e["event"] == "model"]
        return sum(values) if values and all(isinstance(v, (int, float)) for v in values) else None
    record = {"id": sid, "run_id": prepared["run_id"], "signature": signature, **result,
        "terminal": result["status"] not in ("externally_interrupted", "recovery_required"),
        "submission": submission, "calls": state["pairs"], "backend": identity,
        "input": {"messages": prepared["messages"], "tools": prepared["tools"]},
        "environment": prepared.get("environment"),
        "source": prepared.get("source", {}),
        "metrics": {"elapsed_seconds": active, "recovery_seconds": recovery_seconds,
                    "deadline_exceeded": deadline_exceeded,
                    "charged_preparation_seconds": preparation_seconds,
                    "environment_setup_seconds": environment_seconds,
                    "timing_complete": result["status"] != "recovery_required" and
                                       not any(e["event"] == "model_error" for e in all_events),
                    **prepared.get("timings", {}),
                    "attempt_wall_seconds": time.monotonic() - started,
                    "tool_seconds": sum(p["seconds"] for p in state["pairs"]),
                    "backend_wall_seconds": sum(e.get("backend_wall_seconds", 0) for e in all_events),
                    "render_tokenize_seconds": total("render_tokenize_seconds", "timings"),
                    "inference_seconds": total("inference_seconds", "timings"),
                    "parse_seconds": total("parse_seconds", "timings"),
                    "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
                    "model_calls": sum(e["event"] == "model_input" for e in all_events)}}
    if store:
        if record["terminal"]:
            store.commit(record)
        elif result["status"] == "externally_interrupted":
            store.append("pause", active_seconds=active, reason="keyboard_interrupt")
            store.view(record)
        else:
            store.view(record)
    if not state["trace_error"]:
        observe(state, trace, "end", record=record, prediction=submission, summary=summary(record))
    return record


def summary(record):
    return {"id": record["id"], "run_id": record["run_id"], "status": record["status"],
            "reason": record["reason"], "final_text": record["final_text"],
            "error": record.get("error"), **record["metrics"],
            "tool_call_count": len(record["calls"])}

