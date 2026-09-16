"""
MITRE ATT&CK framework mapping for attack stages and multi-step forecasts.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from forecasting.config import AttackStage, STAGE_NAMES


@dataclass
class MITRETechnique:
    """Represents a specific MITRE ATT&CK technique."""

    technique_id: str
    name: str
    tactic: str
    description: str
    severity: str  # "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


# Comprehensive taxonomy mapping Attack Stages to MITRE ATT&CK techniques
MITRE_STAGE_MAPPING: Dict[int, List[MITRETechnique]] = {
    AttackStage.NORMAL: [],
    AttackStage.RECON: [
        MITRETechnique(
            technique_id="T1595",
            name="Active Scanning",
            tactic="Reconnaissance",
            description="Adversaries scan public IP blocks and endpoints to gather vulnerability or routing information.",
            severity="MEDIUM",
        ),
        MITRETechnique(
            technique_id="T1046",
            name="Network Service Discovery",
            tactic="Discovery",
            description="Probing ports and listening services to enumerate proxy and backend routes.",
            severity="MEDIUM",
        ),
        MITRETechnique(
            technique_id="T1592",
            name="Gather Victim Host Information",
            tactic="Reconnaissance",
            description="Querying system endpoints and response headers to identify software stack.",
            severity="LOW",
        ),
    ],
    AttackStage.ESCALATION: [
        MITRETechnique(
            technique_id="T1110",
            name="Brute Force",
            tactic="Credential Access",
            description="Systematically submitting passwords or tokens across authentication routes.",
            severity="HIGH",
        ),
        MITRETechnique(
            technique_id="T1078",
            name="Valid Accounts",
            tactic="Defense Evasion",
            description="Utilizing harvested credentials or tokens to bypass standard rate limiters.",
            severity="HIGH",
        ),
        MITRETechnique(
            technique_id="T1498",
            name="Network Denial of Service (Preparation)",
            tactic="Impact",
            description="Ramping request frequency and thread concurrency prior to full volumetric saturation.",
            severity="HIGH",
        ),
    ],
    AttackStage.SURGE: [
        MITRETechnique(
            technique_id="T1498",
            name="Network Denial of Service",
            tactic="Impact",
            description="Volumetric flooding of proxy endpoints degrading server network capacity.",
            severity="HIGH",
        ),
        MITRETechnique(
            technique_id="T1499",
            name="Endpoint Denial of Service",
            tactic="Impact",
            description="Targeting compute-heavy application routes to starve CPU, memory, or connection pools.",
            severity="HIGH",
        ),
        MITRETechnique(
            technique_id="T1496",
            name="Resource Hijacking",
            tactic="Impact",
            description="Saturating available proxy bandwidth and worker goroutines.",
            severity="HIGH",
        ),
    ],
    AttackStage.SUSTAINED: [
        MITRETechnique(
            technique_id="T1498.001",
            name="Direct Network Flood",
            tactic="Impact",
            description="Protracted high-volume packet and HTTP flood targeting proxy listeners across consecutive windows.",
            severity="CRITICAL",
        ),
        MITRETechnique(
            technique_id="T1499.001",
            name="OS Exhaustion Flood",
            tactic="Impact",
            description="Sustained connection floods causing file descriptor or TCP socket backlog depletion.",
            severity="CRITICAL",
        ),
        MITRETechnique(
            technique_id="T1499.002",
            name="Service Exhaustion Flood",
            tactic="Impact",
            description="Persistent request bombardment preventing regular clients from reaching backend services.",
            severity="CRITICAL",
        ),
    ],
}


def map_stage_to_techniques(stage: int) -> List[MITRETechnique]:
    """Retrieve MITRE ATT&CK techniques associated with a single attack stage."""
    return MITRE_STAGE_MAPPING.get(stage, [])


def map_forecast_to_mitre(forecast: List[int]) -> List[Dict[str, Any]]:
    """
    Map an ordered future forecast trajectory [t+1, t+2, t+3, ...] to MITRE ATT&CK techniques.
    Returns a timeline structure with stage labels and applicable techniques per step.
    """
    timeline: List[Dict[str, Any]] = []

    for step_idx, stage in enumerate(forecast, start=1):
        stage_int = int(stage)
        techniques = map_stage_to_techniques(stage_int)
        max_severity = "INFO"
        if any(t.severity == "CRITICAL" for t in techniques):
            max_severity = "CRITICAL"
        elif any(t.severity == "HIGH" for t in techniques):
            max_severity = "HIGH"
        elif any(t.severity == "MEDIUM" for t in techniques):
            max_severity = "MEDIUM"
        elif any(t.severity == "LOW" for t in techniques):
            max_severity = "LOW"

        step_entry: Dict[str, Any] = {
            "step": step_idx,
            "horizon_label": f"t+{step_idx}",
            "stage": stage_int,
            "stage_name": STAGE_NAMES.get(stage_int, "UNKNOWN"),
            "max_severity": max_severity,
            "techniques": [t.to_dict() for t in techniques],
        }
        timeline.append(step_entry)

    return timeline
