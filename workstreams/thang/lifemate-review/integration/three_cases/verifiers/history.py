from copy import deepcopy

def argument(value, events):
    if isinstance(value, str) and value.startswith("$"):
        parts = value[1:].split(".")
        result = events[parts[0]]["result"]
        for key in parts[1:]:
            result = result[key]
        return deepcopy(result)
    if isinstance(value, dict) and "observed" in value:
        records = events[value["observed"]]["result"][value["collection"]]
        hits = [r for r in records if all(r.get(k) == v for k, v in value["match"].items())]
        assert len(hits) == 1, value
        return deepcopy(hits[0][value["field"]])
    if isinstance(value, dict):
        return {key: argument(item, events) for key, item in value.items()}
    if isinstance(value, list):
        return [argument(item, events) for item in value]
    return value


def successful(event):
    return event["result"].get("ok") is True and event["result"].get("done") is not False
