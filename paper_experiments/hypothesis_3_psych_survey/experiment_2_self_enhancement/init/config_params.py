"""Generate init_config.json + steps.yaml for the se task (AS2 paper Sec. 7.3)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from make_config import generate  # noqa: E402

generate(HERE, task="se")
