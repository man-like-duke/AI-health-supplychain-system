import os
from typing import Any, Protocol

from dotenv import load_dotenv
from google import genai

load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


def build_explanation_prompt(decision_summary: dict[str, Any]) -> str:
    """
    Build a constrained prompt for an LLM explanation layer.

    The LLM explains deterministic analytical results.
    It must not recalculate risks, invent facts, or make
    autonomous operational decisions.
    """
    return f"""
You are an AI explanation assistant for a health-supply-chain
decision-support system.

Your role is to explain analytical results to a health-program
manager in clear, concise language.

IMPORTANT RULES:
1. Treat all supplied numbers and risk classifications as authoritative.
2. Do not recalculate or change any risk classification.
3. Do not invent facilities, medicines, quantities, risks, or other facts.
4. Do not make autonomous operational decisions.
5. Redistribution recommendations are candidates only.
6. Clearly state that an authorized health-program or supply-chain
   professional must review and approve any action.
7. Identify important assumptions or limitations when relevant.
8. The underlying dataset is synthetic and contains no real patient data.
9. Report CRITICAL and HIGH stockout items separately. Do not combine
   their counts into a single category.
10. Distinguish between expiry_days and expiry_risk. expiry_days represents
    the supplied remaining expiry window; expiry_risk is the analytical
    classification. Do not describe an expiry_days value as an expiry-risk
    classification.
11. Do not tell the decision-maker to prioritize, authorize, execute,
    or otherwise choose a specific operational action.
12. If the supplied information is insufficient to support a conclusion,
    say so instead of guessing.

Explain:
- the number of CRITICAL stockout items and identify them,
- the number of HIGH stockout items and identify them separately,
- the most relevant redistribution candidates,
- important expiry-risk classifications and relevant expiry windows,
- what a human decision-maker should verify before considering any action,
- and the main limitations of the analysis.

Return a concise explanation suitable for a health-program manager.

STRUCTURED ANALYSIS:
{decision_summary}
""".strip()


def build_explanation_request(
    decision_summary: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the structured request that will eventually be sent to an LLM.
    """
    return {
        "system_role": "health-supply-chain-explanation-assistant",
        "input_type": "deterministic_decision_summary",
        "data_type": decision_summary["governance"]["data_type"],
        "human_review_required": decision_summary["governance"][
            "human_review_required"
        ],
        "autonomous_action": decision_summary["governance"][
            "autonomous_action"
        ],
        "prompt": build_explanation_prompt(decision_summary),
    }


def build_current_explanation_request() -> dict[str, Any]:
    """
    Run the current deterministic analysis and build the
    corresponding LLM explanation request.
    """
    from src.data import load_facility_data
    from src.risk import analyze_inventory
    from src.recommendations import find_redistribution_opportunities
    from src.decisions import build_decision_summary

    data = load_facility_data()
    inventory = analyze_inventory(data)
    recommendations = find_redistribution_opportunities(inventory)

    decision_summary = build_decision_summary(
        inventory,
        recommendations,
    )

    return build_explanation_request(decision_summary)


class LLMProvider(Protocol):
    """Interface for an LLM provider."""

    def generate_explanation(self, prompt: str) -> str:
        """Generate an explanation from the supplied prompt."""
        ...


class GeminiProvider:
    """Gemini implementation of the LLM provider interface."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not configured."
            )

        self.client = genai.Client(
            api_key=self.api_key
        )
        self.model = model

    def generate_explanation(self, prompt: str) -> str:
        """Generate a decision-support explanation with Gemini."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        return response.text.strip()