"""
Unit tests for MITRE ATT&CK mapping utilities.
"""

import unittest

from forecasting.config import AttackStage
from forecasting.mitre_mapping import (
    MITRETechnique,
    MITRE_STAGE_MAPPING,
    map_stage_to_techniques,
    map_forecast_to_mitre,
)


class TestMITRETechnique(unittest.TestCase):

    def test_to_dict(self):
        t = MITRETechnique(
            technique_id="T1595",
            name="Active Scanning",
            tactic="Reconnaissance",
            description="Example description",
            severity="MEDIUM",
        )
        d = t.to_dict()
        self.assertEqual(d["technique_id"], "T1595")
        self.assertEqual(d["severity"], "MEDIUM")
        self.assertIn("name", d)
        self.assertIn("tactic", d)
        self.assertIn("description", d)


class TestMapStageToTechniques(unittest.TestCase):

    def test_normal_has_no_techniques(self):
        techniques = map_stage_to_techniques(AttackStage.NORMAL)
        self.assertEqual(techniques, [])

    def test_recon_has_techniques(self):
        techniques = map_stage_to_techniques(AttackStage.RECON)
        self.assertGreater(len(techniques), 0)
        ids = {t.technique_id for t in techniques}
        self.assertIn("T1595", ids)  # Active Scanning

    def test_escalation_has_techniques(self):
        techniques = map_stage_to_techniques(AttackStage.ESCALATION)
        self.assertGreater(len(techniques), 0)
        ids = {t.technique_id for t in techniques}
        self.assertIn("T1498", ids)  # Network DoS (Preparation)

    def test_surge_has_techniques(self):
        techniques = map_stage_to_techniques(AttackStage.SURGE)
        self.assertGreater(len(techniques), 0)
        ids = {t.technique_id for t in techniques}
        self.assertIn("T1499", ids)  # Endpoint DoS

    def test_sustained_has_critical_severity(self):
        techniques = map_stage_to_techniques(AttackStage.SUSTAINED)
        self.assertGreater(len(techniques), 0)
        self.assertTrue(
            any(t.severity == "CRITICAL" for t in techniques),
            "SUSTAINED stage should contain CRITICAL severity techniques",
        )

    def test_unknown_stage_returns_empty(self):
        techniques = map_stage_to_techniques(999)
        self.assertEqual(techniques, [])

    def test_all_techniques_are_mitre_objects(self):
        for stage, techs in MITRE_STAGE_MAPPING.items():
            for t in techs:
                self.assertIsInstance(t, MITRETechnique)
                self.assertTrue(t.technique_id.startswith("T"))


class TestMapForecastToMitre(unittest.TestCase):

    def test_empty_forecast(self):
        timeline = map_forecast_to_mitre([])
        self.assertEqual(timeline, [])

    def test_single_step_normal(self):
        timeline = map_forecast_to_mitre([0])
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertEqual(entry["step"], 1)
        self.assertEqual(entry["horizon_label"], "t+1")
        self.assertEqual(entry["stage"], 0)
        self.assertEqual(entry["stage_name"], "NORMAL")
        self.assertEqual(entry["max_severity"], "INFO")
        self.assertEqual(entry["techniques"], [])

    def test_multi_step_escalation(self):
        forecast = [1, 2, 3]  # RECON -> ESCALATION -> SURGE
        timeline = map_forecast_to_mitre(forecast)
        self.assertEqual(len(timeline), 3)

        # Step 1: RECON
        self.assertEqual(timeline[0]["stage_name"], "RECON")
        self.assertEqual(timeline[0]["max_severity"], "MEDIUM")

        # Step 2: ESCALATION
        self.assertEqual(timeline[1]["stage_name"], "ESCALATION")
        self.assertEqual(timeline[1]["max_severity"], "HIGH")

        # Step 3: SURGE
        self.assertEqual(timeline[2]["stage_name"], "SURGE")
        self.assertEqual(timeline[2]["max_severity"], "HIGH")

    def test_sustained_forecast_yields_critical(self):
        timeline = map_forecast_to_mitre([4, 4])
        for entry in timeline:
            self.assertEqual(entry["max_severity"], "CRITICAL")

    def test_step_numbering(self):
        timeline = map_forecast_to_mitre([0, 1, 2, 3, 4])
        for idx, entry in enumerate(timeline, start=1):
            self.assertEqual(entry["step"], idx)
            self.assertEqual(entry["horizon_label"], f"t+{idx}")

    def test_techniques_serialized_as_dicts(self):
        timeline = map_forecast_to_mitre([3])
        for tech_dict in timeline[0]["techniques"]:
            self.assertIsInstance(tech_dict, dict)
            self.assertIn("technique_id", tech_dict)
            self.assertIn("name", tech_dict)
            self.assertIn("severity", tech_dict)


if __name__ == "__main__":
    unittest.main()
