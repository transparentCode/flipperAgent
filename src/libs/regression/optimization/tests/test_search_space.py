"""Tests for V2 search space builder: tier merging, deduplication, bounds."""
from app.regression.config.schema import OrchestratorConfig, OptimizationTier
from app.regression.optimization.models import RegressionOptimizationConfig
from app.regression.optimization.search_space import SearchSpaceBuilder


class TestSearchSpaceBuilder:
    def setup_method(self):
        self.builder = SearchSpaceBuilder()
        self.orch = OrchestratorConfig()
        self.opt = RegressionOptimizationConfig()

    def test_global_tier(self):
        specs = self.builder.build(self.orch, OptimizationTier.GLOBAL, self.opt)
        names = [s.name for s in specs]
        assert "band_multiplier" in names
        assert "trend_atr_fraction" in names
        assert "window_size" not in names  # window_size is per_tf
        assert len(specs) == 5

    def test_per_tf_tier(self):
        specs = self.builder.build(self.orch, OptimizationTier.PER_TF, self.opt)
        names = [s.name for s in specs]
        assert "window_size" in names
        assert "slope_acceleration_alpha" in names
        assert len(specs) == 4

    def test_full_tier_merge(self):
        specs = self.builder.build_merged(
            self.orch,
            [OptimizationTier.GLOBAL, OptimizationTier.PER_TF],
            self.opt,
        )
        names = [s.name for s in specs]
        # 5 global + 4 per_tf, no overlaps
        assert len(specs) == 9
        assert "band_multiplier" in names
        assert "window_size" in names
        assert "methods.theil_sen.weight" in names

    def test_deduplication(self):
        """window_size appears in both per_tf and per_asset; should only appear once."""
        specs = self.builder.build_merged(
            self.orch,
            [OptimizationTier.PER_TF, OptimizationTier.PER_ASSET],
            self.opt,
        )
        ws_count = sum(1 for s in specs if s.name == "window_size")
        assert ws_count == 1

    def test_band_multiplier_bounds_aligned(self):
        specs = self.builder.build(self.orch, OptimizationTier.GLOBAL, self.opt)
        bm = [s for s in specs if s.name == "band_multiplier"][0]
        assert bm.high == 2.5  # Aligned with models default
        assert bm.low == 1.5

    def test_custom_bounds_override(self):
        opt = RegressionOptimizationConfig(
            param_bounds={"band_multiplier": (2.0, 5.0)},
        )
        specs = self.builder.build(self.orch, OptimizationTier.GLOBAL, opt)
        bm = [s for s in specs if s.name == "band_multiplier"][0]
        assert bm.low == 2.0
        assert bm.high == 5.0

    def test_window_size_is_int(self):
        specs = self.builder.build(self.orch, OptimizationTier.PER_TF, self.opt)
        ws = [s for s in specs if s.name == "window_size"][0]
        assert ws.param_type == "int"
