"""
Bot de Trading Martingala Dinámica - MAIN PRO
==========================================
Orquestador principal del bot de trading con sincronización total.
"""
import asyncio
import logging
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

import config as cfg
from src.models import (
    Posicion, CicloTrading, EstadoBot, 
    TradeDirection, OrderSide, ResultadoAnalisis, ConfiguracionTrading
)
from src.exchange_manager import ExchangeFactory, ExchangeWrapper
from src.persistence import Persistencia
from src.trading_logic import EstrategiaMartingala, ModoSalvavidas
from src.telegram_bot import BotTelegram
from src.web_server import iniciar_servidor, actualizar_estado

# Configuración de logging profesional
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL),
    format=cfg.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(cfg.LOG_FILE)
    ]
)
logger = logging.getLogger(__name__)

# Debug: verificar carga de credenciales
logger.info(f"🔑 API_KEY cargada: {'Sí' if cfg.API_KEY else 'NO'} (length: {len(cfg.API_KEY)})")
logger.info(f"🔑 API_SECRET cargada: {'Sí' if cfg.API_SECRET else 'NO'} (length: {len(cfg.API_SECRET)})")

# Limpiar cache de instancias previas
from src.exchange_manager import ExchangeFactory
ExchangeFactory.clear_instances()


class BotTrading:
    """Clase principal que orquesta todos los componentes del bot."""
    
    def __init__(self):
        self.estado = EstadoBot()
        
        # Instanciar configuración desde las variables de config.py
        self.config = ConfiguracionTrading(
            symbol=cfg.SYMBOL,
            leverage=cfg.LEVERAGE,
            initial_volume_pct=cfg.INITIAL_VOLUME_PCT,
            volume_multiplier=cfg.VOLUME_MULTIPLIER,
            max_dca_levels=cfg.MAX_DCA_LEVELS,
            dca_step_pct=cfg.DCA_STEP_PCT,
            take_profit_pct=cfg.TAKE_PROFIT_PCT,
            stop_loss_pct=cfg.STOP_LOSS_PCT,
            dca_interval_sec=cfg.DCA_INTERVAL_SEC,
            tp_inteligente=cfg.TP_INTELIGENTE,
            tp_tipo=cfg.TP_TIPO,
            trailing_distancia=cfg.TRAILING_DISTANCIA,
            auto_transfer_margin=cfg.AUTO_TRANSFER_MARGIN,
            reinvest_mode=cfg.REINVEST_MODE,
            liquidation_threshold_pct=cfg.LIQUIDATION_THRESHOLD_PCT,
            trend_timeframe=cfg.TREND_TIMEFRAME,
            trend_indicator=cfg.TREND_INDICATOR
        )
        
        self.simbolo_actual = self.config.symbol
        
        # Componentes
        self.persistencia = Persistencia(cfg.DB_PATH)
        self.exchange: Optional[ExchangeWrapper] = None
        self.estrategia: Optional[EstrategiaMartingala] = None
        self.telegram: Optional[BotTelegram] = None
        self.salvavidas: Optional[ModoSalvavidas] = None
        
        # Tareas
        self.tareas: List[asyncio.Task] = []
        self._loop_running = False

    async def inicializar(self) -> bool:
        """Inicializa todos los componentes del bot."""
        try:
            logger.info("🚀 INICIANDO BOT DE TRADING MARTINGALA")
            logger.info("=" * 50)
            
            # 1. Base de datos
            await self.persistencia.conectar()
            
            # 2. Cargar estado previo si existe
            estado_db = await self.persistencia.obtener_estado_bot()
            if estado_db:
                self.estado.pnl_realizado = estado_db.get('pnl_realizado', 0.0)
                self.estado.ciclos_completados = estado_db.get('ciclos_completados', 0)
                self.estado.testnet = cfg.TESTNET
                await self.persistencia.actualizar_estado_bot(testnet=cfg.TESTNET)
                self.estado.symbol = estado_db.get('symbol', self.config.symbol)
                self.simbolo_actual = self.estado.symbol
                
                # Actualizar config con el símbolo de la DB
                self.config.symbol = self.simbolo_actual
                logger.info(f"📂 Configuración cargada desde DB (testnet={cfg.TESTNET})")
            else:
                logger.info(f"📂 Configuración cargada desde perfil por defecto")
            
            # 3. Exchange
            testnet = cfg.TESTNET
            logger.info(f"🧪 Testnet: {testnet}")
            
            # Limpiar cache de exchange para forzar nueva conexión
            ExchangeFactory.clear_instances()
            
            api_key = cfg.TESTNET_API_KEY if testnet else cfg.API_KEY
            api_secret = cfg.TESTNET_API_SECRET if testnet else cfg.API_SECRET
            logger.info(f"🔑 Usando API Key: {api_key[:10]}... (testnet={testnet})")
            
            self.exchange = ExchangeFactory.create(
                cfg.EXCHANGE_NAME,
                api_key,
                api_secret,
                testnet
            )
            logger.info(f"🔗 Exchange testnet attribute: {self.exchange.testnet}")
            
            if not self.exchange.verificar_conexion():
                logger.error("❌ No se pudo conectar al exchange")
                return False
            
            # Cargar mercados para que los cálculos de precisión sean reales desde el inicio
            self.exchange._exchange.load_markets()
            logger.info(f"✅ Mercados cargados y conexión verificada: {cfg.EXCHANGE_NAME}")
            
            # 4. Telegram
            if cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_ADMIN_ID:
                self.telegram = BotTelegram(
                    cfg.TELEGRAM_BOT_TOKEN,
                    cfg.TELEGRAM_ADMIN_ID,
                    self.obtener_estado,
                    self.cambiar_config,
                    self.iniciar_trading,
                    self.detener_trading,
                    self.reconectar_exchange,
                    self.cerrar_todas_posiciones,
                    self.guardar_perfil,
                    self.cargar_perfil,
                    self.listar_perfiles,
                    self.eliminar_perfil,
                    self.resetear_estadisticas,
                    self.reset_maestro
                )
                await self.telegram.iniciar()
            
            # 6. Estrategia y Salvavidas
            self.estrategia = EstrategiaMartingala(
                self.exchange,
                self.persistencia,
                self.config,
                on_error_callback=self.telegram.notificar if self.telegram else None
            )
            self.salvavidas = ModoSalvavidas(self.exchange, self.persistencia)
            
            # 7. Actualizar estado inicial con balance fresco
            estado_inicial = await self.obtener_estado()
            actualizar_estado(estado_inicial)
            logger.info(f"💰 Estado inicial actualizado - Balance: {estado_inicial.get('balance_total', 0)}")
            
            # 8. Servidor Web
            iniciar_servidor()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al inicializar: {e}")
            return False

    async def obtener_estado(self) -> Dict[str, Any]:
        """Retorna el estado actual del bot con caché ultrarrápida."""
        try:
            ahora = datetime.now().timestamp()
            # Sin caché para el balance (siempre fresco)
            balance = self.exchange.obtener_balance()
            
            # Solo caché para otros datos (1 segundo)
            if hasattr(self, '_estado_cache') and (ahora - getattr(self, '_ultimo_fetch_estado', 0) < 1.0):
                # Actualizar solo el balance
                self._estado_cache['balance_total'] = balance.get("total", 0)
                self._estado_cache['balance_disponible'] = balance.get("free", 0)
                return self._estado_cache

            posiciones_db = await self.persistencia.obtener_posiciones_abiertas()
            pos_exchange = self.exchange.obtener_posicion(self.simbolo_actual)
            
            info_posiciones = {}
            
            # --- LÓGICA DE SINCRONIZACIÓN PRIORITARIA ---
            if pos_exchange:
                # Si hay posición en el exchange, ella manda sobre la DB
                if not posiciones_db:
                    logger.info(f"🔍 SYNC: Detectada posición externa. Importando...")
                    # Crear objeto temporal para cálculo inmediato
                    pos_temp = Posicion(
                        order_id="sync_init", symbol=self.simbolo_actual,
                        side=OrderSide.LONG if pos_exchange['side'] == 'long' else OrderSide.SHORT,
                        entry_price=pos_exchange['entry_price'],
                        quantity=pos_exchange['size'],
                        leverage=pos_exchange['leverage'],
                        dca_level=0, timestamp=datetime.now().timestamp()
                    )
                    info_posiciones = await self.estrategia.obtener_info_posiciones([pos_temp])
                else:
                    # Usar la lógica de la estrategia para calcular métricas reales
                    info_posiciones = await self.estrategia.obtener_info_posiciones(posiciones_db)
            
            if not pos_exchange and posiciones_db:
                logger.warning(f"🔍 SYNC: Limpiando posiciones fantasma de la DB")
                await self.persistencia.limpiar_posiciones()
                posiciones_db = []
                info_posiciones = {}

            num_posiciones = len(posiciones_db) if not pos_exchange else (len(posiciones_db) or 1)
            if not pos_exchange: num_posiciones = 0

            ciclo = await self.persistencia.obtener_ciclo_activo()
            precio_entrada = info_posiciones.get("precio_entrada", 0)
            precio_actual = info_posiciones.get("precio_actual", 0)
            lado = info_posiciones.get("lado", "NEUTRAL")
            
            precio_tp = 0
            precio_sl = 0
            leverage = self.config.leverage
            if precio_entrada > 0:
                # El objetivo es ganar X% sobre el CAPITAL REAL (Margen)
                # Variación de precio necesaria = Objetivo / Apalancamiento
                variacion_necesaria = self.config.take_profit_pct / leverage
                variacion_sl_necesaria = self.config.stop_loss_pct / leverage
                
                if lado == "LONG":
                    precio_tp = precio_entrada * (1 + variacion_necesaria)
                    precio_sl = precio_entrada * (1 - variacion_sl_necesaria) if self.config.stop_loss_pct > 0 else 0
                else:
                    precio_tp = precio_entrada * (1 - variacion_necesaria)
                    precio_sl = precio_entrada * (1 + variacion_sl_necesaria) if self.config.stop_loss_pct > 0 else 0
            
            liq_price = info_posiciones.get("liquidation_price", 0)
            capital_real = info_posiciones.get("capital_invertido", 0)
            
            estado_fresco = {
                "running": self.estado.running,
                "symbol": self.estado.symbol,
                "exchange": "Binance",
                "testnet": self.estado.testnet,
                "precio_actual": precio_actual,
                "precio_entrada": precio_entrada,
                "precio_inicial": info_posiciones.get("precio_inicial", precio_entrada),
                "precios_dca": info_posiciones.get("precios_dca", {}),
                "liquidation_price": liq_price,
                "pnl": info_posiciones.get("pnl", 0),
                "pnl_pct": info_posiciones.get("pnl_pct", 0),
                "pnl_realizado": self.estado.pnl_realizado,
                "posiciones": num_posiciones,
                "dca_level": info_posiciones.get("nivel_dca", 0),
                "proximidad_dca": info_posiciones.get("proximidad_dca", 0),
                "lado": lado,
                "balance_total": balance.get("total", 0),
                "balance_disponible": balance.get("free", 0),
                "capital_invertido": capital_real,
                "inversion_apalancada": capital_real * self.config.leverage if capital_real > 0 else 0,
                "ciclos_completados": self.estado.ciclos_completados,
                "ciclo_activo": ciclo.ciclo_id if ciclo else None,
                "ultimo_error": self.estado.ultimo_error,
                "config": self.config.to_dict(),
                "precio_tp": precio_tp,
                "precio_sl": precio_sl,
                "timestamp_apertura": info_posiciones.get("timestamp_apertura")
            }
            
            self._estado_cache = estado_fresco
            self._ultimo_fetch_estado = ahora
            return estado_fresco
        except Exception as e:
            logger.error(f"❌ Error obteniendo estado: {e}")
            return getattr(self, '_estado_cache', {"running": False, "error": str(e)})

    async def cambiar_config(self, param: str, valor: Any) -> bool:
        try:
            exito = False
            reconnect = False
            if param == "testnet":
                self.estado.testnet = bool(valor)
                await self.persistencia.guardar_config(param, valor)
                exito = True
                reconnect = True
                ExchangeFactory.clear_instances()
                logger.info(f"⚙️ Testnet cambiado: {valor}")
            elif param == "symbol":
                self.estado.symbol = valor
                self.simbolo_actual = valor
                await self.persistencia.guardar_config(param, valor)
                exito = True
            elif hasattr(self.config, param):
                if param in ['leverage', 'max_dca_levels']: valor = int(float(valor))
                setattr(self.config, param, valor)
                await self.persistencia.guardar_config(param, valor)
                if param == "leverage" and self.exchange:
                    self.exchange.configurar_apalancamiento(self.simbolo_actual, int(valor))
                exito = True
            
            if exito:
                estado_nuevo = await self.obtener_estado()
                actualizar_estado(estado_nuevo)
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error cambiando config: {e}")
            return False

    async def guardar_perfil(self, nombre: str, predeterminado: bool = False) -> bool:
        return await self.persistencia.guardar_perfil(nombre, self.config.to_dict(), predeterminado)

    async def cargar_perfil(self, nombre: str) -> bool:
        try:
            config_dict = await self.persistencia.obtener_perfil(nombre)
            if config_dict:
                for k, v in config_dict.items():
                    if hasattr(self.config, k): setattr(self.config, k, v)
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error cargando perfil: {e}")
            return False
    
    async def listar_perfiles(self) -> list: return await self.persistencia.listar_perfiles()
    async def eliminar_perfil(self, nombre: str) -> bool:
        return await self.persistencia.eliminar_config_perfil(nombre)

    async def resetear_estadisticas(self) -> bool:
        """Reinicia PNL y ciclos."""
        exito = await self.persistencia.resetear_estadisticas()
        if exito:
            self.estado.pnl_realizado = 0
            self.estado.ciclos_completados = 0
        return exito

    async def reset_maestro(self) -> bool:
        """Limpia todo y comienza desde cero absoluto."""
        try:
            logger.info("🔥 Iniciando RESET MAESTRO...")
            # 1. Detener trading
            self.estado.running = False
            for tarea in self.tareas: tarea.cancel()
            self.tareas.clear()
            
            # 2. Cerrar posiciones en exchange y limpiar DB
            self.exchange.cerrar_posicion(self.simbolo_actual)
            await self.persistencia.limpiar_posiciones()
            
            # 3. Resetear estadísticas
            await self.resetear_estadisticas()
            
            # 4. Actualizar estado y persistencia
            await self.persistencia.actualizar_estado_bot(running=False)
            
            # 5. Reiniciar motor
            await self.iniciar_trading()
            logger.info("✅ RESET MAESTRO COMPLETADO. Bot reiniciado desde cero.")
            return True
        except Exception as e:
            logger.error(f"❌ Error en Reset Maestro: {e}")
            return False
    async def reconectar_exchange(self) -> bool:
        try:
            if self.estado.running: await self.detener_trading()
            if self.exchange: self.exchange.cerrar()
            ExchangeFactory.clear_instances()
            api_key = cfg.TESTNET_API_KEY if self.estado.testnet else cfg.API_KEY
            api_secret = cfg.TESTNET_API_SECRET if self.estado.testnet else cfg.API_SECRET
            self.exchange = ExchangeFactory.create(cfg.EXCHANGE_NAME, api_key, api_secret, self.estado.testnet)
            self.estrategia = EstrategiaMartingala(self.exchange, self.persistencia, self.config, on_error_callback=self.telegram.notificar if self.telegram else None)
            self.salvavidas = ModoSalvavidas(self.exchange, self.persistencia)
            return True
        except Exception: return False
    
    async def cerrar_todas_posiciones(self) -> bool:
        """Cierra todo y limpia dashboards inmediatamente."""
        try:
            logger.warning("🚨 PÁNICO: Cierre total en el Exchange...")
            self.estado.running = False
            for tarea in self.tareas: tarea.cancel()
            self.tareas.clear()
            
            exito_exchange = self.exchange.cerrar_todas_posiciones()
            await self.persistencia.limpiar_posiciones()
            await self.persistencia.actualizar_estado_bot(running=False)
            
            # Sincronización inmediata de dashboards
            estado_limpio = await self.obtener_estado()
            actualizar_estado(estado_limpio)
            if self.telegram: await self.telegram.forzar_refresco()
            
            return exito_exchange
        except Exception as e:
            logger.error(f"❌ Error pánico: {e}")
            return False

    async def iniciar_trading(self) -> None:
        if self.estado.running: return
        self.estado.running = True
        await self.persistencia.actualizar_estado_bot(running=True)
        # Actualización inicial web
        estado_inicial = await self.obtener_estado()
        actualizar_estado(estado_inicial)
        
        tarea_trading = asyncio.create_task(self.loop_trading())
        self.tareas.append(tarea_trading)
    
    async def detener_trading(self) -> None:
        self.estado.running = False
        for tarea in self.tareas: tarea.cancel()
        self.tareas.clear()
        self.exchange.cerrar_posicion(self.simbolo_actual)
        await self.persistencia.limpiar_posiciones()
        await self.persistencia.actualizar_estado_bot(running=False)
        # Sincronización inmediata
        estado_fresco = await self.obtener_estado()
        actualizar_estado(estado_fresco)
        if self.telegram: await self.telegram.forzar_refresco()

    async def loop_trading(self) -> None:
        logger.info("🚀 Monitor de Precio Real-Time Iniciado (1s)")
        contador_pesado = 0
        while self.estado.running:
            try:
                # 1. ACTUALIZAR PRECIO (CADA 1 SEGUNDO) - PRIORIDAD MÁXIMA
                precio_fresco = self.exchange.obtener_precio_actual(self.simbolo_actual)
                if precio_fresco > 0:
                    self.estado.precio_actual = precio_fresco
                
                # 2. PROCESAR TRADING (CADA 2 SEGUNDOS)
                if contador_pesado % 2 == 0:
                    await self._procesar_trading()
                
                # 3. ACTUALIZAR DASHBOARDS (WEB Y TELEGRAM)
                estado_real = await self.obtener_estado()
                actualizar_estado(estado_real)
                if self.telegram: await self.telegram.forzar_refresco(estado_real)
                
                contador_pesado += 1
                await asyncio.sleep(1) # El latido del bot ahora es de 1 segundo
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"❌ Loop error: {e}")
                await asyncio.sleep(5)

    async def _procesar_trading(self) -> None:
        try:
            posiciones_db = await self.persistencia.obtener_posiciones_abiertas()
            posicion_exchange = self.exchange.obtener_posicion(self.simbolo_actual)
            
            if posicion_exchange and not posiciones_db:
                logger.info(f"🔍 Detectada posición externa. Importando...")
                lado = OrderSide.LONG if posicion_exchange['side'] == 'long' else OrderSide.SHORT
                nueva_pos = Posicion(
                    order_id=f"ext_{int(datetime.now().timestamp())}",
                    symbol=self.simbolo_actual, side=lado,
                    entry_price=posicion_exchange['entry_price'],
                    quantity=posicion_exchange['size'],
                    leverage=posicion_exchange['leverage'],
                    dca_level=0, timestamp=datetime.now().timestamp()
                )
                await self.persistencia.guardar_posicion(nueva_pos)
                posiciones_db = [nueva_pos]
                
                # Crear ciclo si no existe
                if not await self.persistencia.obtener_ciclo_activo():
                    ciclo = CicloTrading(
                        ciclo_id=await self.persistencia.obtener_ultimo_ciclo_id() + 1,
                        symbol=self.simbolo_actual,
                        direccion_inicial=TradeDirection.LONG if lado == OrderSide.LONG else TradeDirection.SHORT,
                        capital_inicial=self.exchange.obtener_balance_total_usdt(),
                        timestamp_inicio=datetime.now().timestamp()
                    )
                    await self.persistencia.guardar_ciclo(ciclo)

            self.estado.posiciones = posiciones_db
            if not posiciones_db: await self._buscar_nueva_oportunidad()
            else: await self._gestionar_posicion_existente(posiciones_db)
        except Exception as e:
            logger.error(f"❌ Procesar error: {e}")

    async def _buscar_nueva_oportunidad(self) -> None:
        try:
            balance = self.exchange.obtener_balance_total_usdt()
            analis = self.estrategia.analizar_y_decidir(self.simbolo_actual)
            
            if analis.direccion != TradeDirection.NEUTRAL:
                posicion = await self.estrategia.abrir_posicion_inicial(self.simbolo_actual, analis.direccion, balance)
                if posicion:
                    ciclo = CicloTrading(
                        ciclo_id=await self.persistencia.obtener_ultimo_ciclo_id() + 1,
                        symbol=self.simbolo_actual,
                        direccion_inicial=analis.direccion,
                        capital_inicial=balance,
                        timestamp_inicio=datetime.now().timestamp()
                    )
                    await self.persistencia.guardar_ciclo(ciclo)
                    # Sincronización inmediata
                    estado_fresco = await self.obtener_estado()
                    actualizar_estado(estado_fresco)
                    if self.telegram: await self.telegram.forzar_refresco()
        except Exception as e:
            logger.error(f"❌ Buscar error: {e}")

    async def _gestionar_posicion_existente(self, posiciones: list) -> None:
        try:
            debe_tp, pnl = await self.estrategia.verificar_take_profit(posiciones)
            if debe_tp:
                await self._cerrar_con_profit(pnl)
                return
            
            debe_sl, _ = await self.estrategia.verificar_stop_loss(posiciones)
            if debe_sl:
                await self._cerrar_con_perdida()
                return
            
            nueva_pos = await self.estrategia.ejecutar_dca(self.simbolo_actual, posiciones, self.exchange.obtener_balance_total_usdt())
            if nueva_pos:
                posiciones = await self.persistencia.obtener_posiciones_abiertas()
            
            info = await self.estrategia.obtener_info_posiciones(posiciones)
            self.estado.precio_actual = info.get("precio_actual", 0)
            self.estado.pnl_no_realizado = info.get("pnl", 0)
            
            # ACTUALIZACIÓN DE ROE Y MAX DRAWDOWN HISTÓRICO
            roe_actual = info.get("pnl_pct", 0)
            self.estado.pnl_pct = roe_actual
            
            # El Drawdown solo cuenta si es pérdida (negativo)
            # Recordamos el valor más bajo (el más negativo)
            if roe_actual < 0:
                self.estado.max_drawdown = min(self.estado.max_drawdown, roe_actual)
            
            self.estado.capital_invertido = info.get("capital_invertido", 0)
            self.estado.precio_liquidacion = info.get("liquidation_price", 0)
        except Exception as e:
            logger.error(f"❌ Gestionar error: {e}")

    async def _cerrar_con_profit(self, pnl: float) -> None:
        try:
            posiciones = await self.persistencia.obtener_posiciones_abiertas()
            exito, _ = await self.estrategia.cerrar_posiciones(posiciones, "tp")
            if exito:
                self.estado.pnl_realizado += pnl
                self.estado.ciclos_completados += 1
                await self.persistencia.actualizar_estado_bot(pnl_realizado=self.estado.pnl_realizado, ciclos_completados=self.estado.ciclos_completados)
                
                # Verificar modo 'Última Operación'
                if getattr(self.estado, 'parar_tras_tp', False):
                    logger.info("🛑 MODO ÚLTIMA OP: Deteniendo bot tras beneficio...")
                    await self.detener_trading()
                    if self.telegram: await self.telegram.notificar("🛑 <b>META ALCANZADA</b>\n\nEl bot se ha detenido automáticamente tras completar la última operación con éxito.")
                    return

                # Verificar límite de ciclos
                max_ciclos = self.config.max_ciclos
                if max_ciclos > 0 and self.estado.ciclos_completados >= max_ciclos:
                    logger.info(f"🛑 Límite de ciclos alcanzado: {self.estado.ciclos_completados}/{max_ciclos}. Deteniendo bot...")
                    await self.detener_trading()
                    if self.telegram: await self.telegram.notificar(f"🔴 <b>BOT DETENIDO</b>\n\nSe completaron {max_ciclos} ciclos.")
                    return
                
                # Sync inmediato
                estado_fresco = await self.obtener_estado()
                actualizar_estado(estado_fresco)
                if self.telegram: await self.telegram.forzar_refresco()
                if self.estado.ciclo_actual:
                    await self.persistencia.cerrar_ciclo(self.estado.ciclo_actual.ciclo_id, self.exchange.obtener_balance_total_usdt(), pnl)
                    self.estado.ciclo_actual = None
                if cfg.REINVEST_MODE and self.estado.running:
                    await asyncio.sleep(5)
                    await self._buscar_nueva_oportunidad()
        except Exception: pass

    async def _cerrar_con_perdida(self) -> None:
        try:
            posiciones = await self.persistencia.obtener_posiciones_abiertas()
            exito, _ = await self.estrategia.cerrar_posiciones(posiciones, "sl")
            if exito:
                self.estado.ciclos_completados += 1
                
                # Verificar límite de ciclos
                max_ciclos = self.config.max_ciclos
                if max_ciclos > 0 and self.estado.ciclos_completados >= max_ciclos:
                    logger.info(f"🛑 Límite de ciclos alcanzado: {self.estado.ciclos_completados}/{max_ciclos}. Deteniendo bot...")
                    await self.detener_trading()
                    if self.telegram: await self.telegram.notificar(f"🔴 <b>BOT DETENIDO</b>\n\nSe completaron {max_ciclos} ciclos.")
                    return
                
                estado_fresco = await self.obtener_estado()
                actualizar_estado(estado_fresco)
                if self.telegram: await self.telegram.forzar_refresco()
                if self.estado.ciclo_actual:
                    await self.persistencia.cerrar_ciclo(self.estado.ciclo_actual.ciclo_id, self.exchange.obtener_balance_total_usdt(), 0)
                    self.estado.ciclo_actual = None
                await asyncio.sleep(10)
                await self._buscar_nueva_oportunidad()
        except Exception: pass

    async def cerrar(self) -> None:
        if self.estado.running: await self.detener_trading()
        if self.telegram: await self.telegram.detener()
        if self.exchange: self.exchange.cerrar()
        if self.persistencia: await self.persistencia.cerrar()

async def main():
    bot = BotTrading()
    if await bot.inicializar():
        try:
            while True: await asyncio.sleep(1)
        except asyncio.CancelledError: pass
        finally: await bot.cerrar()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("👋 Bot detenido")
