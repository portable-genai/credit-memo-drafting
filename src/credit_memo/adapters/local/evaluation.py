"""Local evaluation gate adapter (EvaluationGatePort) — delegates to the offline gate.

The ``local`` profile's stand-in for the **Gen AI evaluation service** (and the A4 gate):
it delegates to the in-repo offline evaluator (``eval/run_eval.py``), the same
deterministic, credential-free heuristic gate that guards CI. Under ``local`` this
platform-client concern runs in-process, NOT HTTP to A4. SDK-free and unconditional. This
proves the A4 promotion gate runs entirely off-cloud.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from ...config import Settings
from ...domain.models import EvalReport

# eval/ is a repo-root directory (not a package): adapters/local/evaluation.py ->
# local -> adapters -> credit_memo -> src -> <repo>.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_EVAL_SCRIPT = _REPO_ROOT / "eval" / "run_eval.py"


class LocalOfflineEvalAdapter:
    """Run the in-repo offline eval gate and return its :class:`EvalReport`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, dataset_path: str) -> EvalReport:
        run_eval = self._load_run_eval()
        if run_eval is not None:
            dataset = Path(dataset_path) if dataset_path else run_eval.DEFAULT_DATASET
            thresholds = run_eval.load_thresholds_from_rubrics()
            return run_eval.run_offline(dataset, thresholds)
        # Defensive fallback: the offline gate script is unavailable in this build.
        # Nothing was evaluated, so the report claims nothing. The old fallback returned a
        # hand-written passing metric over zero examples, and `gate()` is
        # `self.evaluate("").passed`, so the promotion gate approved exactly when the
        # evaluator was missing. An empty report fails closed and invents no evidence.
        return EvalReport(dataset=dataset_path, results=(), n_examples=0)

    def gate(self, target: str) -> bool:
        """Promotion gate: True iff the offline eval suite passes its thresholds."""
        return self.evaluate("").passed

    @staticmethod
    def _load_run_eval() -> Any:
        if not _EVAL_SCRIPT.exists():
            return None
        spec = importlib.util.spec_from_file_location("credit_memo_local_run_eval", _EVAL_SCRIPT)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("credit_memo_local_run_eval", module)
        spec.loader.exec_module(module)
        return module
