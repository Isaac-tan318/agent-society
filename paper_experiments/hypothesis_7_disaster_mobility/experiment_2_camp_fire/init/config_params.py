"""Generate init_config.json + steps.yaml for the camp_fire scenario (AS2 paper Sec. 7.7)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from make_config import generate  # noqa: E402

generate(HERE, scenario="camp_fire")
