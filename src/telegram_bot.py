"""
Bot de Telegram PRO - NEXUS SYSTEM
=============================================
Interfaz gráfica integrada, ordenada y en tiempo real.
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Any, Callable, Awaitable
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)
from telegram.error import RetryAfter, TelegramError, BadRequest
import uuid

logger = logging.getLogger(__name__)

# Top 50 Market Cap Coins para selección rápida
PARES_POPULARES = [
    ("BTC/USDT:USDT", "BTC"), ("ETH/USDT:USDT", "ETH"), ("SOL/USDT:USDT", "SOL"),
    ("XRP/USDT:USDT", "XRP"), ("BNB/USDT:USDT", "BNB"), ("ADA/USDT:USDT", "ADA"),
    ("DOGE/USDT:USDT", "DOGE"), ("AVAX/USDT:USDT", "AVAX"), ("DOT/USDT:USDT", "DOT"),
    ("MATIC/USDT:USDT", "MATIC"), ("LINK/USDT:USDT", "LINK"), ("LTC/USDT:USDT", "LTC"),
    ("TRX/USDT:USDT", "TRX"), ("TON/USDT:USDT", "TON"), ("SHIB/USDT:USDT", "SHIB"),
    ("PEPE/USDT:USDT", "PEPE"), ("UNI/USDT:USDT", "UNI"), ("ATOM/USDT:USDT", "ATOM"),
    ("XLM/USDT:USDT", "XLM"), ("ETC/USDT:USDT", "ETC"), ("XMR/USDT:USDT", "XMR"),
    ("BCH/USDT:USDT", "BCH"), ("LDO/USDT:USDT", "LDO"), ("FIL/USDT:USDT", "FIL"),
    ("HBAR/USDT:USDT", "HBAR"), ("APT/USDT:USDT", "APT"), ("ARB/USDT:USDT", "ARB"),
    ("OP/USDT:USDT", "OP"), ("NEAR/USDT:USDT", "NEAR"), ("VET/USDT:USDT", "VET"),
    ("MKR/USDT:USDT", "MKR"), ("ICP/USDT:USDT", "ICP"), ("QNT/USDT:USDT", "QNT"),
    ("GRT/USDT:USDT", "GRT"), ("ALGO/USDT:USDT", "ALGO"), ("FTM/USDT:USDT", "FTM"),
    ("SAND/USDT:USDT", "SAND"), ("MANA/USDT:USDT", "MANA"), ("AAVE/USDT:USDT", "AAVE"),
    ("AXS/USDT:USDT", "AXS"), ("THETA/USDT:USDT", "THETA"), ("EOS/USDT:USDT", "EOS"),
    ("XTZ/USDT:USDT", "XTZ"), ("FLOW/USDT:USDT", "FLOW"), ("CHZ/USDT:USDT", "CHZ"),
    ("CRV/USDT:USDT", "CRV"), ("KAVA/USDT:USDT", "KAVA"), ("RNDR/USDT:USDT", "RNDR"),
    ("INJ/USDT:USDT", "INJ"), ("TIA/USDT:USDT", "TIA"), ("SEI/USDT:USDT", "SEI"),
    ("IMX/USDT:USDT", "IMX"), ("RUNE/USDT:USDT", "RUNE"), ("ORDI/USDT:USDT", "ORDI")
]

PARES_POPULARES_ordenado = PARES_POPULARES

PARAMETROS_CONFIG = {
    "symbol": {"nombre": "Par de Trading", "tipo": "str"},
    "leverage": {"nombre": "Leverage", "tipo": "int"},
    "initial_volume_pct": {"nombre": "Vol. Inicial", "tipo": "float"},
    "volume_multiplier": {"nombre": "Multiplicador", "tipo": "float"},
    "max_dca_levels": {"nombre": "Máx DCA", "tipo": "int"},
    "dca_step_pct": {"nombre": "DCA Step", "tipo": "float"},
    "step_multiplier": {"nombre": "Mult. Step", "tipo": "float"},
    "take_profit_pct": {"nombre": "Take Profit", "tipo": "float"},
    "trailing_distancia": {"nombre": "Escalón Profit", "tipo": "float"},
}

class BotTelegram:
    
    def __init__(self, token: str, admin_id: str, 
                 obtener_estado_callback: Callable[[], Awaitable[Dict[str, Any]]],
                 cambiar_config_callback: Callable[[str, Any], Awaitable[bool]],
                 iniciar_callback: Callable[[], Awaitable[None]],
                 detener_callback: Callable[[], Awaitable[None]],
                 reconectar_callback: Optional[Callable[[], Awaitable[bool]]] = None,
                 cerrar_todo_callback: Optional[Callable[[], Awaitable[bool]]] = None,
                 guardar_perfil_callback: Optional[Callable[[str, bool], Awaitable[bool]]] = None,
                 cargar_perfil_callback: Optional[Callable[[str], Awaitable[bool]]] = None,
                 listar_perfiles_callback: Optional[Callable[[], Awaitable[list]]] = None,
                 eliminar_perfil_callback: Optional[Callable[[str], Awaitable[bool]]] = None,
                 reset_stats_callback: Optional[Callable[[], Awaitable[bool]]] = None,
                 reset_maestro_callback: Optional[Callable[[], Awaitable[bool]]] = None,
                 obtener_exchange_callback: Optional[Callable[[], Any]] = None,
                 persistencia: Optional[Any] = None,
                 instance_id: Optional[str] = None):
        
        self.token = token
        self.admin_id = str(admin_id)
        self.obtener_estado = obtener_estado_callback
        self.cambiar_config = cambiar_config_callback
        self.iniciar_bot = iniciar_callback
        self.detener_bot = detener_callback
        self.reconectar = reconectar_callback
        self.cerrar_todo = cerrar_todo_callback
        self.guardar_perfil = guardar_perfil_callback
        self.cargar_perfil = cargar_perfil_callback
        self.listar_perfiles = listar_perfiles_callback
        self.eliminar_perfil = eliminar_perfil_callback
        self.reset_stats = reset_stats_callback
        self.reset_maestro = reset_maestro_callback
        self.obtener_exchange = obtener_exchange_callback
        self.persistencia = persistencia
        
        self.app: Optional[Application] = None
        self._chat_id: Optional[str] = self.admin_id
        self._msg_dashboard_id: Optional[int] = None
        self._update_task: Optional[asyncio.Task] = None
        self._menu_activo: bool = False
        self._transicion_en_curso: bool = False
        self._custom_param: Optional[str] = None
        self._ultimo_estado: Dict[str, Any] = {}
        self._last_refresh_text: str = ""
        self._refresh_lock = asyncio.Lock()
        self._retry_after_edit_until: float = 0.0
        self._ultimo_menu_type: str = "dashboard"
        self._instance_id = instance_id or str(uuid.uuid4())[:8]
        logger.info(f"🤖 Bot Identity [Process/Telegram]: {self._instance_id}")

    async def iniciar(self) -> None:
        """Inicia el bot de Telegram en modo POLLING para máxima estabilidad."""
        try:
            # 1. Construir aplicación
            self.app = Application.builder().token(self.token).build()
            
            # 2. Registrar Handlers
            self.app.add_handler(CommandHandler("start", self._cmd_start))
            self.app.add_handler(CommandHandler("status", self._cmd_status))
            self.app.add_handler(CommandHandler("panic", self._cmd_panic))
            self.app.add_handler(CommandHandler("help", self._cmd_help))
            self.app.add_handler(CallbackQueryHandler(self._callback_query))
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_input))
            
            # Manejador de errores global
            self.app.add_error_handler(self._error_handler)
            
            # 3. Inicializar y Arrancar Polling
            await self.app.initialize()
            await self.app.start()
            
            # Borrar webhook previo por si acaso para que polling funcione
            try: await self.app.bot.delete_webhook()
            except: pass
            
            await self.app.updater.start_polling()
            
            logger.info(f"✅ Bot de Telegram [{self._instance_id}] iniciado en modo POLLING.")
            
            # Tarea de actualización de dashboard (opcional, se inicia en main habitualmente)
            if not self._update_task:
                self._update_task = asyncio.create_task(self._actualizar_dashboard_loop())
                
        except Exception as e:
            logger.error(f"❌ Error al iniciar Telegram: {e}")
            
            # Inicializar marca de tiempo para evitar spam
            self._last_edit_time = 0
            
            self._update_task = asyncio.create_task(self._actualizar_dashboard_loop())
            
        except Exception as e:
            logger.error(f"❌ Error iniciando Telegram: {e}")

    async def forzar_refresco(self, estado_externo: Optional[Dict[str, Any]] = None) -> None:
        """Actualiza el dashboard usando un estado proporcionado o consultando el actual."""
        if not self._chat_id: return
        if self._refresh_lock.locked(): return 
        
        ahora = time.time()
        if ahora < self._retry_after_edit_until: 
            return # Silencio total si estamos bloqueados
            
        async with self._refresh_lock:
            try:
                if estado_externo:
                    estado = estado_externo
                    self._ultimo_estado = estado
                else:
                    try:
                        estado = await asyncio.wait_for(self.obtener_estado(), timeout=2.0)
                        self._ultimo_estado = estado
                    except:
                        if not self._ultimo_estado: return
                        estado = self._ultimo_estado
                
                if self._menu_activo: return 
                
                if estado.get('posiciones', 0) > 0 or estado.get('lado', 'NEUTRAL') != 'NEUTRAL':
                    texto, kb = self._crear_panel_operacion(estado)
                else:
                    texto, kb = self._crear_dashboard(estado)
                
                # OPTIMIZACIÓN: Solo editar si el texto ha cambiado
                if texto == self._last_refresh_text and self._msg_dashboard_id:
                    return
                
                self._last_refresh_text = texto
                
                mensaje_editado = False
                if self._msg_dashboard_id:
                    try:
                        await self.app.bot.edit_message_text(
                            chat_id=self._chat_id, message_id=self._msg_dashboard_id,
                            text=texto, reply_markup=kb, parse_mode='HTML'
                        )
                        mensaje_editado = True
                    except RetryAfter as e_flood:
                        # Capar bloqueos absurdos en refresco automático
                        bloqueo = e_flood.retry_after
                        if bloqueo > 300: bloqueo = 45
                        self._retry_after_edit_until = time.time() + bloqueo
                        logger.warning(f"⚠️ [{self._instance_id}] Flood en Dash: Bloqueo por {bloqueo}s")
                        return
                    except Exception as e_edit:
                        error_str = str(e_edit)
                        if "Message is not modified" in error_str:
                            try:
                                await self.app.bot.edit_message_reply_markup(
                                    chat_id=self._chat_id, message_id=self._msg_dashboard_id,
                                    reply_markup=kb
                                )
                                mensaje_editado = True
                            except: pass
                        elif "message to edit not found" in error_str or "MESSAGE_ID_INVALID" in error_str:
                            self._msg_dashboard_id = None
                        else:
                            logger.debug(f"ℹ️ Edit info: {error_str}")
                
                if not mensaje_editado and self._msg_dashboard_id is None:
                    try:
                        msg = await self.app.bot.send_message(
                            chat_id=self._chat_id, text=texto, reply_markup=kb, parse_mode='HTML'
                        )
                        self._msg_dashboard_id = msg.message_id
                    except RetryAfter as e_flood2:
                        bloqueo = e_flood2.retry_after
                        if bloqueo > 300: bloqueo = 45
                        self._retry_after_edit_until = time.time() + bloqueo
                        logger.warning(f"⚠️ [{self._instance_id}] Flood en Send: Bloqueo por {bloqueo}s")
                    except Exception as e_send:
                        logger.debug(f"ℹ️ Send attempt: {e_send}")
            except Exception as e:
                logger.debug(f"ℹ️ Refresh total info: {e}")

    async def notificar(self, mensaje: str) -> None:
        """Envía un mensaje directo al administrador."""
        if not self.app or not self.admin_id: return
        try:
            await self.app.bot.send_message(chat_id=self.admin_id, text=mensaje, parse_mode='HTML')
        except Exception as e:
            logger.error(f"❌ Error enviando notificación: {e}")

    async def _actualizar_dashboard_loop(self) -> None:
        while True:
            try:
                # Frecuencia reducida de refresco automático
                await asyncio.sleep(60)
                
                # SOLO EL MAESTRO actualiza el dashboard automáticamente
                if self.persistencia:
                    id_maestro = await self.persistencia.obtener_config("master_bot_id")
                    if id_maestro and id_maestro != self._instance_id:
                        continue

                if not self._msg_dashboard_id or self._menu_activo or self._transicion_en_curso:
                    continue
                
                ahora = time.time()
                if ahora < self._retry_after_edit_until:
                    continue
                    
                # Evitar editar muy seguido (mínimo 15s entre ediciones automáticas)
                if ahora - getattr(self, '_last_edit_time', 0) < 15:
                    continue
                
                await self.forzar_refresco()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"❌ Error en bucle Telegram: {e}")

    async def detener(self) -> None:
        logger.info("🔒 Iniciando apagado de Telegram...")
        if self._update_task: self._update_task.cancel()
        if self.app:
            try:
                if self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
                logger.info("🔒 Bot de Telegram detenido correctamente")
            except Exception as e:
                logger.error(f"❌ Error deteniendo Telegram: {e}")

    def _crear_dashboard(self, estado: Dict[str, Any]) -> tuple:
        cfg = estado.get('config', {})
        running = estado.get('running', False)
        testnet = estado.get('testnet', True)
        symbol = estado.get('symbol', '---')
        balance = estado.get('balance_total', 0)
        
        modo_testnet = " <b>🧪 TESTNET</b>" if testnet else " <b>💰 REAL</b>"
        status_text = "🟢 RUNNING" if running else "🔴 PAUSED"
        alerta_prod = "\n⚠️<b>⚠️ MODO PRODUCCIÓN - DINERO REAL ⚠️</b>\n" if not testnet else ""
        linea = "━" * 28
        
        lev = cfg.get('leverage', 10)
        tp = cfg.get('take_profit_pct', 0.01) * 100
        dca_max = cfg.get('max_dca_levels', 2)
        mult = cfg.get('volume_multiplier', 1.5)
        
        texto = f"""
╔{linea}╗
║  🤖 NEXUS TRADING BOT{modo_testnet}
╚{linea}╝{alerta_prod}
📊 ESTADO: {status_text} | {symbol}

💰 BALANCE: <b>${balance:,.2f} USDT</b>

💵 PRECIO: ${estado.get('precio_actual', 0):,.2f}
⏸️ <i>Buscando oportunidad...</i>

{linea}
⚙️ CONFIGURACIÓN
{linea}

⚡ Leverage: <b>{lev}x</b>
🎯 TP: <b>{tp:.1f}%</b>
📉 DCA: <b>{dca_max} niveles</b>
🔄 Mult: <b>{mult}x</b>

{linea}
"""
        tiene_posicion = estado.get('posiciones', 0) > 0 or estado.get('lado', 'NEUTRAL') != 'NEUTRAL'
        parar_tp = estado.get('parar_tras_tp', False)
        emoji_p = "🛑" if parar_tp else "🔄"
        label_p = "ÚLTIMA OP: ON" if parar_tp else "MODO: INFINITO"
        
        # Si hay posición, solo mostrar DETENER (no iniciar)
        if tiene_posicion:
            btn_principal = [InlineKeyboardButton("🛑 DETENER", callback_data="toggle_trading")]
        elif running:
            btn_principal = [InlineKeyboardButton("🛑 DETENER", callback_data="toggle_trading")]
        elif estado.get('_procesando'):
            btn_principal = [InlineKeyboardButton("⏳ PROCESANDO...", callback_data="noop")]
        else:
            btn_principal = [InlineKeyboardButton("🚀 INICIAR", callback_data="toggle_trading")]
        
        botones = [
            btn_principal,
            [InlineKeyboardButton(f"{emoji_p} {label_p}", callback_data="toggle_last_op")],
            [InlineKeyboardButton("⚙️ Configuración", callback_data="menu_config")]
        ]
        if tiene_posicion: botones.append([InlineKeyboardButton("🚨 CERRAR POSICIÓN", callback_data="panic")])
        botones.append([InlineKeyboardButton("📊 Status", callback_data="status"), InlineKeyboardButton("❓ Ayuda", callback_data="help")])
        return texto, InlineKeyboardMarkup(botones)

    def _crear_panel_operacion(self, estado: Dict[str, Any]) -> tuple:
        cfg = estado.get('config', {})
        symbol = estado.get('symbol', '---')
        precio = float(estado.get('precio_actual', 0))
        entrada = float(estado.get('precio_inicial', 0) or estado.get('precio_entrada', 0))
        breakeven = float(estado.get('precio_entrada', 0))
        tp = float(estado.get('precio_tp', 0))
        liq = float(estado.get('liquidation_price', 0))
        pnl = float(estado.get('pnl', 0))
        pnl_pct = float(estado.get('pnl_pct', 0))
        
        lado = str(estado.get('lado', 'NEUTRAL')).upper()
        direccion = "🟢 LONG" if lado == "LONG" else "🔴 SHORT"
        
        tp_objetivo = cfg.get('take_profit_pct', 0.01)
        prog_tp_raw = min(1.0, pnl_pct / 100 / tp_objetivo) if (tp_objetivo > 0 and pnl_pct > 0) else 0
        progreso_tp = int(prog_tp_raw * 100)
        filled_tp = int(prog_tp_raw * 15)
        if prog_tp_raw > 0 and filled_tp == 0: filled_tp = 1
        barra_tp = "🟢" * filled_tp + "⚪️" * (15 - filled_tp)
        
        dist_total_liq = abs(liq - breakeven)
        dist_actual_liq = abs(precio - breakeven)
        en_perdida = (lado == "LONG" and precio < breakeven) or (lado == "SHORT" and precio > breakeven)
        riesgo_liq_raw = min(1.0, dist_actual_liq / dist_total_liq) if (dist_total_liq > 0 and en_perdida) else 0
        riesgo_liq = int(riesgo_liq_raw * 100)
        filled_liq = int(riesgo_liq_raw * 15)
        if riesgo_liq_raw > 0 and filled_liq == 0: filled_liq = 1
        barra_liq = "🔴" * filled_liq + "⚪️" * (15 - filled_liq)
        
        prog_dca_val = float(estado.get('proximidad_dca', 0))
        dca_al_maximo = (estado.get('dca_level', 0) >= cfg.get('max_dca_levels', 0))
        
        filled_dca = int(prog_dca_val * 15)
        if prog_dca_val > 0 and filled_dca == 0: filled_dca = 1
        barra_next_dca = "🔵" * filled_dca + "⚪️" * (15 - filled_dca)
        
        txt_carga_dca = f"{int(prog_dca_val*100)}%" if not dca_al_maximo else "⚠️ LÍMITE"

        ts_apertura = estado.get('timestamp_apertura')
        segundos = int(datetime.now().timestamp() - ts_apertura) if ts_apertura else 0
        tiempo = f"{segundos//3600}h {(segundos%3600)//60}m"
        linea = "━" * 28
        
        emoji_pnl = "💰" if pnl >= 0 else "📉"
        pnl_text = f"+${abs(pnl):,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        
        # ROE Real (como el exchange)
        roe_real = estado.get('roe_real_pct', pnl_pct)
        roe_val = f"+{roe_real:.2f}%" if roe_real >= 0 else f"{roe_real:.2f}%"
        roe_label = "🟢 ROE (Exchange)" if roe_real >= 0 else "🔴 ROE (Exchange)"
        
        # PNL sobre Cartera Total
        roe_cartera = f"{pnl_pct:+.2f}%"
        roe_cartera_label = "ROE Cartera"

        lev = cfg.get('leverage', 10)
        dca_step = cfg.get('dca_step_pct', 0) * 100
        dca_vol = cfg.get('initial_volume_pct', 0) * 100
        margen_real = estado.get('capital_invertido', 0)
        size_apalancado = estado.get('inversion_apalancada', 0)
        max_dd = abs(estado.get('max_drawdown', 0))
        
        max_ciclos_disp = cfg.get('max_ciclos', 0)
        ciclos_fmt = f"{estado.get('ciclos_completados', 0)}/{max_ciclos_disp if max_ciclos_disp > 0 else '∞'}"
        
        texto = f"""
<b>🚀 NEXUS PRO SYSTEM - {symbol}</b>
<code>{linea}</code>

{roe_label}: <b>{roe_val}</b>
{emoji_pnl} PNL Neto: <b>{pnl_text}</b>
📊 {roe_cartera_label}: <b>{roe_cartera}</b>
📉 Max. Drawdown: <b>{max_dd:.2f}%</b>

📐 {direccion} | ⏱️ {tiempo} | 🔄 Ciclos: <b>{ciclos_fmt}</b>

<b>📊 OPERATIVA</b>
<code>{linea}</code>
🏁 Entry:  <code>${entrada:,.2f}</code>
🟰 AVG:    <b>${breakeven:,.2f}</b>
📈 Mark:   <code>${precio:,.2f}</code>
🎯 Target: <code>${tp:,.2f}</code>

🎯 TP:  {barra_tp} {progreso_tp}%
⚠️ LIQ: {barra_liq} {riesgo_liq}%
💀 <b>LIQ: ${liq:,.2f}</b>

<b>📉 GESTIÓN DCA ({estado.get('dca_level', 0)}/{cfg.get('max_dca_levels')}{' MAX' if dca_al_maximo else ''})</b>
<code>{linea}</code>
Step: {dca_step:.2f}% | Vol: {dca_vol:.1f}%
{barra_next_dca} {txt_carga_dca}
{self._generar_lista_dca(estado)}

<b>💳 CAPITAL & MARGEN</b>
<code>{linea}</code>
💰 Balance:  <b>${estado.get('balance_total', 0):,.2f}</b>
🛡️ Margin:   <b>${margen_real:,.2f} (Real)</b>
📊 Size:     <b>${size_apalancado:,.2f} (Apal)</b>
💹 Realizado: <b>${estado.get('pnl_realizado', 0):,.2f}</b>

<code>{linea}</code>
"""
        parar_tp = estado.get('parar_tras_tp', False)
        emoji_p = "🛑" if parar_tp else "🔄"
        label_p = "ÚLTIMA OP: ON" if parar_tp else "MODO: INFINITO"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 CERRAR POSICIÓN", callback_data="cerrar_posicion")],
            [InlineKeyboardButton(f"{emoji_p} {label_p}", callback_data="toggle_last_op")],
            [InlineKeyboardButton("🚨 BOTÓN PÁNICO", callback_data="panic")],
            [InlineKeyboardButton("📊 Status", callback_data="status"), InlineKeyboardButton("⚙️ Config", callback_data="menu_config")]
        ])
        return texto, kb

    def _crear_menu_config(self, estado: Dict[str, Any]) -> tuple:
        cfg = estado.get('config', {})
        testnet = estado.get('testnet', True)
        tp_int = "✅ ON" if cfg.get('tp_inteligente') else "❌ OFF"
        current_symbol = cfg.get('symbol', 'BTC/USDT:USDT')
        symbol_name = current_symbol.split('/')[0] if current_symbol else 'BTC'
        
        leverage = cfg.get('leverage') or 20
        take_profit_pct = (cfg.get('take_profit_pct') or 0.015) * 100
        max_dca_levels = cfg.get('max_dca_levels') or 2
        max_ciclos = cfg.get('max_ciclos') or 0
        dca_step_pct = (cfg.get('dca_step_pct') or 0.01) * 100
        step_multiplier = cfg.get('step_multiplier') or 1.1
        trailing_distancia = (cfg.get('trailing_distancia') or 0.005) * 100
        initial_volume_pct = (cfg.get('initial_volume_pct') or 0.01) * 100
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"🪙 PAR: {symbol_name}/USDT", callback_data="menu_symbol"),
                InlineKeyboardButton(f"⚡ Lev: {leverage}x", callback_data="menu_leverage")
            ],
            [
                InlineKeyboardButton(f"🎯 TP: {take_profit_pct:.1f}%", callback_data="menu_tp"),
                InlineKeyboardButton(f"📉 Niveles DCA: {max_dca_levels}", callback_data="menu_max_dca")
            ],
            [
                InlineKeyboardButton(f"🔄 Ciclos: {'∞' if max_ciclos == 0 else max_ciclos}", callback_data="menu_ciclos"),
                InlineKeyboardButton(f"📏 Step: {dca_step_pct:.2f}%", callback_data="menu_step")
            ],
            [
                InlineKeyboardButton(f"✖️ Mult. Step: {step_multiplier}x", callback_data="menu_mult_step"),
                InlineKeyboardButton(f"🪜 Escalón: {trailing_distancia:.2f}%", callback_data="menu_trailing")
            ],
            [
                InlineKeyboardButton(f"💵 Vol: {initial_volume_pct:.1f}%", callback_data="menu_volumen"),
                InlineKeyboardButton(f"🧠 TP INT: {tp_int}", callback_data="cfg_tp_inteligente")
            ],
            [
                InlineKeyboardButton("🧪 MODO" if testnet else "🟢 REAL", callback_data="toggle_testnet")
            ],
            [InlineKeyboardButton("🔥 RESET MAESTRO (TODO A CERO)", callback_data="reset_maestro")],
            [InlineKeyboardButton("⬅️ VOLVER AL DASHBOARD", callback_data="back_dashboard")]
        ])
        return "⚙️ <b>CONFIGURACIÓN PROFESIONAL</b>", keyboard

    async def _callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Manejador central de botones."""
        query = update.callback_query
        data = query.data
        user_id = str(query.from_user.id)
        
        # 0. VERIFICAR SI SOMOS EL MAESTRO (Solo para logs, permitimos clics en todos)
        es_maestro = True
        if self.persistencia:
            id_maestro = await self.persistencia.obtener_config("master_bot_id")
            if id_maestro and id_maestro != self._instance_id:
                es_maestro = False
                logger.info(f"🖱️ [{self._instance_id}] Click recibido (No soy maestro, pero proceso)")
        
        # 0.1 Respuesta inmediata para quitar spinner (ÚNICA RESPUESTA)
        try: await query.answer()
        except: pass
        
        # 2. Protección contra flood (Solo log)
        ahora = time.time()
        if ahora < self._retry_after_edit_until:
             logger.debug(f"⚠️ [{self._instance_id}] Click recibido durante flood global...")
            
        # 2. Verificar Administrador
        if user_id != self.admin_id:
            try: await query.answer("❌ No autorizado", show_alert=True)
            except: pass
            return

        # 3. Transición en curso
        if self._transicion_en_curso and data in ["toggle_trading", "cerrar_posicion", "panic_confirm"]:
            try: await query.answer("⏳ Ya hay una operación en curso, por favor espera.", show_alert=True)
            except: pass
            return
        
        # 4. Respuesta estándar para quitar el spinner
        try: await query.answer()
        except: pass

        logger.info(f"🖱️ [{self._instance_id}] Click: {data}")
        
        if data == "toggle_trading":
            try:
                self._transicion_en_curso = True
                
                estado = await self.obtener_estado()
                is_running = estado.get('running', False)
                
                if not is_running:
                    balance = estado.get('balance_total', 0)
                    if balance < 10:
                        try:
                            await query.answer("⚠️ Balance insuficiente (mínimo $10)", show_alert=True)
                        except:
                            pass
                        self._transicion_en_curso = False
                        return
                
                if is_running:
                    await self.detener_bot()
                    self._menu_activo = False
                    self._transicion_en_curso = False
                    await self.forzar_refresco(manual=True)
                else:
                    # Cambiar botón a "Procesando..." mientras espera
                    estado_procesando = estado.copy()
                    estado_procesando['_procesando'] = True
                    texto_proc, kb_proc = self._crear_dashboard(estado_procesando)
                    try:
                        await self._safe_edit(query, texto_proc, kb_proc, manual=True)
                    except:
                        pass
                    
                    await self.iniciar_bot()
                    
                    # Esperar hasta que haya una posición
                    for _ in range(20):
                        await asyncio.sleep(0.5)
                        estado_actual = await self.obtener_estado()
                        if estado_actual.get('posiciones', 0) > 0:
                            self._menu_activo = False
                            self._transicion_en_curso = False
                            await self.forzar_refresco(estado_actual, manual=True)
                            return
                    
                    # Si no abrió posición, mostrar dashboard normal
                    self._menu_activo = False
                    self._transicion_en_curso = False
                    await self.forzar_refresco(manual=True)
            except Exception as e:
                logger.error(f"❌ Error toggle: {e}")
                self._transicion_en_curso = False
            return

        elif data == "toggle_last_op":
            try:
                st = await self.obtener_estado()
                nuevo = not st.get('parar_tras_tp', False)
                await self.cambiar_config('parar_tras_tp', nuevo)
                msg = "🛑 Parada automática tras TP: ACTIVADO" if nuevo else "🔄 Modo Infinito: ACTIVADO"
                try:
                    await query.answer(msg, show_alert=True)
                except Exception:
                    pass
                await self.forzar_refresco(manual=True)
            except Exception as e:
                logger.error(f"❌ Error toggle_last_op: {e}")
            return

        elif data == "back_dashboard":
            self._menu_activo = False
            await self.forzar_refresco(manual=True)
            return
            
        elif data == "menu_config":
            self._menu_activo = True
            estado = await self.obtener_estado()
            texto, keyboard = self._crear_menu_config(estado)
            await self._safe_edit(query, texto, keyboard, manual=True)
            return
        elif data == "reset_maestro":
            try:
                await query.answer("🔥 Ejecutando Reset Maestro...", show_alert=False)
                # Feedback visual instantáneo
                temp_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏳ RESETEANDO...", callback_data="noop")]])
                await self._safe_edit(query, "⏳ <b>PROCESANDO RESET MAESTRO...</b>", temp_kb, manual=True)
                
                if self.reset_maestro:
                    await self.reset_maestro()
                
                await query.answer("✅ TODO RESETEADO A CERO", show_alert=True)
                self._menu_activo = False
                await self.forzar_refresco(manual=True)
            except Exception as e:
                logger.error(f"❌ Error reset maestro: {e}")
                await self.forzar_refresco(manual=True)
            return
        elif data == "cerrar_posicion":
            await self.detener_bot()
            await self._safe_edit(query, "✅ <b>POSICIÓN CERRADA.</b>", manual=True)
            await asyncio.sleep(2)
            await self.forzar_refresco(manual=True)
        elif data == "panic":
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚨 SÍ, CERRAR TODO", callback_data="panic_confirm")], [InlineKeyboardButton("❌ CANCELAR", callback_data="back_dashboard")]])
            await self._safe_edit(query, "⚠️ <b>¿CONFIRMAR CIERRE TOTAL?</b>", keyboard, manual=True)
        elif data == "panic_confirm":
            await self._safe_edit(query, "🚨 <b>EJECUTANDO PÁNICO...</b>", manual=True)
            if self.cerrar_todo: await self.cerrar_todo()
            await asyncio.sleep(2.5)
            self._menu_activo = False
            await self.forzar_refresco(manual=True)
        elif data == "help": await self._cmd_help(update, context)
        elif data == "status": await self._cmd_start(update, context)
        elif data.startswith("menu_"):
            m = data.replace("menu_", "")
            if m == "symbol":
                pares = PARES_POPULARES_ordenado
                kb_buttons = []
                for i in range(0, len(pares), 5):
                    row = [InlineKeyboardButton(f"🪙 {p[1]}", callback_data=f"num_symbol_{p[0]}") for p in pares[i:i+5]]
                    kb_buttons.append(row)
                kb_buttons.append([InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")])
                kb = InlineKeyboardMarkup(kb_buttons)
            elif m == "leverage": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}x", callback_data=f"num_leverage_{x}") for x in [1,3,5,10]], [InlineKeyboardButton(f"{x}x", callback_data=f"num_leverage_{x}") for x in [20,30,50,70]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_leverage")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "tp": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_take_profit_pct_{x/100}") for x in [1, 1.5, 2, 5]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_take_profit_pct_{x/100}") for x in [10, 20, 50]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_take_profit_pct")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "max_dca": kb = InlineKeyboardMarkup([[InlineKeyboardButton(str(x), callback_data=f"num_max_dca_levels_{x}") for x in [2,4,6,8]], [InlineKeyboardButton(str(x), callback_data=f"num_max_dca_levels_{x}") for x in [10,15,20,30]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_max_dca_levels")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "step": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_dca_step_pct_{x/100}") for x in [0.2, 0.3, 0.5, 1]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_dca_step_pct_{x/100}") for x in [1.5, 2, 3, 5]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_dca_step_pct")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "mult_step": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}x", callback_data=f"num_step_multiplier_{x}") for x in [1.0, 1.1, 1.2, 1.5]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_step_multiplier")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "trailing": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_trailing_distancia_{x/100}") for x in [0.1, 0.2, 0.3, 0.5]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_trailing_distancia_{x/100}") for x in [1, 1.5, 2]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_trailing_distancia")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "volumen": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_initial_volume_pct_{x/100}") for x in [5, 10, 15, 20]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_initial_volume_pct_{x/100}") for x in [25, 30, 40, 50]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_initial_volume_pct")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m in ["ciclos", "max_ciclos"]: kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("2", callback_data="num_max_ciclos_2"), InlineKeyboardButton("4", callback_data="num_max_ciclos_4"), InlineKeyboardButton("6", callback_data="num_max_ciclos_6"), InlineKeyboardButton("8", callback_data="num_max_ciclos_8")],
                [InlineKeyboardButton("10", callback_data="num_max_ciclos_10"), InlineKeyboardButton("15", callback_data="num_max_ciclos_15"), InlineKeyboardButton("20", callback_data="num_max_ciclos_20")],
                [InlineKeyboardButton("30", callback_data="num_max_ciclos_30"), InlineKeyboardButton("50", callback_data="num_max_ciclos_50"), InlineKeyboardButton("∞", callback_data="num_max_ciclos_0")],
                [InlineKeyboardButton("✏️ Custom", callback_data="custom_max_ciclos")],
                [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]
            ])
            else: return
            logger.info(f"📱 [{self._instance_id}] Abriendo sub-menu: {m}")
            await self._safe_edit(query, f"⚙️ <b>MODIFICAR {m.upper()}</b>", kb, manual=True)
        elif data.startswith("num_"):
            raw = data.replace("num_", "")
            
            if raw.startswith("symbol_"):
                param = 'symbol'
                valor = raw.replace("symbol_", "")
            else:
                p = raw.rsplit("_", 1)
                param = p[0]
                valor = int(p[1]) if param in ['leverage', 'max_dca_levels'] else float(p[1])
            
            if param == 'leverage' and self.obtener_exchange:
                try:
                    exchange = self.obtener_exchange()
                    estado = await self.obtener_estado()
                    simbolo = estado.get('config', {}).get('symbol', 'BTC/USDT:USDT')
                    validacion = exchange.validar_leverage(simbolo, valor)
                    if not validacion.get('valido', True):
                        await query.answer(validacion.get('sugerencia', 'Balance insuficiente'), show_alert=True)
                except Exception as e:
                    pass
            
            await self.cambiar_config(param, valor)
            texto, keyboard = self._crear_menu_config(await self.obtener_estado())
            await self._safe_edit(query, texto, keyboard, manual=True)
        elif data == "cfg_tp_inteligente":
            st = await self.obtener_estado()
            await self.cambiar_config('tp_inteligente', not st['config']['tp_inteligente'])
            texto, keyboard = self._crear_menu_config(await self.obtener_estado())
            await self._safe_edit(query, texto, keyboard, manual=True)
        elif data == "toggle_testnet":
            st = await self.obtener_estado()
            await self.cambiar_config('testnet', not st.get('testnet', False))
            if self.reconectar: await self.reconectar()
            texto, keyboard = self._crear_menu_config(await self.obtener_estado())
            await self._safe_edit(query, texto, keyboard, manual=True)
                
    async def _safe_edit(self, query, text: str, keyboard: Optional[InlineKeyboardMarkup] = None, manual: bool = False) -> bool:
        """Edición segura de mensajes con manejo de flood y cool-down."""
        ahora = time.time()
        
        # 1. Protección de cool-down solo para automático (manual=False)
        if not manual:
            if ahora - getattr(self, '_last_edit_time', 0) < 15:
                # Actualización automática muy frecuente: pausar
                return False
            if ahora < self._retry_after_edit_until:
                # Flood global activo: pausar automáticos
                return False

        # 2. Intentar edición (Las acciones manuales SIEMPRE lo intentan)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
            self._last_edit_time = ahora
            return True
        except RetryAfter as e:
            # SI FALLA EL EDIT POR FLOOD, ENVIAMOS UN NUEVO MENSAJE (Resetea el rate limit del mensaje)
            logger.warning(f"🚨 [{self._instance_id}] Flood reportado {e.retry_after}s. Enviando MENSAJE NUEVO de emergencia...")
            try:
                # Marcar flood global para pausar automáticos
                self._retry_after_edit_until = time.time() + min(e.retry_after, 45)
                
                new_msg = await self.app.bot.send_message(
                    chat_id=self.admin_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                self._msg_dashboard_id = new_msg.message_id
                
                # Intentar borrar el mensaje viejo para no llenar el chat
                try: await query.delete_message()
                except: pass
                
                self._last_edit_time = time.time()
                return True
            except Exception as e_new:
                logger.error(f"❌ Error enviando mensaje de emergencia: {e_new}")
                return False
        except BadRequest as e:
            if "Message is not modified" in str(e): return True
            logger.error(f"❌ [{self._instance_id}] Error BadRequest: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ [{self._instance_id}] Error en safe_edit: {e}")
            return False

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Manejador global de errores de Telegram."""
        if isinstance(context.error, RetryAfter):
            self._retry_after_edit_until = time.time() + context.error.retry_after
            logger.warning(f"⚠️ Flood Control Global: Bloqueado por {context.error.retry_after}s")
            return
        
        logger.error(f"❌ Error en Telegram: {context.error}")
        if update and isinstance(update, Update) and update.effective_chat:
            try:
                # No enviar mensaje aquí para no empeorar el flood si es el caso
                pass
            except: pass

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Dashboard principal del bot."""
        try:
            user_id = str(update.effective_user.id)
            logger.info(f"🚀 [{self._instance_id}] Comando /start recibido de {user_id}")
            
            if user_id != self.admin_id: 
                logger.warning(f"⛔ [{self._instance_id}] Acceso denegado a {user_id} (Admin: {self.admin_id})")
                return
                
            self._chat_id = str(update.effective_chat.id)
            self._menu_activo = False
            
            # Limpiar mensajes anteriores si es posible
            try: await update.message.delete()
            except: pass
            
            if self._msg_dashboard_id:
                try: await self.app.bot.delete_message(self._chat_id, self._msg_dashboard_id)
                except: pass
                
            estado = await self.obtener_estado()
            self._ultimo_estado = estado
            
            # Elegir pantalla (Panel de operación si hay algo abierto, sino Dashboard)
            if estado.get('posiciones', 0) > 0 or estado.get('lado', 'NEUTRAL') != 'NEUTRAL':
                texto, kb = self._crear_panel_operacion(estado)
            else:
                texto, kb = self._crear_dashboard(estado)
                
            msg = await context.bot.send_message(
                chat_id=self._chat_id, 
                text=texto, 
                reply_markup=kb, 
                parse_mode='HTML'
            )
            self._msg_dashboard_id = msg.message_id
            logger.info(f"✅ [{self._instance_id}] Dashboard enviado (ID: {self._msg_dashboard_id})")
            
        except RetryAfter as e:
            logger.warning(f"⚠️ [{self._instance_id}] Flood en cmd_start: espera {e.retry_after}s")
            self._retry_after_edit_until = time.time() + e.retry_after
        except Exception as e: 
            logger.error(f"❌ Error en _cmd_start [{self._instance_id}]: {e}")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await self._cmd_start(update, context)
    async def _cmd_panic(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.cerrar_todo: await self.cerrar_todo()
        await update.message.reply_text("🚨 CIERRE TOTAL EJECUTADO")
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_text("📖 Ayuda: Usa /start para el dashboard.")
    async def _handle_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._custom_param: return
        try:
            val = float(update.message.text)
            if self._custom_param in ['leverage', 'max_dca_levels']: val = int(val)
            else: val = val / 100
            
            if self._custom_param == 'leverage' and self.obtener_exchange:
                try:
                    exchange = self.obtener_exchange()
                    estado = await self.obtener_estado()
                    simbolo = estado.get('config', {}).get('symbol', 'BTC/USDT:USDT')
                    validacion = exchange.validar_leverage(simbolo, val)
                    if not validacion.get('valido', True):
                        await update.message.reply_text(f"⚠️ {validacion.get('sugerencia', 'Balance insuficiente')}")
                        self._custom_param = None
                        return
                except: pass
            
            await self.cambiar_config(self._custom_param, val)
            await update.message.reply_text(f"✅ {self._custom_param} = {val}")
            self._custom_param = None
            await self.forzar_refresco()
        except: await update.message.reply_text("❌ Valor inválido")

