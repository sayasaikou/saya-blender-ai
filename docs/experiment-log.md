# Blender 线实验记录

> 按时间顺序列出做过什么、参数、结果与结论。脚本不全部入仓（很多是同一实验的中间迭代），但参数足够复跑。

## 一、资产准备

### E1 MMD 模型入库

- 10 个 PMX / 9 个角色；导入后一个个检查：贴图缺失、公共贴图缺号、眼睛材质错误。
- 结论：每个作者包的目录结构都不一样，必须写一个检查脚本（`tools/mmd_inspect.py`）先看节点组与材质，再谈渲染。

### E2 贴图路径修复

- PMX 里写的是作者机器的绝对路径；导入后全部变成粉色/黑色。
- 做法：按前缀重映射（`--tex-from` / `--tex-to`），不按文件名猜。
- 结果：材质正常显示；但仍有 `T_actor_common_*` 缺失 —— 从同系列其他角色拷，**同号对同号**。

## 二、材质升级的四条路（三条失败）

### E3 硬换 Principled BSDF（失败）

- 做法：断开 MMD 的 toon 输出，改接 Principled；乘 1.35 提亮；程序化噪声做粗糙度与 bump；皮肤加 0.12 的 SSS。
- 结果：发黑、斑驳、高光碎裂。
- 根因：MMD 的 diffuse 贴图**烘了光照**，不是纯 albedo。当 albedo 用时，阴影与 AO 被叠了两遍。
- 参考实现：`tools/mat_upgrade.py`（保留作为反例，不要直接用于交付）。

### E4 保留 toon 颜色链，只在节点组内叠 bump（效果不够）

- 做法：不动 MMDShaderDev 组的外部连线，只在组内给 Diffuse BSDF 加一个 noise → bump。
- 结果：不崩，但提升微乎其微；后续低 denoise 重绘又把它稀释掉。
- 结论：**在 toon 链上打补丁，不如把材质交给 AI**。

### E5 换 Cycles（失败）

- 做法：EEVEE → Cycles，加 AgX、HDRI、面部补光，灯光能量按比例降。
- 结果：真实感有了，但红伞反弹过曝、脸被压黑。
- 根因：32 盏灯是按 EEVEE 调的；换渲染器后能量与弹射全部变化。补到能看时只能打平 EEVEE，成本不值得。

### E6 模板渲染器（能跑但不够）

- 做法：MMD Template Renderer 的 CHECK → APPLY → RENDER，SUN 主光 + POINT 补光。
- 前置：补公共贴图、`iris_mode=RAW_A`、手动补 `Cloth*` 材质映射（正则只认 `Cloth\d+(Alpha)?`）。
- 结果：流程通，质感偏平，没有卡渲渐变与描边。

## 三、AI 重绘实验

### E7 分区重绘 v1 → v3

| 版本 | 变化 | 结果 |
| --- | --- | --- |
| v1 | 全图 img2img，denoise 0.5，CN tile | 结构漂、画风有变、脸换人 |
| v2 | 加 mask 锁头部 | 脸保住，但头发质感被固定 |
| v3 | **只锁脸**，denoise 0.35–0.40，CN 换 lineart 0.6 | 最佳：脸与设计细节保留，衣服与背景材质提升 |

### E8 链式低 denoise（3 × 0.15）

- 做法：连续三次低 denoise 重绘，每次都带 tile ControlNet 锁结构。
- 结果：身份稳定，但画风提升近乎为零。
- 结论：**保身份与提画风是同一个旋钮**，分几次做也拆不开。

### E9 ControlNet 选型

- `lineart` 0.6：可用，结构锁得住、材质能改。
- `tile`：把底图色块一起锁进去，结果改脸、发脏。
- `canny`：结构锁得住，但边缘太硬，重绘后线条发脏。

### E10 更大模型 + 细节 LoRA + hires

- 做法：换 2B 级模型，加材质 LoRA，hires fix。
- 结果：材质完成度自评 7.5/10（参考图记 10）。
- 结论：瓶颈是模型对材质与光的理解，不是分辨率或 LoRA 强度。

## 四、深度图（给 ControlNet）

### E11 四条常规路全不通（实测）

`color_type='DEPTH'`、`CompositorNodeRLayers`、`RenderSlot.z`、多层 EXR 全部不可用（详见 README）。

### E12 光线投射（可用）

- 做法：相机内外参 → 每像素一条射线 → `scene.ray_cast()` 量距离；近白远黑输出。
- 提速：先 1/2 降采样算，再上采样；1334×768 的网格约数十秒。
- 两个坑：相机矩阵必须先 `view_layer.update()`；Blender 自带 Python 没有 PIL。
- 实现：`tools/depth_raycast.py`。

## 五、待复跑

| 项 | 原因 |
| --- | --- |
| 用 PBR 底图（非 toon）重试 Principled | 避免 diffuse 烘光导致的二次叠影 |
| 分区 mask 的毛发边界细分 | 目前只能整块锁或不锁 |
| 不同 EEVEE 采样/光比下的重绘稳定性 | 只试过一套灯光 |
