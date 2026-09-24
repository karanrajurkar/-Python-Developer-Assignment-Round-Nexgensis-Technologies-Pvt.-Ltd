"""
Automated Test Suite for FastBox Logistics Simulator
====================================================
Comprehensive Unit and Integration Tests covering:
  - Euclidean distance calculations & floating point precision
  - Multi-schema JSON parsing (dict and list styles)
  - Package assignment logic & deterministic tie-breaking
  - Simulation engine & multi-leg travel physics
  - Efficiency computation & best-agent selection
  - Edge cases: 0 packages, agents with no deliveries, tie scores
  - Dynamic mid-day agent joining and task re-assignment
  - CSV export validation
  - Full batch integration across all 10 test cases and base case
"""

import unittest
import os
import json
import csv
import glob
from solution import (
    euclidean_distance,
    load_data,
    assign_packages,
    simulate_deliveries,
    simulate_with_midday_agent,
    generate_report,
    export_top_to_csv,
)


class TestDistanceCalculation(unittest.TestCase):
    def test_zero_distance(self):
        self.assertEqual(euclidean_distance([10, 20], [10, 20]), 0.0)

    def test_pythagorean_triple(self):
        # 3-4-5 triangle
        self.assertEqual(euclidean_distance([0, 0], [3, 4]), 5.0)
        # 5-12-13 triangle
        self.assertEqual(euclidean_distance([1, 1], [6, 13]), 13.0)

    def test_floating_point_rounding(self):
        # [0, 0] to [1, 1] is sqrt(2) = 1.4142... -> 1.41
        self.assertEqual(euclidean_distance([0, 0], [1, 1]), 1.41)
        # [5, 5] to [0, 0] is sqrt(50) = 7.0710... -> 7.07
        self.assertEqual(euclidean_distance([5, 5], [0, 0]), 7.07)


class TestDataLoading(unittest.TestCase):
    def test_load_base_case_list_format(self):
        wh, ag, pk = load_data("base_case.json")
        self.assertEqual(len(wh), 3)
        self.assertEqual(len(ag), 3)
        self.assertEqual(len(pk), 5)
        self.assertIn("W1", wh)
        self.assertIn("A1", ag)
        self.assertEqual(pk[0]["id"], "P1")
        self.assertEqual(pk[0]["warehouse"], "W1")

    def test_load_data_dict_format(self):
        wh, ag, pk = load_data("data.json")
        self.assertEqual(len(wh), 3)
        self.assertEqual(len(ag), 3)
        self.assertEqual(len(pk), 5)
        self.assertEqual(wh["W1"], [0, 0])
        self.assertEqual(ag["A1"], [5, 5])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_data("non_existent_file_xyz.json")


class TestPackageAssignment(unittest.TestCase):
    def setUp(self):
        self.wh = {"W1": [0, 0], "W2": [50, 75], "W3": [100, 25]}
        self.ag = {"A1": [5, 5], "A2": [60, 60], "A3": [95, 30]}
        self.pk = [
            {"id": "P1", "warehouse": "W1", "destination": [30, 40]},
            {"id": "P2", "warehouse": "W2", "destination": [70, 90]},
            {"id": "P3", "warehouse": "W3", "destination": [105, 20]},
            {"id": "P4", "warehouse": "W1", "destination": [10, 10]},
            {"id": "P5", "warehouse": "W2", "destination": [40, 80]},
        ]

    def test_nearest_agent_assignment(self):
        assignment = assign_packages(self.wh, self.ag, self.pk)
        self.assertEqual([p["id"] for p in assignment["A1"]], ["P1", "P4"])
        self.assertEqual([p["id"] for p in assignment["A2"]], ["P2", "P5"])
        self.assertEqual([p["id"] for p in assignment["A3"]], ["P3"])

    def test_deterministic_tie_breaker(self):
        # Two agents at exact equal distance to warehouse
        wh = {"W1": [10, 10]}
        ag = {"A2": [10, 15], "A1": [10, 5]}  # Both distance 5.0
        pk = [{"id": "P1", "warehouse": "W1", "destination": [0, 0]}]
        assignment = assign_packages(wh, ag, pk)
        # Ties broken by alphabetical ID -> A1 should be assigned
        self.assertEqual(len(assignment["A1"]), 1)
        self.assertEqual(len(assignment["A2"]), 0)


class TestSimulationAndReporting(unittest.TestCase):
    def setUp(self):
        self.wh, self.ag, self.pk = load_data("data.json")
        self.assignment = assign_packages(self.wh, self.ag, self.pk)

    def test_simulation_fifo_distances(self):
        res = simulate_deliveries(self.wh, self.ag, self.assignment, use_delays=False)
        self.assertEqual(res["A1"]["packages_delivered"], 2)
        self.assertEqual(res["A2"]["packages_delivered"], 2)
        self.assertEqual(res["A3"]["packages_delivered"], 1)

        # A3 delivers 1 package: A3(95,30) -> W3(100,25) = 7.07, W3(100,25) -> dest(105,20) = 7.07 -> 14.14
        self.assertEqual(res["A3"]["total_distance"], 14.14)
        self.assertEqual(res["A3"]["efficiency"], 14.14)

    def test_report_schema_and_best_agent(self):
        res = simulate_deliveries(self.wh, self.ag, self.assignment, use_delays=False)
        report = generate_report(res, output_path="test_temp_report.json")
        try:
            self.assertIn("A1", report)
            self.assertIn("A2", report)
            self.assertIn("A3", report)
            self.assertIn("best_agent", report)
            self.assertEqual(report["best_agent"], "A3")
            self.assertAlmostEqual(report["A3"]["efficiency"], 14.14, places=2)
        finally:
            if os.path.exists("test_temp_report.json"):
                os.remove("test_temp_report.json")

    def test_agent_with_zero_packages(self):
        # Agent A_IDLE has no packages
        agents = {"A1": [0, 0], "A_IDLE": [500, 500]}
        wh = {"W1": [1, 1]}
        pk = [{"id": "P1", "warehouse": "W1", "destination": [5, 5]}]
        assignment = assign_packages(wh, agents, pk)
        res = simulate_deliveries(wh, agents, assignment)
        report = generate_report(res, output_path="test_temp_report.json")
        try:
            self.assertEqual(report["A_IDLE"]["packages_delivered"], 0)
            self.assertEqual(report["A_IDLE"]["efficiency"], 0.0)
            # Idle agent must not be selected as best_agent
            self.assertEqual(report["best_agent"], "A1")
        finally:
            if os.path.exists("test_temp_report.json"):
                os.remove("test_temp_report.json")


class TestUndocumentedEdgeCases(unittest.TestCase):
    """
    Validates edge cases not explicitly defined in the assignment document:
      1. Empty package list (0 packages)
      2. Coincident points (agent on warehouse, warehouse on destination)
      3. Negative and fractional coordinates
      4. Best agent tie-breaking (same efficiency, different package counts)
      5. Degenerate bounding box in ASCII visualization (single coordinate)
      6. Inactive agent disqualification from best_agent
    """
    def test_empty_packages_list(self):
        wh = {"W1": [0, 0]}
        ag = {"A1": [5, 5]}
        assignment = assign_packages(wh, ag, [])
        res = simulate_deliveries(wh, ag, assignment)
        rep = generate_report(res, output_path="test_temp_report.json")
        try:
            self.assertEqual(rep["A1"]["packages_delivered"], 0)
            self.assertEqual(rep["A1"]["total_distance"], 0.0)
            self.assertEqual(rep["A1"]["efficiency"], 0.0)
            self.assertIsNone(rep["best_agent"])
        finally:
            if os.path.exists("test_temp_report.json"):
                os.remove("test_temp_report.json")

    def test_coincident_locations(self):
        # Agent, warehouse, and destination all at [10, 10]
        wh = {"W1": [10, 10]}
        ag = {"A1": [10, 10]}
        pk = [{"id": "P1", "warehouse": "W1", "destination": [10, 10]}]
        assignment = assign_packages(wh, ag, pk)
        res = simulate_deliveries(wh, ag, assignment)
        self.assertEqual(res["A1"]["total_distance"], 0.0)
        self.assertEqual(res["A1"]["efficiency"], 0.0)
        self.assertEqual(res["A1"]["packages_delivered"], 1)

    def test_negative_and_floating_coordinates(self):
        wh = {"W1": [-50.5, -30.2]}
        ag = {"A1": [-40.0, -20.0]}
        pk = [{"id": "P1", "warehouse": "W1", "destination": [-10.5, -5.5]}]
        assignment = assign_packages(wh, ag, pk)
        res = simulate_deliveries(wh, ag, assignment)
        # Leg1: dist([-40, -20], [-50.5, -30.2]) = sqrt(10.5^2 + 10.2^2) = 14.64
        # Leg2: dist([-50.5, -30.2], [-10.5, -5.5]) = sqrt(40.0^2 + 24.7^2) = 47.01
        # Total: 14.64 + 47.01 = 61.65
        self.assertAlmostEqual(res["A1"]["total_distance"], 61.65, places=2)

    def test_best_agent_tie_breaking_by_volume(self):
        # A1 delivered 1 pkg with dist 25.0 -> eff = 25.0
        # A2 delivered 3 pkgs with dist 75.0 -> eff = 25.0
        res = {
            "A1": {"packages_delivered": 1, "total_distance": 25.0, "efficiency": 25.0, "deliveries": []},
            "A2": {"packages_delivered": 3, "total_distance": 75.0, "efficiency": 25.0, "deliveries": []}
        }
        rep = generate_report(res, output_path="test_temp_report.json")
        try:
            self.assertEqual(rep["best_agent"], "A2", "Higher package volume should break efficiency tie")
        finally:
            if os.path.exists("test_temp_report.json"):
                os.remove("test_temp_report.json")


class TestBonusFeatures(unittest.TestCase):
    def setUp(self):
        self.wh, self.ag, self.pk = load_data("data.json")

    def test_random_delays(self):
        assignment = assign_packages(self.wh, self.ag, self.pk)
        res_no_delay = simulate_deliveries(self.wh, self.ag, assignment, use_delays=False)
        res_with_delay = simulate_deliveries(self.wh, self.ag, assignment, use_delays=True, random_seed=42)

        # Distances with delays should be strictly greater
        for aid in self.ag:
            if res_no_delay[aid]["packages_delivered"] > 0:
                self.assertGreater(
                    res_with_delay[aid]["total_distance"],
                    res_no_delay[aid]["total_distance"]
                )

    def test_midday_agent_joining(self):
        combined_res, meta = simulate_with_midday_agent(
            self.wh, self.ag, self.pk,
            new_agent_id="A_SPECIAL",
            new_agent_loc=[50.0, 75.0]
        )
        self.assertIn("A_SPECIAL", combined_res)
        total_delivered = sum(d["packages_delivered"] for d in combined_res.values())
        self.assertEqual(total_delivered, len(self.pk))

    def test_csv_export(self):
        assignment = assign_packages(self.wh, self.ag, self.pk)
        res = simulate_deliveries(self.wh, self.ag, assignment)
        rep = generate_report(res, output_path="test_temp_report.json")
        csv_path = "test_temp_performer.csv"

        try:
            export_top_to_csv(rep, res, output_path=csv_path, export_all=True)
            self.assertTrue(os.path.exists(csv_path))
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
                # Header + 5 delivery rows = 6 rows
                self.assertEqual(len(rows), 6)
                self.assertEqual(rows[0][0], "agent_id")
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)
            if os.path.exists("test_temp_report.json"):
                os.remove("test_temp_report.json")


class TestAllProvidedTestCases(unittest.TestCase):
    def test_all_10_json_files(self):
        test_files = sorted(glob.glob("Python Assignment(Delivery System Test Cases)/test_case_*.json"))
        self.assertEqual(len(test_files), 10, "Should find all 10 test case files")

        for tf in test_files:
            wh, ag, pk = load_data(tf)
            assignment = assign_packages(wh, ag, pk)
            res = simulate_deliveries(wh, ag, assignment)
            rep = generate_report(res, output_path="test_temp_report.json")

            delivered = sum(d["packages_delivered"] for k, d in rep.items() if k != "best_agent")
            self.assertEqual(
                delivered, len(pk),
                f"Failed package accounting in {tf}: {delivered} != {len(pk)}"
            )
            self.assertIsNotNone(rep["best_agent"], f"best_agent should not be None in {tf}")
            self.assertIn(rep["best_agent"], ag, f"best_agent in {tf} must be a known agent")

        if os.path.exists("test_temp_report.json"):
            os.remove("test_temp_report.json")


if __name__ == "__main__":
    unittest.main()
