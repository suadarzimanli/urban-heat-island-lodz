"""Unit tests for the pipeline library:  python -m unittest discover -s pipeline"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import uhi  # noqa: E402


class Conversions(unittest.TestCase):
    def test_landsat_surface_temperature(self):
        # USGS: K = DN × 0.00341802 + 149.0; DN 0 is fill
        dn = np.array([0, 44177])
        t = uhi.landsat_lst_celsius(dn)
        self.assertTrue(np.isnan(t[0]))
        self.assertAlmostEqual(t[1], 44177 * 0.00341802 + 149.0 - 273.15, places=6)

    def test_qa_mask_rejects_cloud_shadow_and_fill(self):
        clear_land = 21824  # Collection 2 value for clear land
        cloud = clear_land | (1 << 3)
        shadow = clear_land | (1 << 4)
        fill = 1
        self.assertEqual(uhi.landsat_clear(np.array([clear_land, cloud, shadow, fill])).tolist(), [True, False, False, False])

    def test_temperature_from_radiance_inverts_planck(self):
        # a blackbody (ε = 1) seen through a perfect atmosphere (τ = 1, no path radiance) returns its own temperature
        k1, k2 = 774.8853, 1321.0789
        t_k = 300.0
        radiance = k1 / (np.exp(k2 / t_k) - 1)
        one = np.array([1.0])
        t = uhi.surface_temperature_from_radiance(np.array([radiance]), 0 * one, 0 * one, one, one, k1, k2)
        self.assertAlmostEqual(float(t[0]), t_k - 273.15, places=6)

    def test_emissivity_from_ndvi_interpolates_bins(self):
        rng = np.random.default_rng(0)
        nd = rng.uniform(0, 0.8, 5000)
        em = 0.95 + 0.04 * nd
        est = uhi.emissivity_from_ndvi(nd, em, np.array([0.1, 0.7, np.nan]))
        self.assertAlmostEqual(float(est[0]), 0.954, places=3)
        self.assertAlmostEqual(float(est[1]), 0.978, places=3)
        self.assertTrue(np.isnan(est[2]))

    def test_ndvi(self):
        self.assertAlmostEqual(float(uhi.ndvi(np.array([0.1]), np.array([0.5]))[0]), 0.4 / 0.6)
        self.assertTrue(np.isnan(uhi.ndvi(np.array([0.0]), np.array([0.0]))[0]))


class Cells(unittest.TestCase):
    def test_500m_cells_hold_50x50_pixels(self):
        ids, nr, nc = uhi.cell_index((120, 230), 500)
        self.assertEqual((nr, nc), (3, 5))
        self.assertEqual(int((ids == 0).sum()), 50 * 50)
        self.assertEqual(int(ids[0, 49]), 0)
        self.assertEqual(int(ids[0, 50]), 1)
        self.assertEqual(int(ids[50, 0]), nc)

    def test_cell_size_must_divide(self):
        with self.assertRaises(ValueError):
            uhi.cell_index((10, 10), 25)

    def test_zonal_mean_ignores_missing_values(self):
        ids = np.array([[0, 0, 1, 1]])
        v = np.array([[1.0, np.nan, 2.0, 4.0]])
        mean, cnt = uhi.zonal_mean(v, ids, 2)
        self.assertEqual(mean.tolist(), [1.0, 3.0])
        self.assertEqual(cnt.tolist(), [1.0, 2.0])

    def test_zonal_fraction(self):
        ids = np.array([[0, 0, 1, 1]])
        self.assertEqual(uhi.zonal_fraction(np.array([[True, False, True, True]]), ids, 2).tolist(), [0.5, 1.0])


class Statistics(unittest.TestCase):
    def setUp(self):
        r, c = np.meshgrid(np.arange(12), np.arange(12), indexing="ij")
        self.rows, self.cols = r.ravel(), c.ravel()
        self.nbrs = uhi.rook_neighbours(self.rows, self.cols)

    def test_ols_recovers_line(self):
        x = np.linspace(0, 1, 50)
        m = uhi.ols(x[:, None], 40 - 10 * x)
        self.assertAlmostEqual(m["beta"][1], -10)
        self.assertAlmostEqual(m["r2"], 1.0)

    def test_neighbours(self):
        self.assertEqual(len(self.nbrs[0]), 2)  # corner
        self.assertEqual(len(self.nbrs[13]), 4)  # interior
        self.assertEqual(len(uhi.rook_neighbours(self.rows, self.cols, queen=True)[13]), 8)

    def test_morans_i_detects_clustering_and_not_noise(self):
        smooth = (self.cols >= 6).astype(float)  # two halves
        self.assertGreater(uhi.morans_i(smooth, self.nbrs, 199)["I"], 0.8)
        self.assertLess(uhi.morans_i(smooth, self.nbrs, 199)["p"], 0.01)
        noise = np.random.default_rng(3).normal(size=len(self.rows))
        self.assertGreater(uhi.morans_i(noise, self.nbrs, 199)["p"], 0.05)

    def test_gi_star_finds_a_hot_block(self):
        x = np.zeros(len(self.rows))
        hot = (self.rows < 3) & (self.cols < 3)
        x[hot] = 5
        z = uhi.getis_ord_gi_star(x, uhi.rook_neighbours(self.rows, self.cols, queen=True))
        self.assertGreater(z[hot].min(), 1.96)
        self.assertLess(z[(self.rows > 6) & (self.cols > 6)].max(), 0)

    def test_fdr(self):
        p = np.array([0.001, 0.01, 0.02, 0.5, 0.9])
        self.assertEqual(uhi.fdr_mask(p, 0.05).tolist(), [True, True, True, False, False])

    def test_blocked_cv_close_to_in_sample_for_a_true_line(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(0, 1, 400)
        y = 3 * x + rng.normal(0, 0.1, 400)
        blocks = np.arange(400) // 20
        self.assertGreater(uhi.blocked_cv_r2(x[:, None], y, blocks), 0.95)


if __name__ == "__main__":
    unittest.main()
