# -*- coding: utf-8 -*-
"""Inspect an MMD shader node group: inputs, outputs, inner node types.

Why: MMD models import with deeply nested shader groups whose interfaces differ per author.
Before writing a material patch, dump what is actually there -- guessing the socket names is
the fastest way to build a node tree that silently does nothing.

Usage:
    blender -b <scene.blend> --python mmd_inspect.py -- [--material Cloth1]
"""
import argparse
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--material", default="Cloth1")
    return p.parse_args(argv)


def main():
    args = parse_args()
    material = bpy.data.materials.get(args.material)
    if material is None:
        names = [m.name for m in bpy.data.materials]
        raise SystemExit("material %r not found; available: %s" % (args.material, names))

    tree = material.node_tree
    print("MATERIAL", material.name, flush=True)
    for node in tree.nodes:
        print("  NODE", node.type, node.name, flush=True)
        if node.type == "GROUP" and node.node_tree:
            print("    GROUP TREE", node.node_tree.name, flush=True)
            print("    INPUTS:", [(i.name, i.type) for i in node.inputs], flush=True)
            print("    OUTPUTS:", [(o.name, o.type) for o in node.outputs], flush=True)
            print("    INNER TYPES:", sorted({n.type for n in node.node_tree.nodes}), flush=True)
            for inner in node.node_tree.nodes:
                if inner.type == "GROUP_OUTPUT":
                    print("    GROUP_OUTPUT INPUTS:",
                          [(i.name, i.type) for i in inner.inputs], flush=True)


if __name__ == "__main__":
    main()
