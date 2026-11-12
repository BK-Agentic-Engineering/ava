"""smolagents 1.26: retain LifeMate names/schemas and let the SDK validate calls."""

import copy
import json
import time

from smolagents import ToolCallingAgent
from smolagents.models import Model, ChatMessage, TokenUsage, get_tool_json_schema
from smolagents.tools import BaseTool, Tool

from .execution import emit
from .llamacpp_client import SessionStop, ResponseFormatError


class ToolSpec(BaseTool):
    to_tool_calling_prompt = Tool.to_tool_calling_prompt

    def __init__(self, spec, execute):
        self.name, self.description = spec["name"], spec["description"]
        self.inputs, self.output_type = spec["parameters"]["properties"], "object"
        self.execute = execute

    def __call__(self, **arguments):
        return self.execute(self.name, arguments)


class SDKAgent(ToolCallingAgent):
    def execute_tool_call(self, tool_name, arguments):
        # No smolagents argument substitution/pre-validation before the authoritative SDK.
        if tool_name == "final_answer":
            return super().execute_tool_call(tool_name, arguments)
        return self.execute_sdk(tool_name, arguments)


class SmolModel(Model):
    def __init__(self, backend, prepared, state, trace, budget):
        super().__init__(model_id="lfm3")
        self.backend, self.prepared = backend, prepared
        self.state, self.trace, self.budget = state, trace, budget

    def generate(self, messages, stop_sequences=None, tools_to_call_from=None, **kwargs):
        if tools_to_call_from is None:
            # smolagents asks for an extra synthetic final answer at its step limit.
            raise SessionStop("budget_exhausted", "step_limit")
        # LFM3 requires structured calls/results, rather than smolagents' textual memory.
        wire = copy.deepcopy(self.state["messages"])
        tools = self.prepared["tools"] + [get_tool_json_schema(
            next(t for t in tools_to_call_from if t.name == "final_answer"))]
        emit(self.state, self.trace, "model_input", messages=wire, tools=tools)
        started = time.monotonic()
        try:
            response = self.backend.generate(wire, tools, max_context_tokens=self.budget.context_tokens,
                max_new_tokens=self.budget.output_tokens, tool_choice="required")
            if not (response["timed_out"] or response["hit_token_limit"]):
                calls = response["message"].get("tool_calls") or []
                ids = [call.get("id") for call in calls]
                if any(not isinstance(call_id, str) or not call_id for call_id in ids) or len(set(ids)) != len(ids):
                    raise ResponseFormatError("tool_calls", "Tool call IDs must be present and unique",
                                              response["raw_text"])
                if len(calls) > 1 and any(call["function"]["name"] == "final_answer" for call in calls):
                    # smolagents rejects this turn after dispatch; detect it before SDK side effects.
                    raise ResponseFormatError("tool_calls", "final_answer must be the only call in its turn",
                                              response["raw_text"])
        except (Exception, SessionStop) as exc:
            emit(self.state, self.trace, "model_error", error=f"{type(exc).__name__}: {exc}",
                 backend_wall_seconds=time.monotonic()-started,
                 stage=getattr(exc, "stage", None), raw_response=getattr(exc, "raw_response", None))
            if isinstance(exc, TimeoutError):
                raise SessionStop("budget_exhausted", "time_limit") from exc
            if isinstance(exc, ResponseFormatError):
                raise SessionStop("protocol_error", exc.stage) from exc
            raise
        emit(self.state, self.trace, "model", **response, backend_wall_seconds=response["seconds"])
        if response["timed_out"] or response["hit_token_limit"]:
            raise SessionStop("budget_exhausted", "time_limit" if response["timed_out"] else "token_limit")
        self.state["messages"].append(copy.deepcopy(response["message"]))
        self.tool_call_ids = iter(call["id"] for call in (response["message"].get("tool_calls") or [])
                                  if call["function"]["name"] != "final_answer")
        return ChatMessage.from_dict(copy.deepcopy(response["message"]),
            token_usage=TokenUsage(response["input_tokens"], response["output_tokens"]))

    def parse_tool_calls(self, message):
        raise SessionStop("protocol_error", "no_structured_tool_calls")


def run_smolagents(prepared, backend, env, state, trace, budget):
    def execute(name, arguments):
        if state.get("waiting_for_user"):
            raise SessionStop("waiting_for_user", "missing_information")
        if time.monotonic() >= backend.deadline:
            raise SessionStop("budget_exhausted", "time_limit")
        call_id = f"{state['run_id']}/latest/{len(state['pairs'])}"
        call = {"name": name, "arguments": arguments}
        emit(state, trace, "tool_intent", call_id=call_id, call=call)
        started = time.monotonic()
        result = env.call(name, arguments)
        state["messages"].append({"role": "tool", "tool_call_id": next(model.tool_call_ids),
                                  "content": json.dumps(result, ensure_ascii=False)})
        pair = {"call_id": call_id, "call": call, "result": result,
                "seconds": time.monotonic()-started, "state_hash": env.get_state_hash()}
        state["pairs"].append(pair)
        emit(state, trace, "tool", **pair)
        if result.get("ok") and result.get("waiting_for_user"):
            state["waiting_for_user"] = True
            raise SessionStop("waiting_for_user", "missing_information")
        return json.dumps(result, ensure_ascii=False)

    model = SmolModel(backend, prepared, state, trace, budget)
    agent = SDKAgent(tools=[ToolSpec(t["function"], execute) for t in prepared["tools"]],
        model=model, instructions=prepared["messages"][0]["content"],
        max_steps=backend.max_steps, max_tool_threads=1, verbosity_level=0)
    agent.prompt_templates["system_prompt"] = (
        "{{ custom_instructions }}\n"
        "Dùng giao thức gọi tool gốc của mô hình, không viết Action JSON hay mô tả call trong văn bản. "
        "Khi hoàn tất hoặc yêu cầu ngoài phạm vi tool, gọi final_answer với câu trả lời ngắn.\n"
        "final_answer chỉ là lệnh kết thúc nội bộ, không thực thi app hay SDK. "
        "Nếu người dùng yêu cầu không dùng công cụ, không gọi tool của app nhưng vẫn dùng final_answer để kết thúc.\n"
        "ok chỉ xác nhận tool đã được gọi; done=false nghĩa là thao tác chưa thực hiện thành công. "
        "Đọc đầy đủ kết quả; không lặp lại hành động đã thành công, không lặp nguyên call thất bại khi không có dữ liệu mới. "
        "Mỗi lượt chỉ xuất lời gọi tool XML, không trả lời bằng văn bản thông thường. "
        "Khi xong, đặt câu trả lời trong tham số answer của final_answer như sau:\n"
        "<tool_call>\n<function=final_answer>\n<parameter=answer>\nĐã hoàn tất.\n"
        "</parameter>\n</function>\n</tool_call>"
    )
    state["messages"][0]["content"] = agent.system_prompt
    agent.execute_sdk = execute
    answer = agent.run(prepared["messages"][-1]["content"])
    return {"status": "completed", "reason": "final_answer", "final_text": str(answer)}
