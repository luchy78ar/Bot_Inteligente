"""
Configuración Global del Bot de Trading
=========================================
Todas las variables de entorno y constantes centralizadas.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# =====================
# RUTAS DEL PROYECTO
# =====================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Cargar variables de entorno DESPUÉS de definir BASE_DIR
load_dotenv(dotenv_path=BASE_DIR / ".env")

DB_PATH = str(DATA_DIR / "trading.db")

# =====================
# CONFIGURACIÓN DEL EXCHANGE
# =====================
EXCHANGE_NAME: str = os.getenv("EXCHANGE", "binance").lower()
SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT:USDT")
TESTNET: bool = os.getenv("TESTNET", "false").lower() == "true"

# API Keys (se cargan desde .env)
API_KEY: str = os.getenv("API_KEY", "")
API_SECRET: str = os.getenv("API_SECRET", "")

# API Keys Testnet
TESTNET_API_KEY: str = os.getenv("TESTNET_API_KEY", "")
TESTNET_API_SECRET: str = os.getenv("TESTNET_API_SECRET", "")

# =====================
# CONFIGURACIÓN DE TRADING
# =====================
LEVERAGE: int = int(os.getenv("LEVERAGE", "20"))
INITIAL_VOLUME_PCT: float = float(os.getenv("INITIAL_VOLUME_PCT", "0.01"))  # 1% del capital
VOLUME_MULTIPLIER: float = float(os.getenv("VOLUME_MULTIPLIER", "1.1"))
MAX_DCA_LEVELS: int = int(os.getenv("MAX_DCA_LEVELS", "2"))
DCA_STEP_PCT: float = float(os.getenv("DCA_STEP_PCT", "0.01"))  # 1% de caída
TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.015"))  # 1.5%

# TP Inteligente
TP_INTELIGENTE: bool = os.getenv("TP_INTELIGENTE", "true").lower() == "true"
TP_TIPO: str = os.getenv("TP_TIPO", "trailing")  # trailing, escalera, ema, simple
TRAILING_DISTANCIA: float = float(os.getenv("TRAILING_DISTANCIA", "0.005"))  # 0.5%
TP_ESCALERA: str = os.getenv("TP_ESCALERA", "[0.30, 0.30, 0.40]")
TP_EMA_TIMEFRAME: str = os.getenv("TP_EMA_TIMEFRAME", "1h")

STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "0"))  # 0% = OFF
DCA_INTERVAL_SEC: int = int(os.getenv("DCA_INTERVAL_SEC", "30"))

# =====================
# ANÁLISIS DE TENDENCIA
# =====================
TREND_TIMEFRAME: str = os.getenv("TREND_TIMEFRAME", "15m")
TREND_INDICATOR: str = os.getenv("TREND_INDICATOR", "EMA")  # EMA o RSI
EMA_FAST: int = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW: int = int(os.getenv("EMA_SLOW", "21"))
RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "30"))

# =====================
# TELEGRAM
# =====================
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_ID: str = os.getenv("TELEGRAM_ADMIN_ID", "")

# =====================
# MODO SALVAVIDAS (LIQUIDATION SAVER)
# =====================
LIQUIDATION_THRESHOLD_PCT: float = float(os.getenv("LIQUIDATION_THRESHOLD_PCT", "0.20"))  # 20% antes de liquidar
AUTO_TRANSFER_MARGIN: bool = os.getenv("AUTO_TRANSFER_MARGIN", "true").lower() == "true"

# =====================
# MODO REINVERSIÓN (COMPUESTO)
# =====================
REINVEST_MODE: bool = os.getenv("REINVEST_MODE", "true").lower() == "true"
MAX_CYCLES: int = int(os.getenv("MAX_CYCLES", "0"))  # 0 = infinito

# =====================
# WEB SERVER (HEALTH CHECK)
# =====================
WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")

# =====================
# LOGGING
# =====================
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_FILE: str = str(LOGS_DIR / "trading_bot.log")
