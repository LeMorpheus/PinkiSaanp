"""PinkiSaanp - a ruthless, time-boxed Paper.io bot (FSM + risk-aware A* + bitboards)."""

from .adapters import AiCupsAdapter, GenericAdapter
from .bot import PinkiSaanp
from .config import BotConfig
from .fsm import ATTACKING, DEFENDING, EXPANDING_SAFELY, RETREATING

__all__ = ['PinkiSaanp', 'BotConfig', 'AiCupsAdapter', 'GenericAdapter',
           'EXPANDING_SAFELY', 'RETREATING', 'ATTACKING', 'DEFENDING']

__version__ = '1.0.0'
