"""
Modelos y Type Hints del Bot de Trading
=========================================
Definiciones de clases, enumeraciones y tipos de datos.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime


class ExchangeName(Enum):
    """Exchanges soportados por el bot."""
    BINANCE = "binance"
    BYBIT = "bybit"
    BINGX = "bingx"
    PIONEX = "pionex"


class OrderSide(Enum):
    """Dirección de la orden."""
    LONG = "long"
    SHORT = "short"


class OrderStatus(Enum):
    """Estado de una orden."""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class TradeDirection(Enum):
    """Dirección del trading."""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class ConfiguracionTrading:
    """Configuración actual del trading."""
    symbol: str = "BTC/USDT:USDT"
    leverage: int = 20
    initial_volume_pct: float = 0.01
    volume_multiplier: float = 1.5
    step_multiplier: float = 1.1

    max_dca_levels: int = 10
    max_ciclos: int = 0  # 0 = infinito
    dca_step_pct: float = 0.01
    take_profit_pct: float = 0.015
    stop_loss_pct: float = 0
    dca_interval_sec: int = 30
    tp_inteligente: bool = True
    tp_tipo: str = "trailing"
    trailing_distancia: float = 0.005
    auto_transfer_margin: bool = True
    reinvest_mode: bool = True
    liquidation_threshold_pct: float = 0.20
    trend_timeframe: str = "15m"
    trend_indicator: str = "EMA"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "leverage": self.leverage,
            "initial_volume_pct": self.initial_volume_pct,
            "volume_multiplier": self.volume_multiplier,
            "step_multiplier": self.step_multiplier,
            "max_dca_levels": self.max_dca_levels,
            "max_ciclos": self.max_ciclos,
            "dca_step_pct": self.dca_step_pct,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "dca_interval_sec": self.dca_interval_sec,
            "tp_inteligente": self.tp_inteligente,
            "tp_tipo": self.tp_tipo,
            "trailing_distancia": self.trailing_distancia,
            "auto_transfer_margin": self.auto_transfer_margin,
            "reinvest_mode": self.reinvest_mode,
            "liquidation_threshold_pct": self.liquidation_threshold_pct,
            "trend_timeframe": self.trend_timeframe,
            "trend_indicator": self.trend_indicator,
        }


@dataclass
class Posicion:
    """Representa una posición abierta en el mercado."""
    order_id: str
    symbol: str
    side: OrderSide
    entry_price: float
    quantity: float
    leverage: int
    dca_level: int
    timestamp: float
    status: OrderStatus = OrderStatus.FILLED
    
    # Campos calculados
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    roe_pct: float = 0.0
    
    def __post_init__(self):
        self.side = OrderSide(self.side) if isinstance(self.side, str) else self.side
        self.status = OrderStatus(self.status) if isinstance(self.status, str) else self.status


@dataclass
class CicloTrading:
    """Representa un ciclo completo de trading (desde apertura hasta cierre)."""
    ciclo_id: int
    symbol: str
    direccion_inicial: TradeDirection
    capital_inicial: float
    capital_final: float = 0.0
    profit: float = 0.0
    profit_pct: float = 0.0
    max_dca_alcanzado: int = 0
    timestamp_inicio: float = 0.0
    timestamp_fin: float = 0.0
    status: str = "activo"  # activo, completado, cancelado


@dataclass
class EstadoBot:
    """Estado general del bot."""
    running: bool = False
    symbol: str = ""
    exchange: str = ""
    testnet: bool = True
    direccion_actual: TradeDirection = TradeDirection.NEUTRAL
    balance_total: float = 0.0
    balance_disponible: float = 0.0
    capital_invertido: float = 0.0
    posiciones: List[Posicion] = field(default_factory=list)
    precio_entrada_promedio: float = 0.0
    precio_liquidacion: float = 0.0
    precio_actual: float = 0.0
    pnl_no_realizado: float = 0.0
    pnl_realizado: float = 0.0
    ciclos_completados: int = 0
    ciclo_actual: Optional[CicloTrading] = None
    ultimo_error: Optional[str] = None
    parar_tras_tp: bool = False # Modo 'Última Operación'
    max_drawdown: float = 0.0 # Récord de peor caída en el ciclo actual
    
    def tiene_posiciones(self) -> bool:
        return len(self.posiciones) > 0
    
    def get_posicion_principal(self) -> Optional[Posicion]:
        """Retorna la primera posición (la principal)."""
        return self.posiciones[0] if self.posiciones else None


@dataclass
class ResultadoAnalisis:
    """Resultado del análisis de tendencia."""
    direccion: TradeDirection
    tendencia: str  # "alcista", "bajista", "neutral"
    confianza: float  # 0-100%
    precio_actual: float
    indicadores: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
