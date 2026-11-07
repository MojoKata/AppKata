#!/usr/bin/env python3
# #2 de-risk: a concrete, well-defined rule for resolving a sandbox when several Trusts (and the user)
# weigh in. The gap was "most restrictive template + intersection of grants" being undefined when two
# Trusts name *different* templates. Resolution: templates stop being atomic at merge time — resolve
# each to a grant set, then combine. Order of authority: user override > merge(reviews) > default.

LEVELS = ["off", "standard", "strict"]          # strictness order; "off" is least restrictive
def stricter(a, b): return a if LEVELS.index(a) >= LEVELS.index(b) else b

# built-in templates -> a normalized grant set. folders: {path: "ro"|"rw"}; caps/devices: sets.
TEMPLATES = {
    "strict":        dict(level="strict",   folders={}, network=False, ports=None, sound=set(), devices=set(), caps=set(), exec_deny=True),
    "offline-editor":dict(level="standard", folders={}, network=False, ports=None, sound=set(), devices=set(), caps=set(), exec_deny=True),
    "online-app":    dict(level="standard", folders={}, network=True,  ports=None, sound={"play"}, devices=set(), caps={"notifications"}, exec_deny=True),
    "messenger":     dict(level="standard", folders={}, network=True,  ports=None, sound={"play","record"}, devices={"camera"}, caps={"tray","notifications","inhibit"}, exec_deny=True),
    "media-player":  dict(level="standard", folders={}, network=False, ports=None, sound={"play"}, devices=set(), caps={"mpris","inhibit"}, exec_deny=True),
    "developer":     dict(level="standard", folders={}, network=True,  ports=None, sound=set(), devices=set(), caps=set(), exec_deny=False),
    "cli-tool":      dict(level="standard", folders={"$cwd":"rw"}, network=False, ports=None, sound=set(), devices=set(), caps=set(), exec_deny=False),
}

def resolve_template(name): return {k: (dict(v) if isinstance(v, dict) else set(v) if isinstance(v, set) else v)
                                    for k, v in TEMPLATES[name].items()}

def apply_overrides(gs, ov):
    """ov: e.g. {'folders':{'+~/Zettlr':'rw','-~/Downloads':None}, 'network':True}. +/- on folders."""
    gs = dict(gs); gs["folders"] = dict(gs["folders"])
    for k, v in ov.items():
        if k == "folders":
            for path, mode in v.items():
                if path.startswith("+"): gs["folders"][path[1:]] = mode
                elif path.startswith("-"): gs["folders"].pop(path[1:], None)
                else: gs["folders"][path] = mode
        else:
            gs[k] = v
    return gs

def review_grant_set(review):
    gs = resolve_template(review["template"])
    return apply_overrides(gs, review.get("overrides", {}))

def intersect(a, b):
    """The least-privilege combination of two grant sets (used across Trusts)."""
    folders = {}
    for p in set(a["folders"]) & set(b["folders"]):
        folders[p] = "rw" if a["folders"][p] == "rw" and b["folders"][p] == "rw" else "ro"   # rw only if both rw
    return dict(
        level=stricter(a["level"], b["level"]),
        folders=folders,
        network=a["network"] and b["network"],
        ports=(None if a["ports"] is None and b["ports"] is None
               else sorted(set(a["ports"] or []) & set(b["ports"] or []))),   # None = all; a set = only those
        sound=a["sound"] & b["sound"],
        devices=a["devices"] & b["devices"],
        caps=a["caps"] & b["caps"],
        exec_deny=a["exec_deny"] or b["exec_deny"],      # deny if either denies (more restrictive)
    )

def resolve(reviews=None, user=None, default="strict"):
    """reviews: list of review dicts (per Trust). user: a grant set the user chose (wins). default: template name."""
    if user is not None:
        return ("user", user)
    reviews = reviews or []
    if not reviews:
        return ("default", resolve_template(default))
    gs = review_grant_set(reviews[0])
    for r in reviews[1:]:
        gs = intersect(gs, review_grant_set(r))
    return ("reviews", gs)

# ---- tests ----
def show(tag, gs):
    print(f"  {tag:22} level={gs['level']:8} net={str(gs['network']):5} folders={gs['folders']} "
          f"sound={sorted(gs['sound'])} dev={sorted(gs['devices'])} caps={sorted(gs['caps'])} exec_deny={gs['exec_deny']}")

print("== two Trusts, DIFFERENT templates (the case the old rule left undefined)")
src, gs = resolve(reviews=[{"template":"messenger"}, {"template":"offline-editor"}])
show("messenger ∩ offline", gs)
assert gs["network"] is False            # offline-editor says no network -> intersection is no network
assert gs["sound"] == set()              # offline has no sound -> intersection empty
assert gs["devices"] == set()            # camera dropped (offline has none)
assert gs["exec_deny"] is True
print("  -> well-defined: strictest level, and only what BOTH allow\n")

print("== template + override, then a second Trust")
src, gs = resolve(reviews=[{"template":"offline-editor","overrides":{"folders":{"+~/Zettlr":"rw"}}},
                           {"template":"offline-editor"}])
show("editor+~Zettlr ∩ editor", gs)
assert "~/Zettlr" not in gs["folders"]   # only one Trust granted it -> not in the intersection
print("  -> a folder only one Trust grants is dropped by the intersection\n")

print("== developer (exec allowed) ∩ anything stays safe")
src, gs = resolve(reviews=[{"template":"developer"}, {"template":"online-app"}])
show("developer ∩ online", gs)
assert gs["exec_deny"] is True           # online-app denies exec -> deny wins
print("  -> execute-deny is contagious: one Trust denying is enough\n")

print("== user override beats reviews; unreviewed falls to default")
src, gs = resolve(reviews=[{"template":"messenger"}], user=resolve_template("strict"))
assert src == "user" and gs["level"] == "strict"; print("  user override -> strict (wins over messenger)")
src, gs = resolve(reviews=[], default="strict")
assert src == "default" and gs["level"] == "strict"; print("  no reviews -> default (strict)")
print("\nALL MERGE CASES WELL-DEFINED ✓")
