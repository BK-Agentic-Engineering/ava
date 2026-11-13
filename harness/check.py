"""Offline contract check: local scripted HTTP responses, real tool runtime, no inference."""
import json
import math
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent import _history_messages, build_tools, run_agent
from analyze import load_trace
from benchmark import score
from diagnostics import fingerprint, prefix_stats, uncertainty

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data/train"))
from zaic_tools.executor import Session


def main():
    catalog = json.loads((Path(__file__).resolve().parents[1] / "data/train/train_tools_catalog.json").read_text())
    # Model-facing documentation must preserve execution schemas and the source catalog.
    for split in ("train", "public_test"):
        source = json.loads((Path(__file__).resolve().parents[1] / f"data/{split}/{split}_tools_catalog.json").read_text())
        before = fingerprint(source)
        installed = {app["id"]: {"tools": [tool["name"] for tool in app["tools"]]} for app in source["apps"]}
        presented = {tool["function"]["name"]: tool["function"] for tool in build_tools(source, installed)}
        names = {tool["name"] for app in source["apps"] for tool in app["tools"]}
        assert set(presented) == names | {"sys.ask_missing_info"}
        assert set(presented["sys.ask_missing_info"]["parameters"]["properties"]["tool_name"]["enum"]) == names - {"sys.ask_missing_info"}
        for app in source["apps"]:
            for tool in app["tools"]:
                params = presented[tool["name"]]["parameters"]
                assert params.get("required", []) == tool["parameters"].get("required", [])
                assert set(params["properties"]) == set(tool["parameters"]["properties"])
                for name, prop in tool["parameters"]["properties"].items():
                    model_prop = params["properties"][name]
                    expected_prop = {key: value for key, value in prop.items() if key != "x-match"}
                    if tool["name"] == "sys.ask_missing_info" and name == "tool_name":
                        expected_prop["enum"] = sorted(names - {"sys.ask_missing_info"})
                    ref = expected_prop.get("x-ref")
                    if ref:
                        expected_prop["description"] = (expected_prop.get("description", "") + " Miền ID: " + ref + ".").strip()
                    assert model_prop == expected_prop
                groups = tool["parameters"].get("x-one-of", [])
                if groups:
                    assert params["required"] == tool["parameters"].get("required", [])
                    base = {key: value for key, value in params.items() if key not in ("anyOf", "x-one-of")}
                    assert params["anyOf"] == [
                        {**base, "required": list(dict.fromkeys([*params["required"], *group]))}
                        for group in groups
                    ]
        assert fingerprint(source) == before
    synthetic = {"apps": [{"tools": [{"name": "new_tool.action", "kind": "write",
        "description": "Catalog behavior", "returns": "A catalog result",
        "parameters": {"type": "object", "properties": {
            "entity_id": {"type": "string", "x-ref": "new_tool.entities"},
            "count": {"type": "integer", "minimum": 2, "maximum": 9}},
            "required": ["entity_id"], "x-one-of": [["count"], ["count", "entity_id"]]}}]}]}
    synthetic["apps"][0]["tools"].append(next(tool for app in catalog["apps"] for tool in app["tools"]
        if tool["name"] == "sys.ask_missing_info"))
    synthetic_tool = next(tool["function"] for tool in build_tools(synthetic,
        {"new_tool": {"tools": ["new_tool.action"]}}) if tool["function"]["name"] == "new_tool.action")
    assert synthetic_tool["description"] == "[write] Catalog behavior Kết quả: A catalog result."
    assert synthetic_tool["parameters"]["properties"]["entity_id"]["x-ref"] == "new_tool.entities"
    base = {key: value for key, value in synthetic_tool["parameters"].items()
            if key not in ("anyOf", "x-one-of")}
    assert synthetic_tool["parameters"]["anyOf"] == [
        {**base, "required": ["entity_id", "count"]},
        {**base, "required": ["entity_id", "count"]}]
    assert synthetic_tool["parameters"]["properties"]["count"]["minimum"] == 2
    assert synthetic_tool["parameters"]["properties"]["count"]["maximum"] == 9
    assert synthetic_tool["parameters"]["x-one-of"] == [["count"], ["count", "entity_id"]]
    history = [{"role": "user", "audio_text": "Find Lân"},
        {"role": "assistant", "text": "Found Lân",
         "tool_calls": [{"name": "contacts.search", "arguments": {"query": "Lân"}}],
         "tool_results": [{"ok": True, "contacts": [{"id": "c_2", "name": "Lân"}]}]}]
    history_messages = _history_messages(history)
    assert history_messages[1]["tool_calls"][0]["id"] == history_messages[2]["tool_call_id"]
    try:
        _history_messages([{"role": "assistant", "tool_calls": [{"name": "contacts.search"}], "tool_results": []}])
    except ValueError as exc:
        assert "count mismatch" in str(exc)
    else:
        raise AssertionError("unpaired historical tool call accepted")
    item = {"id": "synthetic", "audio_text": "Find Mai", "history": [], "context": {
        "current_time": "2026-11-12T09:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
        "installed_apps": {"contacts": {"tools": ["contacts.search", "contacts.update"]}}}}
    replies, requests = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if not replies:
                self.send_error(503, "scripted transport failure")
                return
            payload = json.dumps(replies.pop(0)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    def response(message, finish="tool_calls"):
        return {"choices": [{"message": message, "finish_reason": finish}],
                "usage": {"completion_tokens": 3, "prompt_tokens": 10}}

    def call(name, arguments, reasoning="plan", call_id="call_1"):
        return {"role": "assistant", "content": "", "reasoning_content": reasoning,
                "tool_calls": [{"id": call_id, "type": "function", "function": {
                    "name": name, "arguments": arguments}}]}

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with tempfile.TemporaryDirectory() as directory:
            def execute(name, responses, research=False):
                replies[:] = responses
                requests.clear()
                env = Session("synthetic", {"_meta": {"current_time": item["context"]["current_time"],
                              "tools": item["context"]["installed_apps"]["contacts"]["tools"]}, "contacts": {"contacts": [
                                  {"id": "c_1", "name": "Mai", "phone": "0912345678"}]}}, catalog)
                path = Path(directory) / (name + ".jsonl")
                result = run_agent(item, catalog, env, base_url=url, trace_path=path, research=research, vocab_size=4)
                events = [json.loads(line) for line in path.read_text().splitlines()]
                assert events[0]["event"] == "input" and events[-1]["event"] == "end"
                assert all("request" not in e for e in events)
                loaded = load_trace(path)
                assert loaded["termination"] == result["termination"]
                assert len(loaded["calls"]) == len(env.get_tool_calls())
                return result, env, events

            result, env, events = execute("continuity", [
                response(call("contacts.search", '{"query":"Mai"}', "Resolve recipient first")),
                response({"role": "assistant", "content": "Found Mai"}, "stop")])
            assert result["termination"] == "final_answer"
            assert env.get_tool_calls() == [{"name": "contacts.search", "arguments": {"query": "Mai"}}]
            assert "parallel_tool_calls" not in requests[0]
            assert "parallel_tool_calls" not in requests[1]
            call_event = next(event for event in events if event["event"] == "call")
            result_event = next(event for event in events if event["event"] == "result")
            assert call_event["call_id"] == result_event["call_id"] == "call_1"
            assert call_event["arguments"] == env.get_tool_calls()[0]["arguments"]
            assert requests[1]["messages"][-2]["tool_calls"][0]["id"] == requests[1]["messages"][-1]["tool_call_id"]
            assert requests[1]["messages"][-2]["reasoning_content"] == "Resolve recipient first"
            assert json.loads(requests[1]["messages"][-1]["content"])["contacts"][0]["id"] == "c_1"
            assert fingerprint(requests[0]["tools"]) == fingerprint(requests[1]["tools"])

            replies[:] = [
                response(call("contacts.search", '{"query":"Mai"}')),
                response({"role": "assistant", "content": "Found Mai"}, "stop")]
            requests.clear()
            env = Session("synthetic", {"_meta": {"current_time": item["context"]["current_time"],
                          "tools": item["context"]["installed_apps"]["contacts"]["tools"]}, "contacts": {"contacts": [
                              {"id": "c_1", "name": "Mai", "phone": "0912345678"}]}}, catalog)
            path = Path(directory) / "one_call_option.jsonl"
            result = run_agent(item, catalog, env, base_url=url, trace_path=path, parallel_tool_calls=False)
            assert result["termination"] == "final_answer"
            assert requests[0]["parallel_tool_calls"] is False
            assert requests[1]["parallel_tool_calls"] is False

            result, env, events = execute("research", [
                {"prompt": "first"}, {"tokens": [{"id": 1, "piece": "a"}]},
                response(call("contacts.search", '{"query":"Mai"}')),
                {"prompt": "extended"}, {"tokens": [{"id": 1, "piece": "a"}, {"id": 2, "piece": " "}]},
                response({"content": "Found Mai"}, "stop")], research=True)
            assert result["termination"] == "final_answer"
            probes = [e for e in events if e["event"] == "prefix"]
            assert probes[1]["prefix_invariant"] and probes[1]["whitespace_only_token_fraction"] == .5
            assert requests[2]["logprobs"] is True and requests[2]["top_logprobs"] == 20

            result, env, _ = execute("waiting", [response(call("sys.ask_missing_info",
                '{"tool_name":"contacts.update","params":["phone"]}'))])
            assert result["termination"] == "waiting_for_user" and len(requests) == 1
            assert len(env.get_tool_calls()) == 1

            waiting_batch = call("sys.ask_missing_info", '{"tool_name":"contacts.update","params":["phone"]}')
            waiting_batch["tool_calls"].append({"id": "call_2", "type": "function", "function": {
                "name": "contacts.update", "arguments": '{"contact_id":"c_1","phone":"0987654321"}'}})
            result, env, events = execute("waiting_batch", [response(waiting_batch)])
            assert result["termination"] == "waiting_for_user" and len(requests) == 1
            assert env.get_state()["contacts"]["contacts"][0]["phone"] == "0912345678", "write executed after waiting"
            assert len(env.get_tool_calls()) == 1
            assert len(next(e for e in events if e["event"] == "assistant")["message"]["tool_calls"]) == 2
            assert len([e for e in events if e["event"] == "call"]) == len(env.get_tool_calls()) == 1
            assert len([e for e in events if e["event"] == "result"]) == len(env.get_tool_calls())
            assert next(e for e in events if e["event"] == "call")["call_id"] == \
                   next(e for e in events if e["event"] == "result")["call_id"]

            invalid_native = call("contacts.search", '{"query":"Mai"}')
            invalid_native["tool_calls"][0]["id"] = ""
            mismatched_finish = call("contacts.search", '{"query":"Mai"}')
            invalid_tool = call("banking.transfer", "{}", call_id="call_9")
            for name, reply, termination in [
                ("invalid", response(call("contacts.search", "{invalid")), "protocol_error"),
                ("missing_id", response(invalid_native), "protocol_error"),
                ("finish_mismatch", response(mismatched_finish, "stop"), "protocol_error"),
                ("truncated", response(call("contacts.search", '{}'), "length"), "generation_truncated"),
                ("xml", response({"content": "<tool_call><function=contacts.search>"}, "stop"), "protocol_error")]:
                result, env, _ = execute(name, [reply])
                assert result["termination"] == termination and env.get_tool_calls() == []

            result, env, events = execute("uninstalled", [response(invalid_tool)])
            assert result["termination"] == "runtime_error" and len(env.get_tool_calls()) == 1
            assert env.get_tool_calls()[0] == {"name": "banking.transfer", "arguments": {}}
            assert len([event for event in events if event["event"] == "call"]) == 1
            assert len([event for event in events if event["event"] == "result"]) == 1

            result, env, _ = execute("failure", [response(call("contacts.search", '{}'))])
            assert result["termination"] == "runtime_error" and len(env.get_tool_calls()) == 1
            assert result.get("error")  # The failed second request must not erase the first action.
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    report = score([{ "tool_calls": [{"name": "x", "arguments": {}}],
        "expected_calls": [{"name": "x", "arguments": {}}], "sequence_exact": True,
        "raw_state_exact": False, "canonical_state_exact": True, "termination": "final_answer",
        "failures": {"schema_rejections": 0, "business_failures": 1}, "task_seconds": 8.0}])
    assert report["exact_call_f1"] == 1 and report["canonical_final_state_accuracy"] == 1
    assert report["mean_task_seconds"] == 8 and report["business_failures"] == 1
    assert prefix_stats([1, 2], [1, 2, 3])["prefix_invariant"]
    assert prefix_stats([1, 2], [1, 9])["prefix_stability"] == 0.5
    stats = uncertainty({"logprobs": {"content": [{"token": "a", "logprob": math.log(.5),
        "top_logprobs": [{"logprob": math.log(.5)}, {"logprob": math.log(.25)}]}]}}, 4)
    assert abs(stats["mean_entropy_lower_nats"] - 1.0397207708399179) < 1e-9
    assert abs(stats["mean_entropy_upper_nats"] - 1.2130075659799042) < 1e-9
    print("PASS: tool contracts, continuity, stable schemas, immediate waiting stop, truncation, malformed calls, partial trace, prefix and entropy bounds")


if __name__ == "__main__":
    main()
