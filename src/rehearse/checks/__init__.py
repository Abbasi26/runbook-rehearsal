"""Built-in non-destructive checks."""

from rehearse.checks.completeness import CompletenessCheck
from rehearse.checks.contacts import ContactCheck
from rehearse.checks.files import FileCheck
from rehearse.checks.freshness import FreshnessCheck
from rehearse.checks.groups import GroupCheck
from rehearse.checks.reachability import ReachabilityCheck
from rehearse.checks.scripts import ScriptCheck

__all__ = [
    "CompletenessCheck",
    "ContactCheck",
    "FileCheck",
    "FreshnessCheck",
    "GroupCheck",
    "ReachabilityCheck",
    "ScriptCheck",
    "default_checks",
]


def default_checks():
    return [
        FreshnessCheck(),
        ContactCheck(),
        ReachabilityCheck(),
        FileCheck(),
        ScriptCheck(),
        GroupCheck(),
        CompletenessCheck(),
    ]
