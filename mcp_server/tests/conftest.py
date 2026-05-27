import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MCP_REQUIRE_AUTH"] = "false"
os.environ["CIRCLE_API_KEY"] = "test-key"
os.environ["ENTITY_SECRET"] = "test-secret"
