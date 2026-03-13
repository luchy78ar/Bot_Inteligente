# Bot de Trading Martingala Dinámica

Bot de trading algorítmico para futuros/perpetuos con estrategia Martingala Dinámica.

## Características

- **Multi-exchange**: Binance, Bybit, BingX, Pionex (via ccxt)
- **Estrategia**: Martingala con análisis de tendencia (EMA 9/21)
- **DCA**: Hasta 20 niveles de promedio de costo
- **Modo Compuesto**: Reinversión automática de ganancias
- **Modo Salvavidas**: Transferencia automática de margen para evitar liquidaciones
- **Telegram**: Control total vía comandos
- **Persistence**: SQLite para mantener estado entre reinicios
- **Health Check**: Servidor web para UptimeRobot

## Estructura

```
Bot_Inteligente/
├── config.py           # Configuraciones globales
├── main.py             # Orquestador principal
├── requirements.txt   # Dependencias
├── .env                # Variables de entorno
└── src/
    ├── models.py           # Type hints y modelos
    ├── exchange_manager.py # Factory ccxt
    ├── trading_logic.py    # Estrategia Martingala
    ├── persistence.py      # SQLite
    ├── web_server.py       # Flask health-check
    └── telegram_bot.py     # Comandos Telegram
```

## Instalación Local

### 1. Clonar y configurar

```bash
# Clonar repositorio
cd Bot_Inteligente

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
# Copiar ejemplo
cp .env.example .env

# Editar .env con tus datos
nano .env
```

Variables requeridas:
- `EXCHANGE`: binance (o bybit, bingx, pionex)
- `API_KEY`: Tu API key del exchange
- `API_SECRET`: Tu API secret
- `TELEGRAM_BOT_TOKEN`: Token de @BotFather
- `TELEGRAM_ADMIN_ID`: Tu ID de Telegram

### 3. Ejecutar

```bash
python main.py
```

## Despliegue en Render (Gratuito)

### Paso 1: Preparar código

1. Sube el código a GitHub
2. Asegúrate de tener `data/` y `logs/` en `.gitignore`

### Paso 2: Crear servicio en Render

1. Ve a [render.com](https://render.com) e inicia sesión
2. Crea un nuevo **Web Service**
3. Conecta tu repositorio GitHub
4. Configura:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Environment**: Python 3.x

### Paso 3: Configurar variables

En Render, agrega las variables de entorno:
- `EXCHANGE` = binance
- `API_KEY` = tu_api_key
- `API_SECRET` = tu_api_secret
- `TELEGRAM_BOT_TOKEN` = tu_token
- `TELEGRAM_ADMIN_ID` = tu_id
- `SYMBOL` = BTC/USDT:USDT
- `LEVERAGE` = 20

### Paso 4: Health Check con UptimeRobot

1. Crea cuenta en [uptimerobot.com](https://uptimerobot.com)
2. Agrega nuevo monitor:
   - **Type**: HTTPS
   - **URL**: `https://tu-servicio.onrender.com/ping`
   - **Interval**: 5 minutes

## Comandos Telegram

| Comando | Descripción |
|---------|-------------|
| `/start` | Panel principal |
| `/status` | Estado detallado |
| `/config` | Ver/cambiar configuración |
| `/balance` | Ver balance |
| `/stop` | Cerrar posiciones y detener |
| `/resume` | Reanudar bot |
| `/help` | Ayuda |

## Configuración de Trading

| Variable | Default | Descripción |
|----------|---------|-------------|
| `LEVERAGE` | 20x | Apalancamiento |
| `INITIAL_VOLUME_PCT` | 1% | Primera orden |
| `VOLUME_MULTIPLIER` | 1.5x | Multiplicador DCA |
| `MAX_DCA_LEVELS` | 20 | Máx niveles DCA |
| `DCA_STEP_PCT` | 1% | Caída para DCA |
| `TAKE_PROFIT_PCT` | 1.5% | Objetivo profit |
| `STOP_LOSS_PCT` | 15% | Pérdida máxima |

## Notas de Seguridad

⚠️ **IMPORTANTE**:
- Usa API keys con solo permisos de trading (no withdrawal)
- Activa 2FA en tu exchange
- Empieza con cantidades pequeñas
- Haz testing en testnet primero

## Licencia

MIT - Uso bajo tu propio riesgo.
