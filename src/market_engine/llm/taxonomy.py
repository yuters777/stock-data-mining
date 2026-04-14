"""
News event taxonomy — category definitions for Gemini/Sonnet classification.

TAXONOMY_VERSION tracks the current schema version.
CATEGORY_DEFINITIONS lists all valid leaf categories.
HARD_VETO_LEAF_CATEGORIES are categories that trigger trading veto.
"""

TAXONOMY_VERSION = "v69"

HARD_VETO_LEAF_CATEGORIES: frozenset[str] = frozenset({
    "earnings_negative",
    "earnings_guidance_cut",
    "regulatory_sec_action",
    "regulatory_doj_action",
    "fda_rejection",
    "bankruptcy_filing",
    "delisting_notice",
    "fraud_allegation",
    "ceo_departure_unexpected",
    "dividend_cut",
    "debt_downgrade",
})

CATEGORY_DEFINITIONS: dict[str, dict] = {
    # Hard veto categories
    "earnings_negative": {
        "description": "Earnings miss or negative earnings surprise",
        "veto": True,
    },
    "earnings_guidance_cut": {
        "description": "Forward guidance lowered or withdrawn",
        "veto": True,
    },
    "regulatory_sec_action": {
        "description": "SEC enforcement, investigation, or charges",
        "veto": True,
    },
    "regulatory_doj_action": {
        "description": "DOJ enforcement or criminal charges",
        "veto": True,
    },
    "fda_rejection": {
        "description": "FDA rejection or CRL for drug/device",
        "veto": True,
    },
    "bankruptcy_filing": {
        "description": "Chapter 7/11 filing or bankruptcy protection",
        "veto": True,
    },
    "delisting_notice": {
        "description": "Exchange delisting notice or warning",
        "veto": True,
    },
    "fraud_allegation": {
        "description": "Fraud allegation from credible source",
        "veto": True,
    },
    "ceo_departure_unexpected": {
        "description": "Unexpected CEO/CFO departure",
        "veto": True,
    },
    "dividend_cut": {
        "description": "Dividend reduction or suspension",
        "veto": True,
    },
    "debt_downgrade": {
        "description": "Credit rating downgrade",
        "veto": True,
    },
    # Soft / non-veto categories
    "earnings_positive": {
        "description": "Earnings beat or positive surprise",
        "veto": False,
    },
    "earnings_guidance_raise": {
        "description": "Forward guidance raised",
        "veto": False,
    },
    "product_launch": {
        "description": "New product or service announcement",
        "veto": False,
    },
    "partnership": {
        "description": "Strategic partnership or joint venture",
        "veto": False,
    },
    "analyst_upgrade": {
        "description": "Analyst upgrade or price target increase",
        "veto": False,
    },
    "analyst_downgrade": {
        "description": "Analyst downgrade or price target decrease",
        "veto": False,
    },
    "macro_event": {
        "description": "Macroeconomic event (Fed, CPI, jobs, etc.)",
        "veto": False,
    },
    "sector_rotation": {
        "description": "Sector rotation or flow signal",
        "veto": False,
    },
    "other": {
        "description": "Uncategorized or general market news",
        "veto": False,
    },
}
