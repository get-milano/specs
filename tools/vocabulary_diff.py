#!/usr/bin/env python3
"""Vocabulary compatibility diff.

Classifies every change between two vocabulary artifacts per the evolution
rules in the vocabulary schema spec (additive within a major; anything that
removes, retypes, or tightens requires a major bump) and verifies the
version bump matches. Exits nonzero when it does not, so producers can gate
publication in CI:

    python3 tools/vocabulary_diff.py old-vocabulary.json new-vocabulary.json

Semantic repurposing with unchanged shape is undetectable by any tool; the
spec forbids it in prose. Pure stdlib.
"""

import json
import sys


def semver(text):
    parts = str(text).split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return None


def type_repr(descriptor):
    return json.dumps(descriptor, sort_keys=True)


def enum_members(descriptor):
    if isinstance(descriptor, dict) and "enum" in descriptor:
        return set(descriptor["enum"]), bool(descriptor.get("optional"))
    return None


def type_change(old, new):
    """Classifies one declared type moving from `old` to `new`: None when
    they are the same type, ("ADDITIVE", gained members) when an enum only
    gained members, ("BREAKING", None) for every other change. Enum member
    additions are the one additive type change; removals and renames
    change the type (evolution rules)."""
    if type_repr(old) == type_repr(new):
        return None
    before, after = enum_members(old), enum_members(new)
    if before is not None and after is not None and before[1] == after[1]:
        # Enum identity is the member set, so a reordered list is the same
        # type: comparing the serialized descriptors alone would report a
        # change that is not one.
        if before[0] == after[0]:
            return None
        if before[0] < after[0]:
            return ("ADDITIVE", sorted(after[0] - before[0]))
    return ("BREAKING", None)


def describe_change(subject, old, new, change, changes):
    verdict, gained = change
    if verdict == "ADDITIVE":
        changes.append(("ADDITIVE", f"{subject} enum gained: {', '.join(gained)}"))
    else:
        changes.append(("BREAKING",
                        f"{subject} type changed: {type_repr(old)} -> {type_repr(new)}"))


def diff_declarations(kind, owner, old, new, changes):
    """Compare name -> type-descriptor maps (properties, action parameters,
    event payloads)."""
    for name in old:
        if name not in new:
            changes.append(("BREAKING", f"{owner} {kind} {name} removed"))
            continue
        change = type_change(old[name], new[name])
        if change is not None:
            describe_change(f"{owner} {kind} {name}", old[name], new[name],
                            change, changes)
    for name in new:
        if name not in old:
            changes.append(("ADDITIVE", f"{owner} {kind} {name} added"))


def diff_result(name, old, new, changes):
    """The completion result is a declared type like any other (vocabulary
    schema spec, Completion results): adding one is additive, since no
    document could bind `result` before; removing or retyping it breaks
    every document that reads `result` in that action's onSuccess; an enum
    result may gain members."""
    before, after = old.get("result"), new.get("result")
    if before is None and after is None:
        return
    if before is None:
        changes.append(("ADDITIVE", f"action {name} result added"))
    elif after is None:
        changes.append(("BREAKING", f"action {name} result removed"))
    else:
        change = type_change(before, after)
        if change is not None:
            describe_change(f"action {name} result", before, after, change, changes)


def diff(old, new):
    changes = []

    old_components = old.get("components", {})
    new_components = new.get("components", {})
    for name, component in old_components.items():
        if name not in new_components:
            changes.append(("BREAKING", f"component {name} removed"))
            continue
        after = new_components[name]
        diff_declarations("property", name,
                          component.get("properties", {}),
                          after.get("properties", {}), changes)
        diff_declarations("event", name,
                          component.get("events", {}),
                          after.get("events", {}), changes)
        if bool(component.get("children")) and not bool(after.get("children")):
            changes.append(("BREAKING", f"component {name} no longer accepts children"))
        if not bool(component.get("children")) and bool(after.get("children")):
            changes.append(("ADDITIVE", f"component {name} now accepts children"))
        if not bool(component.get("strict")) and bool(after.get("strict")):
            changes.append(("BREAKING", f"component {name} became strict"))
        if bool(component.get("strict")) and not bool(after.get("strict")):
            changes.append(("ADDITIVE", f"component {name} is no longer strict"))
    for name in new_components:
        if name not in old_components:
            changes.append(("ADDITIVE", f"component {name} added"))

    old_actions = old.get("actions", {})
    new_actions = new.get("actions", {})
    for name, action in old_actions.items():
        if name not in new_actions:
            changes.append(("BREAKING", f"action {name} removed"))
        else:
            diff_declarations("parameter", f"action {name}",
                              action.get("parameters", {}),
                              new_actions[name].get("parameters", {}), changes)
            diff_result(name, action, new_actions[name], changes)
    for name in new_actions:
        if name not in old_actions:
            changes.append(("ADDITIVE", f"action {name} added"))

    return changes


def main():
    if len(sys.argv) != 3:
        print("usage: vocabulary_diff.py <old-artifact.json> <new-artifact.json>",
              file=sys.stderr)
        return 2

    old = json.load(open(sys.argv[1]))
    new = json.load(open(sys.argv[2]))

    problems = []
    if old.get("name") != new.get("name"):
        problems.append(f"vocabulary name changed: {old.get('name')} -> {new.get('name')}")

    old_version, new_version = semver(old.get("version")), semver(new.get("version"))
    if old_version is None or new_version is None:
        problems.append("both artifacts must carry a major.minor.patch version")

    changes = diff(old, new)
    for verdict, message in changes:
        print(f"{verdict:9} {message}")

    breaking = sum(1 for verdict, _ in changes if verdict == "BREAKING")
    additive = sum(1 for verdict, _ in changes if verdict == "ADDITIVE")

    if old_version and new_version:
        if new_version <= old_version and (breaking or additive):
            problems.append(
                f"version did not increase: {old.get('version')} -> {new.get('version')}")
        if breaking and new_version[0] <= old_version[0]:
            problems.append(
                f"{breaking} breaking change(s) require a MAJOR bump; "
                f"got {old.get('version')} -> {new.get('version')}")
        if additive and not breaking and new_version[:2] <= old_version[:2]:
            problems.append(
                f"{additive} additive change(s) require at least a MINOR bump; "
                f"got {old.get('version')} -> {new.get('version')}")

    if not changes:
        print("no declaration changes")
    if problems:
        print()
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(f"verdict: ok ({breaking} breaking, {additive} additive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
