"""Data models for CyberneticAgents."""
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional


@dataclass
class Agent:
    id: str
    name: str
    ticker: str
    persona_json: str
    research_report: str
    portfolio_balance: float = 10000.0
    created_at: Optional[datetime] = None
    # Extended fields (all optional for backward compat)
    description: str = ""
    tools: str = "[]"  # JSON array of analyst types e.g. ["market","news"]
    analysis_system_prompt: str = ""
    comment_system_prompt: str = ""
    analysis_temperature: float = 0.7
    comment_temperature: float = 0.8
    target_days: int = 7
    max_positions: int = 1
    personality: str = ""
    direction_bias: str = "bullish"
    created_from: str = "manual"  # "research" | "prompt" | "manual"
    cybernetic_api_key: str = ""  # API key from cybernetic.biz registration


@dataclass
class Prediction:
    id: Optional[int] = None
    agent_id: str = ""
    ticker: str = ""
    direction: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    entry_price: float = 0.0
    target_date: Optional[date] = None
    result: Optional[str] = None
    exit_price: Optional[float] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    pushed_to_cybernetic: bool = False
    position_pct: float = 10.0    # agent-chosen % of balance
    position_size: float = 0.0    # computed dollar amount at entry


@dataclass
class Trade:
    id: Optional[int] = None
    prediction_id: int = 0
    agent_id: str = ""
    side: str = ""
    ticker: str = ""
    price: float = 0.0
    quantity: float = 0.0
    fee: float = 0.0
    created_at: Optional[datetime] = None
