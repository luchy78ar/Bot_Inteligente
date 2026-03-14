"""
Bot de Telegram PRO - NEXUS SYSTEM
=============================================
Interfaz gráfica integrada, ordenada y en tiempo real.
"""
import asyncio
import logging
from typing import Optional, Dict, Any, Callable, Awaitable
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)

logger = logging.getLogger(__name__)

# Parámetros populares para selección rápida
PARES_POPULARES = [
    ("BTC/USDT:USDT", "BTC"), ("ETH/USDT:USDT", "ETH"), ("SOL/USDT:USDT", "SOL"),
    ("XRP/USDT:USDT", "XRP"), ("BNB/USDT:USDT", "BNB"), ("ADA/USDT:USDT", "ADA"),
    ("DOGE/USDT:USDT", "DOGE"), ("AVAX/USDT:USDT", "AVAX"), ("DOT/USDT:USDT", "DOT"),
    ("MATIC/USDT:USDT", "MATIC"), ("LINK/USDT:USDT", "LINK"), ("LTC/USDT:USDT", "LTC")
]

PARAMETROS_CONFIG = {
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
                 obtener_exchange_callback: Optional[Callable[[], Any]] = None):
        
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
        
        self.app: Optional[Application] = None
        self._chat_id: Optional[str] = None
        self._msg_dashboard_id: Optional[int] = None
        self._update_task: Optional[asyncio.Task] = None
        self._menu_activo: bool = False
        self._transicion_en_curso: bool = False
        self._custom_param: Optional[str] = None
        self._ultimo_estado: Dict[str, Any] = {}

    async def iniciar(self) -> None:
        try:
            from telegram.ext import Application
            
            # Usar webhooks con la URL de Koyeb
            webhook_url = f"https://selected-daron-luchy78ar-d6c587c4.koyeb.app/webhook/{self.token}"
            
            self.app = Application.builder().token(self.token).build()
            
            # Configurar webhook
            await self.app.bot.set_webhook(webhook_url)
            
            self.app.add_handler(CommandHandler("start", self._cmd_start))
            self.app.add_handler(CommandHandler("status", self._cmd_status))
            self.app.add_handler(CommandHandler("panic", self._cmd_panic))
            self.app.add_handler(CommandHandler("help", self._cmd_help))
            self.app.add_handler(CallbackQueryHandler(self._callback_query))
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_input))
            
            await self.app.initialize()
            await self.app.start()
            
            self._update_task = asyncio.create_task(self._actualizar_dashboard_loop())
            
            logger.info(f"✅ Bot de Telegram NEXUS iniciado con webhook: {webhook_url}")
        except Exception as e:
            logger.error(f"❌ Error iniciando Telegram: {e}")

    async def forzar_refresco(self, estado_externo: Optional[Dict[str, Any]] = None) -> None:
        """Actualiza el dashboard usando un estado proporcionado o consultando el actual."""
        if not self._chat_id or not self._msg_dashboard_id: return
            
        try:
            if estado_externo:
                estado = estado_externo
                self._ultimo_estado = estado
            else:
                # Si no hay estado externo, obtenerlo con timeout corto
                try:
                    estado = await asyncio.wait_for(self.obtener_estado(), timeout=2.0)
                    self._ultimo_estado = estado
                except:
                    if not self._ultimo_estado: return
                    estado = self._ultimo_estado
            
            if estado.get('posiciones', 0) > 0 or estado.get('running', False):
                texto, kb = self._crear_panel_operacion(estado)
            else:
                texto, kb = self._crear_dashboard(estado)
                
            try:
                await self.app.bot.edit_message_text(
                    chat_id=self._chat_id, message_id=self._msg_dashboard_id,
                    text=texto, reply_markup=kb, parse_mode='HTML'
                )
            except Exception as e:
                if "Message is not modified" in str(e):
                    await self.app.bot.edit_message_reply_markup(
                        chat_id=self._chat_id, message_id=self._msg_dashboard_id,
                        reply_markup=kb
                    )
                else: raise e
        except Exception as e:
            logger.debug(f"ℹ️ Refresh info: {e}")

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
                await asyncio.sleep(3) # Reducido a 3s para máxima fluidez
                if not self._msg_dashboard_id or self._menu_activo or self._transicion_en_curso:
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
        
        botones = [
            [InlineKeyboardButton("🚀 " + ("DETENER" if running else "INICIAR"), callback_data="toggle_trading")],
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
        
        tp_objetivo_pct = cfg.get('take_profit_pct', 0.01) * 100
        prog_tp_raw = min(1.0, pnl_pct / tp_objetivo_pct) if (tp_objetivo_pct > 0 and pnl_pct > 0) else 0
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
        roe_val = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
        roe_label = "🟢 ROE%" if pnl_pct >= 0 else "🔴 ROE%"

        lev = cfg.get('leverage', 10)
        dca_step = cfg.get('dca_step_pct', 0) * 100
        dca_vol = cfg.get('initial_volume_pct', 0) * 100
        margen_real = estado.get('capital_invertido', 0)
        size_apalancado = estado.get('inversion_apalancada', 0)
        max_dd = abs(estado.get('max_drawdown', 0))
        
        texto = f"""
<b>🚀 NEXUS PRO SYSTEM - {symbol}</b>
<code>{linea}</code>

{roe_label}: <b>{roe_val}</b> ({lev}x)
{emoji_pnl} PNL: <b>{pnl_text}</b>
📉 Max. Drawdown: <b>{max_dd:.2f}%</b>

📐 {direccion} | ⏱️ {tiempo} | 🔄 {estado.get('ciclos_completados', 0)} ciclos

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

    def _generar_lista_dca(self, estado: Dict[str, Any]) -> str:
        precios = estado.get('precios_dca', {})
        if not precios: return "▫️ <i>Sin compras DCA activas</i>"
        text = ""
        for nivel, precio in precios.items(): text += f"🔹 DCA {nivel}: ${precio:,.2f}\n"
        return text.strip()

    def _crear_menu_config(self, estado: Dict[str, Any]) -> tuple:
        cfg = estado.get('config', {})
        testnet = estado.get('testnet', True)
        tp_int = "✅ ON" if cfg.get('tp_inteligente') else "❌ OFF"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"⚡ Lev: {cfg.get('leverage')}x", callback_data="menu_leverage"),
                InlineKeyboardButton(f"🎯 TP: {cfg.get('take_profit_pct')*100:.1f}%", callback_data="menu_tp")
            ],
            [
                InlineKeyboardButton(f"🔄 Ciclos: {'∞' if cfg.get('max_ciclos', 0) == 0 else cfg.get('max_ciclos')}", callback_data="toggle_ciclos"),
                InlineKeyboardButton(f"📉 Niveles DCA: {cfg.get('max_dca_levels')}", callback_data="menu_max_dca")
            ],
            [
                InlineKeyboardButton(f"📏 Step: {cfg.get('dca_step_pct')*100:.2f}%", callback_data="menu_step"),
                InlineKeyboardButton(f"✖️ Mult. Step: {cfg.get('step_multiplier')}x", callback_data="menu_mult_step")
            ],
            [
                InlineKeyboardButton(f"🪜 Escalón: {cfg.get('trailing_distancia')*100:.2f}%", callback_data="menu_trailing"),
                InlineKeyboardButton(f"💵 Vol: {cfg.get('initial_volume_pct')*100:.1f}%", callback_data="menu_volumen")
            ],
            [
                InlineKeyboardButton(f"🧠 TP INT: {tp_int}", callback_data="cfg_tp_inteligente"),
                InlineKeyboardButton("🧪 MODO" if testnet else "🟢 REAL", callback_data="toggle_testnet")
            ],
            [InlineKeyboardButton("🔥 RESET MAESTRO (TODO A CERO)", callback_data="reset_maestro")],
            [InlineKeyboardButton("⬅️ VOLVER AL DASHBOARD", callback_data="back_dashboard")]
        ])
        return "⚙️ <b>CONFIGURACIÓN PROFESIONAL</b>", keyboard

    async def _callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        data = query.data
        
        if data == "toggle_trading":
            try:
                self._transicion_en_curso = True
                await query.answer("⚙️ Procesando motor...", show_alert=False)
                
                # Feedback visual temporal sin bloquear
                temp_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏳ PROCESANDO...", callback_data="none")]])
                await query.edit_message_reply_markup(reply_markup=temp_kb)
                
                # Obtener estado actual
                estado = await self.obtener_estado()
                
                # Verificar balance antes de iniciar
                if not estado.get('running'):
                    balance = estado.get('balance_total', 0)
                    if balance < 10:
                        await query.answer("⚠️ Balance insuficiente. Mínimo $10 USDT requeridos.", show_alert=True)
                        self._transicion_en_curso = False
                        return
                
                # Ejecutar acción en segundo plano
                if estado.get('running'): await self.detener_bot()
                else: await self.iniciar_bot()
                
                await asyncio.sleep(1.0)
                self._menu_activo = False
                await self.forzar_refresco()
            except Exception as e:
                logger.error(f"❌ Error toggle: {e}")
                await query.answer(f"❌ Error: {e}", show_alert=True)
            finally:
                self._transicion_en_curso = False
                # Asegurar que el teclado se restaura si algo falló
                try: await self.forzar_refresco()
                except: pass
            return

        elif data == "toggle_last_op":
            try:
                st = await self.obtener_estado()
                nuevo = not st.get('parar_tras_tp', False)
                await self.cambiar_config('parar_tras_tp', nuevo)
                msg = "🛑 Parada automática tras TP: ACTIVADO" if nuevo else "🔄 Modo Infinito: ACTIVADO"
                await query.answer(msg, show_alert=True)
                await self.forzar_refresco()
            except Exception as e:
                logger.error(f"❌ Error toggle_last_op: {e}")
            return

        await query.answer()
        if data == "back_dashboard":
            self._menu_activo = False
            await self.forzar_refresco()
        elif data == "menu_config":
            try:
                logger.info(f"🔧 Abriendo menu config...")
                self._menu_activo = True
                estado = await self.obtener_estado()
                texto, keyboard = self._crear_menu_config(estado)
                await query.edit_message_text(texto, reply_markup=keyboard, parse_mode='HTML')
                logger.info(f"✅ Menu config abierto")
            except Exception as e:
                logger.error(f"❌ Error config: {e}")
                await query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)
        elif data == "toggle_ciclos":
            st = await self.obtener_estado()
            current = st['config'].get('max_ciclos', 0)
            nuevo = 0 if current > 0 else 10
            await self.cambiar_config('max_ciclos', nuevo)
            texto, keyboard = self._crear_menu_config(await self.obtener_estado())
            await query.edit_message_text(texto, reply_markup=keyboard, parse_mode='HTML')
        elif data == "reset_maestro":
            try:
                await query.answer("🔥 Ejecutando Reset Maestro...", show_alert=False)
                # Feedback visual instantáneo
                temp_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏳ RESETEANDO...", callback_data="none")]])
                await query.edit_message_reply_markup(reply_markup=temp_kb)
                
                if self.reset_maestro:
                    await self.reset_maestro()
                
                await query.answer("✅ TODO RESETEADO A CERO", show_alert=True)
                self._menu_activo = False
                await self.forzar_refresco()
            except Exception as e:
                logger.error(f"❌ Error reset maestro: {e}")
                await self.forzar_refresco()
            return
        elif data == "cerrar_posicion":
            await self.detener_bot()
            await query.edit_message_text("✅ <b>POSICIÓN CERRADA.</b>", parse_mode='HTML')
            await asyncio.sleep(2)
            await self.forzar_refresco()
        elif data == "panic":
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚨 SÍ, CERRAR TODO", callback_data="panic_confirm")], [InlineKeyboardButton("❌ CANCELAR", callback_data="back_dashboard")]])
            await query.edit_message_text("⚠️ <b>¿CONFIRMAR CIERRE TOTAL?</b>", reply_markup=keyboard, parse_mode='HTML')
        elif data == "panic_confirm":
            await query.edit_message_text("🚨 <b>EJECUTANDO PÁNICO...</b>", parse_mode='HTML')
            if self.cerrar_todo: await self.cerrar_todo()
            await asyncio.sleep(2.5)
            self._menu_activo = False
            await self.forzar_refresco()
        elif data == "help": await self._cmd_help(update, context)
        elif data == "status": await self._cmd_start(update, context)
        elif data.startswith("menu_"):
            m = data.replace("menu_", "")
            if m == "leverage": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}x", callback_data=f"num_leverage_{x}") for x in [1,3,5,10]], [InlineKeyboardButton(f"{x}x", callback_data=f"num_leverage_{x}") for x in [20,30,50,70]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_leverage")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "tp": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_take_profit_pct_{x/100}") for x in [1, 1.5, 2, 5]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_take_profit_pct_{x/100}") for x in [10, 20, 50]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_take_profit_pct")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "max_dca": kb = InlineKeyboardMarkup([[InlineKeyboardButton(str(x), callback_data=f"num_max_dca_levels_{x}") for x in [2,4,6,8]], [InlineKeyboardButton(str(x), callback_data=f"num_max_dca_levels_{x}") for x in [10,15,20,30]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_max_dca_levels")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "step": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_dca_step_pct_{x/100}") for x in [0.2, 0.3, 0.5, 1]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_dca_step_pct_{x/100}") for x in [1.5, 2, 3, 5]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_dca_step_pct")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "mult_step": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}x", callback_data=f"num_step_multiplier_{x}") for x in [1.0, 1.1, 1.2, 1.5]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_step_multiplier")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "trailing": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_trailing_distancia_{x/100}") for x in [0.1, 0.2, 0.3, 0.5]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_trailing_distancia_{x/100}") for x in [1, 1.5, 2]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_trailing_distancia")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "volumen": kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{x}%", callback_data=f"num_initial_volume_pct_{x/100}") for x in [5, 10, 15, 20]], [InlineKeyboardButton(f"{x}%", callback_data=f"num_initial_volume_pct_{x/100}") for x in [25, 30, 40, 50]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_initial_volume_pct")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            elif m == "max_ciclos": kb = InlineKeyboardMarkup([[InlineKeyboardButton(str(x), callback_data=f"num_max_ciclos_{x}") for x in [1, 2, 3, 5]], [InlineKeyboardButton(str(x), callback_data=f"num_max_ciclos_{x}") for x in [10, 20, 50, 0]], [InlineKeyboardButton("✏️ Custom", callback_data="custom_max_ciclos")], [InlineKeyboardButton("⬅️ Volver", callback_data="menu_config")]])
            else: return
            await query.edit_message_text(f"⚙️ <b>MODIFICAR {m.upper()}</b>", reply_markup=kb, parse_mode='HTML')
        elif data.startswith("num_"):
            p = data.replace("num_", "").rsplit("_", 1)
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
            await query.edit_message_text(texto, reply_markup=keyboard, parse_mode='HTML')
        elif data == "cfg_tp_inteligente":
            st = await self.obtener_estado()
            await self.cambiar_config('tp_inteligente', not st['config']['tp_inteligente'])
            texto, keyboard = self._crear_menu_config(await self.obtener_estado())
            await query.edit_message_text(texto, reply_markup=keyboard, parse_mode='HTML')
        elif data == "toggle_testnet":
            st = await self.obtener_estado()
            await self.cambiar_config('testnet', not st.get('testnet', False))
            if self.reconectar: await self.reconectar()
            texto, keyboard = self._crear_menu_config(await self.obtener_estado())
            await query.edit_message_text(texto, reply_markup=keyboard, parse_mode='HTML')

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            user_id = str(update.effective_user.id)
            if user_id != self.admin_id: return
            self._chat_id = str(update.effective_chat.id)
            self._menu_activo = False
            try: await update.message.delete()
            except: pass
            if self._msg_dashboard_id:
                try: await self.app.bot.delete_message(self._chat_id, self._msg_dashboard_id)
                except: pass
            estado = await self.obtener_estado()
            self._ultimo_estado = estado
            texto, kb = self._crear_panel_operacion(estado) if (estado.get('posiciones', 0) > 0 or estado.get('running', False)) else self._crear_dashboard(estado)
            msg = await context.bot.send_message(self._chat_id, texto, reply_markup=kb, parse_mode='HTML')
            self._msg_dashboard_id = msg.message_id
        except Exception as e: logger.error(f"❌ Error start: {e}")

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

