"""Run scripted architecture tests with Python socket connections denied."""
import os
from pathlib import Path
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
os.environ["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


def deny(*args, **kwargs):
    raise RuntimeError("Network connection attempted during offline architecture check")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
import lifemate
print("LIFEMATE_SOURCE", lifemate.__file__, flush=True)
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / "tests")))
sys.exit(0 if result.wasSuccessful() else 1)
