# -*- coding: utf-8 -*-
"""Convert MMD toon materials to Principled BSDF (kept as a failed-approach reference).

Why this is here: this route was tried and it looks wrong -- the MMD diffuse textures have
lighting baked in, so using them as albedo double-counts shadows and AO. The script is kept
because the node setup (procedural roughness, micro-bump, subsurface weight) is useful once
the source textures are true albedo.

Usage:
    blender -b <scene.blend> --python mat_upgrade.py -- --out <png> [--tex-from ... --tex-to ...]

Known failure signature (measured): black blotches, shattered highlights, patchy base color.
"""
import argparse
import sys

import bpy

SKIN_MATERIALS = {"肌", "面", "口内", "表情"}
METAL_MATERIALS = {"目HL"}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--tex-from", default="")
    p.add_argument("--tex-to", default="")
    return p.parse_args(argv)


def repair_textures(tex_from, tex_to):
    if not tex_from or not tex_to:
        return
    for im in bpy.data.images:
        fp = im.filepath or ""
        if fp.startswith(tex_from):
            im.filepath = tex_to + fp[len(tex_from):]
            try:
                im.reload()
            except Exception:  # noqa: BLE001
                pass


def upgrade(material):
    nt = material.node_tree
    output = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    base = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and "base" in n.name.lower()), None)
    if output is None or bsdf is None:
        return "skip"

    for link in list(output.inputs[0].links):
        nt.links.remove(link)
    nt.links.new(bsdf.outputs[0], output.inputs[0])

    if base is not None:
        gain = nt.nodes.new("ShaderNodeMix")
        gain.data_type = "RGBA"
        gain.blend_type = "MULTIPLY"
        gain.inputs["Factor"].default_value = 1.0
        gain.inputs[7].default_value = (1.35, 1.35, 1.35, 1.0)
        nt.links.new(base.outputs["Color"], gain.inputs[6])
        nt.links.new(gain.outputs[2], bsdf.inputs["Base Color"])

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 25.0
    noise.inputs["Detail"].default_value = 6.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.25
    ramp.color_ramp.elements[0].color = (0.32, 0.32, 0.32, 1.0)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.52, 0.52, 0.52, 1.0)
    nt.links.new(noise.outputs["Fac"], ramp.inputs[0])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Roughness"])

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.18
    bump.inputs["Distance"].default_value = 0.02
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    if material.name in SKIN_MATERIALS:
        try:
            bsdf.inputs["Subsurface Weight"].default_value = 0.12
            bsdf.inputs["Subsurface Radius"].default_value = (0.24, 0.08, 0.04)
        except Exception:  # noqa: BLE001
            pass
        ramp.color_ramp.elements[0].color = (0.32, 0.32, 0.32, 1.0)
        ramp.color_ramp.elements[1].color = (0.55, 0.55, 0.55, 1.0)

    if material.name in METAL_MATERIALS:
        try:
            bsdf.inputs["Metallic"].default_value = 0.8
            bsdf.inputs["Roughness"].default_value = 0.25
        except Exception:  # noqa: BLE001
            pass
    return "ok"


def main():
    args = parse_args()
    repair_textures(args.tex_from, args.tex_to)

    done = skipped = 0
    for material in list(bpy.data.materials):
        if not material.node_tree:
            continue
        result = upgrade(material)
        if result == "ok":
            done += 1
        else:
            skipped += 1
    print("UPGRADED", done, "SKIPPED", skipped, flush=True)

    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    try:
        scene.eevee.taa_render_samples = args.samples
        scene.eevee.use_gtao = True
        scene.eevee.use_raytracing = True
    except Exception:  # noqa: BLE001
        pass

    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print("RENDER DONE", args.out, flush=True)


if __name__ == "__main__":
    main()
