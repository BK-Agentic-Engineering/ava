"""Chỉ xuất ba trường chính thức, từ phiên ToolEnv thật."""

def submission_row(sample_id, env):
    return {"id": sample_id, "tool_calls": env.get_tool_calls(),
            "state_hash": env.get_state_hash()}
