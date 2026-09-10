#!/usr/bin/env python3
from __future__ import annotations

import prospect_agent_qualification as legacy

_original_classify = legacy.classify_agent_context
_PRIORITY = (
    'quote_intake',
    'commerce',
    'customer_support',
    'front_desk_sales',
    'review_concierge',
)


def classify_agent_context_draft_first(context: str, target_agent_type: str = legacy.AUTO_TARGET):
    target = legacy.normalize_target(target_agent_type)
    if target != legacy.AUTO_TARGET:
        return legacy._fit_for_target(context, target)
    ranked = []
    for priority, agent_type in enumerate(_PRIORITY):
        fit = legacy._fit_for_target(context, agent_type)
        if fit.score:
            ranked.append((-fit.score, priority, fit))
    if not ranked:
        return legacy.AgentFit('', 0, 'none', '', '', '')
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2]


def main(argv=None) -> int:
    legacy.classify_agent_context = classify_agent_context_draft_first
    try:
        return legacy.main(argv)
    finally:
        legacy.classify_agent_context = _original_classify


if __name__ == '__main__':
    raise SystemExit(main())
