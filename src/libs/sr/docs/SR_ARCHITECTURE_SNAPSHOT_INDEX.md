# S/R Architecture Snapshot Index

Use this note when context is thin and you need a stable entry point into the current Support/Resistance design.

## 1. Reading Order

Start here, then read in this order:

1. [ARCHITECTURE_DEEP_DIVE.md](ARCHITECTURE_DEEP_DIVE.md)
2. [QUALIFICATION_AND_OPTIMIZATION_DEEP_DIVE.md](QUALIFICATION_AND_OPTIMIZATION_DEEP_DIVE.md)
3. [README.md](README.md)
4. [OPTIMIZATION.md](OPTIMIZATION.md)
5. [KERNEL_REFERENCE.md](KERNEL_REFERENCE.md)

## 2. What Each Document Owns

- [ARCHITECTURE_DEEP_DIVE.md](ARCHITECTURE_DEEP_DIVE.md): runtime architecture, config cascade, router, sidecar, pipeline, state boundaries, and runtime data travel.
- [QUALIFICATION_AND_OPTIMIZATION_DEEP_DIVE.md](QUALIFICATION_AND_OPTIMIZATION_DEEP_DIVE.md): qualification, Stage 1, Stage 2, staleness, writeback semantics, and optimization-specific nuances.
- [README.md](README.md): module map and high-level surface area.
- [OPTIMIZATION.md](OPTIMIZATION.md): reference view of the optimizer surface and evaluation stack.
- [KERNEL_REFERENCE.md](KERNEL_REFERENCE.md): per-kernel structural needs, strengths, weaknesses, and knobs.

## 3. Source Files Most Often Needed In Handoffs

- [app/sr/universe/router.py](../universe/router.py)
- [app/sr/config_resolver.py](../config_resolver.py)
- [app/sr/sidecar/daemon.py](../sidecar/daemon.py)
- [app/sr/pipeline.py](../pipeline.py)
- [app/sr/qualification/screener.py](../qualification/screener.py)
- [app/sr/qualification/qualifier.py](../qualification/qualifier.py)
- [app/sr/optimization/universe_optimizer.py](../optimization/universe_optimizer.py)
- [app/sr/optimization/asset_optimizer.py](../optimization/asset_optimizer.py)
- [app/sr/optimization/two_stage_optimizer.py](../optimization/two_stage_optimizer.py)
- [app/sr/config/sr.yaml](../config/sr.yaml)

## 4. Current Snapshot Themes

If you only remember five things, remember these:

- the runtime resolver is data-light and sidecar-backed,
- deterministic microstructure math is owned by the sidecar, not by the live router,
- kernels are stateless while pipeline and lifecycle are stateful,
- qualification is relative rather than absolute,
- optimization is two-stage and persists `_optimization_meta` separately from sidecar `_profiler_meta`.