"""Replay one profile-landmark-to-save family in fresh pinned SDK sessions."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import zipfile

from audit_synthetic_coverage import components
from replay_train_wave_01 import canonical
from replay_train_wave_08 import ROOT, gold_observations, load_design, matches, verify as verify_trace, validate
from replay_train_wave_15 import ARCHIVE

DESIGN = ROOT / "data/synthetic/design/train_wave_18.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_18_replay/replay.json"
KINDS = {"maps.search_place": "read", "maps.save_place": "write"}


def materialize(world, scenario):
    result = deepcopy(world["initial_state"])
    for app, fields in world["variants"].get(scenario["fixture_variant"], {}).items():
        result[app].update(deepcopy(fields))
    return result


def effects(initial, final, actions):
    expected = deepcopy(initial)
    for name, args in actions:
        assert name == "maps.save_place"
        existing = next((r for r in expected["maps"]["saved_places"] if r["place_id"] == args["place_id"]), None)
        if existing:
            existing["label"] = args["label"]
        else:
            old_ids = {r["id"] for r in initial["maps"]["saved_places"]}
            added = [r for r in final["maps"]["saved_places"] if r["id"] not in old_ids]
            if len(added) != 1 or added[0] != {"id": added[0]["id"], **args}:
                return False
            expected["maps"]["saved_places"].append(added[0])
    return expected == final


def verify(world, scenario, initial, calls, final):
    alias = scenario["oracle_draft"]["target"]
    target = gold_observations(world, initial)[alias]
    source = scenario["oracle_draft"]["source"]
    if source == "explicit_address":
        assert target["address"] in scenario["agent_visible"]["request"]
        required = {k: target[k] for k in ("name", "address")}
    else:
        landmark = scenario["agent_visible"]["context"]["user_profile"][source]
        assert target["detail"] == "Cạnh " + landmark
        assert sum(r.get("name") == target["name"] and r.get("detail") == target["detail"]
                   for r in initial["maps"]["places"]) == 1
        required = {"name": target["name"], "detail": "Cạnh " + landmark}
    world = deepcopy(world)
    world["witnesses"][alias][1] = required
    verdict = verify_trace(world, scenario, initial, calls, final, KINDS, effects=effects)
    prefix = calls[:next((i for i,c in enumerate(calls) if c["name"] != "maps.search_place"),len(calls))]

    def establishes_place(call):
        ids = {row.get("id") for row in call["result"].get("places", []) if matches(row, required)}
        # verify_trace also requires the saved ID to equal this bound target.
        return ids == {target["id"]}

    if not any(c["name"] == "maps.search_place" and c["result"].get("ok") is True
               and c["name"] in scenario["agent_visible"]["allowed_tools"]
               and c["result"].get("done") is not False
               and establishes_place(c) for c in prefix):
        verdict["verdict"] = "reject"
        verdict["reasons"] = sorted(set(verdict["reasons"]) | {"place_evidence"})
    return verdict


def run(archive, output):
    begin = perf_counter()
    design = load_design(DESIGN)
    docs = [load_design(p) for p in sorted(DESIGN.parent.glob("*.yaml"))]
    inventory = validate(next(d for d in docs if d["version"] == "train_wave_14"),docs)
    inventory.pop("near_duplicate_review",None)
    inventory["components"] = components({w["world_id"]:w for d in docs for w in d["worlds"]},
                                         {s["scenario_id"]:s for d in docs for s in d["scenarios"]})
    assert (design["split"],design["status"],design["exportable"]) == ("train","spec_only",False)
    world = design["worlds"][0]
    assert world["split"] == "train"
    provenance = design["provenance"]
    files = ["__init__.py","executor.py","validate.py","utils.py","apps/__init__.py","apps/base.py","apps/sys.py","apps/maps.py"]
    rows,fixtures,visible = [],{},{}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        root=Path(directory)
        with zipfile.ZipFile(archive) as source:
            for member in files:
                path=root/"zaic_tools"/member
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(source.read(provenance["runtime_root"]+member))
            catalog=json.loads(source.read(provenance["catalog_member"]))
        assert catalog["schema_version"] == provenance["schema"]
        assert "zaic_tools" not in sys.modules
        sys.path.insert(0,directory)
        from zaic_tools.executor import Session
        for scenario in design["scenarios"]:
            sid=scenario["scenario_id"]
            assert scenario["status"]=="spec_only" and scenario["exportable"] is False
            assert scenario["agent_visible"]["allowed_tools"]==world["relevant_tools"]
            assert scenario["fixture_variant"]=="base" or scenario["fixture_variant"] in world["variants"]
            initial=materialize(world,scenario)
            allowed=scenario["agent_visible"]["allowed_tools"]
            fixtures[sid]={**initial,"sys":{},"_meta":{"tools":allowed,"current_time":scenario["agent_visible"]["context"]["current_time"]}}
            visible[sid]=scenario["agent_visible"]
            assert all(r["id"] not in canonical(visible[sid]) for r in initial["maps"]["places"])
            target=gold_observations(world,initial)[scenario["oracle_draft"]["target"]]
            other=gold_observations(world,initial)["b" if scenario["oracle_draft"]["target"]=="a" else "a"]
            source=scenario["oracle_draft"]["source"]
            near=target["address"] if source=="explicit_address" else visible[sid]["context"]["user_profile"][source]
            query=("maps.search_place",{"query":target["name"],"near":near})
            save=("maps.save_place",{"place_id":target["id"],"label":scenario["oracle_draft"]["label"]})
            traces={
                "standard":[query,save],
                "broad_search":[("maps.search_place",{"query":target["name"]}),save],
                "guessed_id":[save],
                "distractor":[("maps.search_place",{"query":target["name"]}),
                              ("maps.save_place",{"place_id":other["id"],"label":scenario["oracle_draft"]["label"]})],
                "damage_existing":[query,save,("maps.search_place",{"query":"*"}),
                                   ("maps.save_place",{"place_id":"w18_old","label":"Chỗ làm chìa"})],
                "wrong_label":[query,("maps.save_place",{"place_id":target["id"],"label":"Chỗ hẹn"})],
                "late_read":[save,query],
            }
            for case,plan in traces.items():
                session=Session(sid,fixtures[sid],catalog)
                assert session.log==[] and session.allowed==set(allowed)|{"sys.ask_missing_info"}
                before=session.get_state()
                calls=[]
                for name,args in plan:
                    result=session.call(name,args)
                    assert result.get("ok") is True and result.get("done") is not False
                    calls.append({"name":name,"arguments":deepcopy(args),"result":deepcopy(result)})
                final=session.get_state()
                verdict=verify(world,scenario,before,calls,final)
                expected={
                    "standard":[], "broad_search":[],
                    "guessed_id":["grounding","place_evidence"],
                    "distractor":["authorized_actions","state"],
                    "damage_existing":["authorized_actions","state"],
                    "wrong_label":["authorized_actions","state"],
                    "late_read":["grounding","place_evidence"],
                }[case]
                assert verdict["reasons"]==expected,(sid,case,verdict)
                assert session.log==calls
                assert Session(sid,fixtures[sid],catalog).get_state()==before
                rows.append({"scenario_id":sid,"trace_case":case,"evidence_kind":"actual_runtime_trace",
                             "calls":calls,"final_state":final,"verdict":verdict})
    a,b=(s for s in design["scenarios"] if s["scenario_id"] in ("TR18_WORK_A","TR18_WORK_B"))
    left,right=deepcopy(a["agent_visible"]),deepcopy(b["agent_visible"])
    assert left["context"]["user_profile"].pop("work_address")!=right["context"]["user_profile"].pop("work_address")
    assert left==right and materialize(world,a)==materialize(world,b)
    assert a["oracle_draft"]["target"]!=b["oracle_draft"]["target"]
    result={"created_utc":datetime.now(timezone.utc).isoformat(),"replay_wall_seconds":perf_counter()-begin,
            "declared_volatile_fields":["created_utc","replay_wall_seconds"],"inventory":inventory,
            "provenance":{**provenance,"archive":str(archive),"allowlisted_members":[provenance["runtime_root"]+p for p in files]+[provenance["catalog_member"]]},
            "agent_visible":visible,"fixtures":fixtures,"replays":rows,
            "status":{"scenarios":len(design["scenarios"]),"outcomes":{"execute":len(design["scenarios"])},
                      "verdicts":dict(Counter(r["verdict"]["verdict"] for r in rows)),"verifier_only_probes":0,
                      "exportable":False,"execution_verified":0}}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(result["status"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,default=ARCHIVE)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    args=parser.parse_args()
    run(args.archive,args.output)
