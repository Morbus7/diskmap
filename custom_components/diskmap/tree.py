"""Utsnitt av treet: brukes av tjenesten diskmap.get_tree og websocket-kommandoene."""
from __future__ import annotations


def find(tree: dict, path: str) -> dict | None:
    """Noden for «volume1/photo» (navn skilt med «/», regnet fra røttene). Tom sti gir hele treet."""
    node = tree
    for part in filter(None, path.split("/")):
        node = next((c for c in node.get("c", ()) if c["n"] == part and c["t"] != "o"), None)
        if node is None:
            return None
    return node


def cut(node: dict, depth: int) -> dict:
    """Kopi av noden med bare «depth» nivåer under. more = antall barn som ikke er tatt med."""
    out = {k: v for k, v in node.items() if k not in ("c", "cap", "path")}
    children = node.get("c")
    if children:
        if depth > 0:
            out["c"] = [cut(c, depth - 1) for c in children]
        else:
            out["more"] = len(children)
    return out
