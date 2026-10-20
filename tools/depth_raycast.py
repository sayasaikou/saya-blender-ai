# -*- coding: utf-8 -*-
"""Render a depth map by ray casting instead of using a render pass.

Why: on Blender 5 the usual routes are all unavailable (measured):
    1. Workbench `color_type='DEPTH'`           -> no DEPTH in the enum
    2. Compositor RLayers.Depth -> MapRange      -> CompositorNodeRLayers removed
    3. `Render Result.render_slots[0].z`         -> RenderSlot only has name/clear
    4. multi-layer EXR round trip                -> no OPEN_EXR_MULTILAYER in the enum

Ray casting does not depend on any render pass: for every pixel build a camera ray
and let `scene.ray_cast()` measure the distance to geometry. Lighting, materials and
the render engine cannot affect the result.

Usage:
    blender -b <scene.blend> --python depth_raycast.py -- --out <dir> [options]

Options:
    --width / --height   output size (default 1344x768)
    --near / --far       clip range mapped to the grayscale (default 0.5 / 16.0)
    --step               ray-cast downsample factor (default 2; 1 = full res, slower)
    --camera             create a camera by explicit pose "cx,cy,cz,tx,ty,tz"
                         (omit to use the scene camera)

Output: near = white, far = black, 8-bit grayscale PNG. This is the convention
ControlNet / Depth-Anything expects.
"""
import argparse
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--name", default="depth.png")
    p.add_argument("--width", type=int, default=1344)
    p.add_argument("--height", type=int, default=768)
    p.add_argument("--near", type=float, default=0.5)
    p.add_argument("--far", type=float, default=16.0)
    p.add_argument("--step", type=int, default=2)
    p.add_argument("--camera", default="")
    return p.parse_args(argv)


def save_gray_png(arr8, path, width, height):
    # Blender's bundled Python has no PIL, and adding system site-packages fails on
    # the C extension (_imaging). Use Blender's own image datablock instead.
    im = bpy.data.images.new("depth_out", width=width, height=height, alpha=False)
    im.colorspace_settings.name = "Non-Color"
    buf = np.empty((height, width, 4), dtype=np.float32)
    v = arr8.astype(np.float32) / 255.0
    buf[..., 0] = v
    buf[..., 1] = v
    buf[..., 2] = v
    buf[..., 3] = 1.0
    im.pixels.foreach_set(buf.reshape(-1))
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    return os.path.exists(path) and os.path.getsize(path) > 0


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    scene = bpy.context.scene

    if args.camera:
        parts = [float(v) for v in args.camera.split(",")]
        if len(parts) != 6:
            raise SystemExit("--camera expects cx,cy,cz,tx,ty,tz")
        cam_pos, target = tuple(parts[:3]), tuple(parts[3:])
        bpy.ops.object.camera_add(location=cam_pos)
        cam = bpy.context.active_object
        cam.rotation_euler = (Vector(target) - Vector(cam_pos)).to_track_quat("-Z", "Y").to_euler()
        scene.camera = cam
    else:
        cam = scene.camera
        if cam is None:
            raise SystemExit("scene has no camera; pass --camera")

    width, height, step = args.width, args.height, max(1, args.step)
    cam.data.sensor_fit = "AUTO"
    sensor = cam.data.sensor_width if width >= height else cam.data.sensor_height
    focal = cam.data.lens * (width / sensor)

    # matrix_world is stale right after rotation_euler is set unless the view layer
    # is updated first; reading it early yields identity rotation and every ray goes down.
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    matrix = cam.matrix_world
    origin = matrix.translation.copy()
    cam_dir = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    cam_up = (matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    cam_right = (matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
    print("DEPTH|CAM|origin=%s focal=%.1fpx" % (tuple(round(v, 3) for v in origin), focal))

    grid_w = (width + step - 1) // step
    grid_h = (height + step - 1) // step
    started = time.time()
    distances = np.full((grid_h, grid_w), np.nan, dtype=np.float32)
    for gy in range(grid_h):
        y = gy * step + step * 0.5 - 0.5
        vy = (0.5 - y / height) * (height / focal)
        for gx in range(grid_w):
            x = gx * step + step * 0.5 - 0.5
            vx = (x / width - 0.5) * (width / focal)
            direction = (cam_dir + cam_right * vx + cam_up * vy).normalized()
            hit, loc, _n, _i, _o, _m = scene.ray_cast(depsgraph, origin, direction)
            if hit:
                distances[gy, gx] = (loc - origin).length
    print("DEPTH|raycast|%dx%d grid in %.1fs" % (grid_w, grid_h, time.time() - started))

    hit_ratio = float(np.mean(~np.isnan(distances)))
    print("DEPTH|hits=%.3f" % hit_ratio)
    if hit_ratio <= 0.0:
        raise SystemExit("DEPTH|FAIL|no ray hit geometry (camera looks at nothing)")

    dmin = float(np.nanmin(distances))
    dmax = float(np.nanmax(distances))
    lo, hi = min(args.near, dmin), max(args.far, dmax)
    print("DEPTH|range|near=%.3f far=%.3f -> used %.2f..%.2f" % (dmin, dmax, lo, hi))

    d = np.nan_to_num(distances, nan=hi)
    norm = np.clip((d - lo) / (hi - lo), 0.0, 1.0)
    norm = 1.0 - norm  # near = white, far = black
    full = np.repeat(np.repeat(norm, step, axis=0), step, axis=1)[:height, :width]
    arr = (full * 255.0 + 0.5).astype(np.uint8)

    out = os.path.join(args.out, args.name)
    if not save_gray_png(arr, out, width, height):
        raise SystemExit("DEPTH|FAIL|wrote nothing: %s" % out)
    uniq = len(np.unique(arr))
    print("DEPTH|PNG|%s  %d B  mean=%.1f uniq=%d" % (out, os.path.getsize(out), float(arr.mean()), uniq))
    if uniq < 8:
        print("DEPTH|WARN|only %d gray levels -- probably empty or flat; not a usable depth map" % uniq)
    print("DEPTH|DONE")


if __name__ == "__main__":
    main()
