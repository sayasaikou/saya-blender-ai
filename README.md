# saya-blender-ai

用 Blender 定结构、用 AI 定材质的出图链路。包含两条支线：

1. **MMD 模型 → Blender 布光渲染 → ComfyUI 分区重绘**：几何与光影可控，画风与材质交给 AI。
2. **白模场景 → 深度图 → ControlNet**：把空间构图锁死，让 AI 只负责画，不负责编布局。

不包含模型权重、MMD 模型本体与成品图。

## 这条线补什么缺口

本地出图有两条现成路径，各有硬伤：

| 路径 | 优点 | 硬伤 |
| --- | --- | --- |
| 纯提示词出图 | 快，画风自由 | 相机、布光、空间结构全不可控；每张重掷一次 |
| MMD 模型直接渲 | 几何、服装、比例准确 | 材质是 toon；贴图把光照烘死了，不是纯 albedo |

本仓把两件事拆开：

```
Blender（EEVEE）   负责结构：几何 / 相机 / 布光 / 阴影 / 反射
ComfyUI img2img    负责材质：PBR 质感 / 画风 / 光影细腻度
```

AI 只做低 denoise 重绘，不重新构图。

## 链路

### 支线一：MMD → AI 重绘

1. `mmd_tools` 导入 PMX，补齐贴图（见「导入硬坑」）
2. 布光（三点光或顶侧逆光），EEVEE 渲一张带真实阴影的底图
3. ComfyUI：SDXL 系底模 + ControlNet union（lineart）+ 分区 mask，低 denoise 重绘
4. 逐项验收角色设计细节（鞋扣、绑带、披风内衬）有没有被 AI 脑补改掉

### 支线二：白模 → 深度图 → ControlNet

1. Blender 里摆白模场景（比例与机位对了就行，材质无所谓）
2. `tools/depth_raycast.py` 出深度图（近白远黑，ControlNet 惯例）
3. 深度图给 ControlNet，AI 在锁定的空间里画背景或人物

这条线在 AI 视频里同样适用（工坊背景、场景母版）。

## 验证过的参数

| 项 | 取值 | 说明 |
| --- | --- | --- |
| 底模 | SDXL 系插画底模（Illustrious 谱系） | 需要支持 Danbooru tag |
| 分辨率 | 832×1216 | 与底图同尺寸，避免二次缩放 |
| 采样 | 28 步，`dpmpp_2m` / `karras`，cfg 6.5 | |
| denoise | **0.35–0.40** | 上界见结论 4 |
| ControlNet | union，`lineart`，权重 **0.6** | 不用 tile |
| mask | **只锁脸**，不锁头发、不锁兽耳 | 范围取脸外扩一圈 |
| 输出耗时 | 832×1216 / 28 步约 12–18 s | 单卡 16 GB 实测 |

## 五条核心结论

### 1. 保身份与提画风是同一个旋钮

denoise 低 → 脸和设计细节保住，但画风几乎不变；denoise 高 → 材质和画风上来了，脸开始换人。

链式低 denoise（3 次 × 0.15）也一样：身份稳定，画风提升近乎为零。**不能靠调 denoise 同时拿到两件事。**

### 2. 分区 mask 是唯一能把两者拆开的旋钮

做法：给 `SetLatentNoiseMask` 一张 mask，脸区涂黑（denoise=0，保持底模原样），其余区域放行。

边界要按角色设计定，不能默认「把头部全锁住」：

- 锁脸是对的：脸是最容易崩的部分。
- **锁头发会连发丝走向、光泽一起固化**，AI 只能改发色，改不了质感。
- 兽耳如果是造型识别点，也要放出 mask。

### 3. ControlNet 用 lineart，不用 tile

- `lineart` 0.6：结构锁得住，材质还能被重绘。
- `tile`：会把底图的色块一起锁进去，结果是「改脸、发脏」。

### 4. denoise 有硬上界，约 0.5

同一张底图：0.30 结构稳、0.40 是可用档、**0.50 直接换头**。跨模型重绘时上界更低，因为 AI 不认识这个角色。

### 5. 深度图不要依赖渲染 pass，用光线投射

Blender 5 上 Workbench DEPTH、合成器 RLayers、RenderSlot.z、多层 EXR 四条路全部不可用（实测）。光线投射不依赖任何 pass，光照/材质/引擎都影响不了它。

## 失败方案（不要重走）

| 方案 | 结果 | 根因 |
| --- | --- | --- |
| 把 MMD 的 toon 材质硬换成 Principled BSDF | 发黑、斑驳、高光碎裂 | MMD 的 diffuse 贴图**烘了光照**，不是纯 albedo；当 albedo 用会把阴影和 AO 叠两遍 |
| 用 Cycles 替换 EEVEE | 红伞反弹过曝、脸被压黑 | 灯光是按 EEVEE 调的；换渲染器后能量与弹射全部变化。补 HDRI、面部补光、AgX 后只能打平 EEVEE，不值得 |
| 把 bump 叠进 MMDShaderDev 节点组 | 不崩，但提升被 AI 稀释 | 低 denoise 重绘会把细节层压掉 |
| MMD_Template_Renderer 模板渲染 | CHECK → APPLY → RENDER 能跑通，但质感偏平 | 没有卡渲的渐变与描边；插件能力上限低于手工布光 |
| 更大模型 + 细节 LoRA + hires fix | 材质完成度自评 7.5/10（参考图记 10） | 瓶颈是模型对材质与光的理解，不是分辨率 |

## 导入 MMD 的四个硬坑

1. **贴图路径写死在 PMX 里**（作者机器路径）。导入后必须按文件名重映射；`pmx_render.py` 提供 `--tex-from` / `--tex-to` 做根目录替换。
2. **公共贴图缺失**：`T_actor_common_*` 系列不在角色包里。从其他同系列角色拷，**同号对同号**，不要按名字猜。
3. **眼睛材质**：`mmd_tools` 导入后要显式设 `iris_mode="RAW_A"`，否则眼球材质映射错误。
4. **材质名的正则**：模板插件只认 `Cloth\d+(Alpha)?`。`Cloth10` 这种多一位数字的名字匹配不上，得手动改映射表。

## Blender 5 深度图：四条路都不通

| 尝试 | 结果 |
| --- | --- |
| Workbench `color_type='DEPTH'` | 枚举里没有 `DEPTH` |
| 合成器 `RLayers.Depth` → `MapRange` | Blender 5 去掉了 `CompositorNodeRLayers` |
| `Render Result.render_slots[0].z` | `RenderSlot` 只剩 `name` / `clear` |
| 渲染多层 EXR 再读回 | `file_format` 枚举里没有 `OPEN_EXR_MULTILAYER` |

改用光线投射（`tools/depth_raycast.py`）：相机内外参已知 → 每像素构一条射线 → `scene.ray_cast()` 量距离。

两个实测坑：

- **刚设完相机旋转就读 `matrix_world` 会拿到旧值**（表现为所有光线朝下，深度范围只有地板那一层）。必须先 `bpy.context.view_layer.update()`。
- Blender 自带 Python 没有 PIL，把系统 site-packages 加进 `sys.path` 也不行（C 扩展对不上）。存图用 Blender 自己的 image datablock。

## 文件

| 文件 | 作用 | 依赖 |
| --- | --- | --- |
| `tools/pmx_render.py` | 导入 PMX、修贴图路径、三点光、渲一张 | Blender + mmd_tools |
| `tools/mtr_render.py` | 走 MMD Template Renderer 的 CHECK→APPLY→RENDER | Blender + 两个扩展 |
| `tools/bl2ai_masked.py` | ComfyUI 分区 img2img（上传 → mask → 采样 → 回传） | Python + Pillow + 本地 ComfyUI |
| `tools/depth_raycast.py` | 光线投射出深度图（近白远黑） | Blender 自带 numpy |

脚本里的路径全部是参数或环境变量，没有硬编码目录。

## 复现前提

- Blender 4.x / 5.x + `mmd_tools` 扩展（4.2 以后的扩展 ID 是 `bl_ext.blender_org.mmd_tools`）。
- 本地 ComfyUI，装有 ControlNet union SDXL 与对应 checkpoint。
- 模型与贴图不入仓：MMD 模型的再分发许可各不相同，使用前自行确认。

## 边界

- 这条线**没有现成社区配方**。公开资料里能找到的是「Blender 渲白模 + ControlNet」和「img2img 换画风」，把 MMD 角色直接接进去的完整流程没有现成教程。
- 材质质感的瓶颈在模型对 PBR、各向异性高光、次表面散射的理解，不在分辨率。
- **角色设计细节必须由 mask 与 denoise 保护**。AI 会把鞋扣、绑带、内衬这类小件按自己的先验重画；验收时逐项比对，不要只看脸。

## 与 saya-imagegen 的关系

两边共用同一套画风判据（材质高光、光影分层、denoise 上界）；区别是这里多了「可控的几何与光影输入」。纯 2D 生成线见 [`saya-imagegen`](https://github.com/sayasaikou/saya-imagegen)。

## 许可

MIT。Blender、mmd_tools、MMD Template Renderer 与各 MMD 模型遵循其各自的原始许可。
