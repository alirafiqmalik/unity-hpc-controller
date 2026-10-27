"""A portable CPU task: write a declared result without cluster imports."""
import json
import os
from pathlib import Path

output = Path(os.environ["HPC_OUTPUT_DIR"])
output.mkdir(parents=True, exist_ok=True)
values = [2, 3, 5, 7, 11]
(output / "result.json").write_text(json.dumps({"count": len(values), "sum": sum(values)}) + "\n")
