from __future__ import annotations

import run_50_personalized_drafts_v2 as runner

_original_rows_from_values = runner.rows_from_values


def _compat_rows_from_values(values):
    return [], _original_rows_from_values(values)


runner.rows_from_values = _compat_rows_from_values

if __name__ == "__main__":
    raise SystemExit(runner.main())
