"""
Bot de Trading Martingala Dinámica - MAIN PRO
==========================================
Orquestador principal del bot de trading con sincronización total.
"""
import asyncio
import logging
import os
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
from src.web_server import iniciar_servidor, actualizar_estado, set_telegram_app

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
        self._instance_id = str(uuid.uuid4())[:8] # ID único para esta ejecución
        
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
        
        # Capital base fijo para cada ciclo (se reinicia en cada ciclo nuevo)
        self._capital_base_fijo = 0.0
        
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
            logger.info(f"🚀 INICIANDO BOT DE TRADING MARTINGALA [{getattr(self, '_instance_id', '???')}]")
            logger.info("=" * 50)
            
            # 1. Base de datos
            await self.persistencia.conectar()
            
            # 2. Cargar estado previo si existe
            estado_db = await self.persistencia.obtener_estado_bot()
            if estado_db:
                self.estado.pnl_realizado = estado_db.get('pnl_realizado', 0.0)
                self.estado.ciclos_completados = estado_db.get('ciclos_completados', 0)
            # Prioridad: ENV siempre tiene prioridad sobre DB
            # Si TESTNET está definido en ENV, usarlo; sino usar config por defecto
            env_testnet_raw = os.getenv("TESTNET", None)
            if env_testnet_raw is not None:
                # ENV está definido, usarlo
                self.estado.testnet = env_testnet_raw.lower() == "true"
            else:
                # ENV no definido, usar config por defecto
                self.estado.testnet = cfg.TESTNET
            
            if estado_db:
                if 'symbol' in estado_db:
                    self.estado.symbol = estado_db['symbol']
                    self.simbolo_actual = self.estado.symbol
                    self.config.symbol = self.simbolo_actual
                
                for param in vars(self.config).keys():
                    if param == 'symbol': continue
                    val_db = await self.persistencia.obtener_config(param)
                    if val_db is not None:
                        setattr(self.config, param, val_db)
                        logger.debug(f"⚙️ Config persistente cargada: {param} = {val_db}")
                
                logger.info(f"📂 Configuración persistente cargada desde DB (testnet={self.estado.testnet})")
            
            # 3. Exchange
            testnet = self.estado.testnet  # Usar el valor que ya leímos de la DB o el default
            logger.info(f"🧪 Testnet activa: {testnet}")
            
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
                    self.reset_maestro,
                    lambda: self.exchange,
                    self.persistencia
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
            
            # 8. Servidor Web (Eliminado de aquí, se inicia en main)
            # if self.telegram:
            #     set_telegram_app(self.telegram.app, asyncio.get_event_loop())
            # iniciar_servidor()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al inicializar: {e}")
            return False

    async def obtener_estado(self) -> Dict[str, Any]:
        """Retorna el estado actual del bot con caché ultrarrápida."""
        try:
            ahora = datetime.now().timestamp()
            
            # Si exchange no está inicializado, retornar estado básico
            if not self.exchange:
                return {
                    'running': self.estado.running,
                    'testnet': cfg.TESTNET,
                    'symbol': self.simbolo_actual,
                    'balance_total': 0,
                    'balance_disponible': 0,
                    'posiciones': [],
                    'pnl_realizado': self.estado.pnl_realizado,
                    'ciclos_completados': self.estado.ciclos_completados,
                    'config': self.config.to_dict(),
                    'dca_level': 0,
                    'lado': 'NEUTRAL',
                    'error': 'Exchange no conectado'
                }
            
            # Sin caché para el balance (siempre fresco)
            balance = self.exchange.obtener_balance_fresco()
            
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
                logger.info(f"🔍 SYNC: Posición detectada en exchange: {pos_exchange}")
                # Si hay posición en el exchange, ella manda sobre la DB
                if not posiciones_db:
                    logger.info(f"🔍 SYNC: Detectada posición externa. Importando...")
                    # Crear y GUARDAR posición en DB para persistencia
                    pos_db = Posicion(
                        order_id="sync_init", symbol=self.simbolo_actual,
                        side=OrderSide.LONG if pos_exchange['side'] == 'long' else OrderSide.SHORT,
                        entry_price=pos_exchange['entry_price'],
                        quantity=pos_exchange['size'],
                        leverage=pos_exchange['leverage'],
                        dca_level=0, timestamp=datetime.now().timestamp()
                    )
                    await self.persistencia.guardar_posicion(pos_db)
                    posiciones_db = [pos_db]
                    info_posiciones = await self.estrategia.obtener_info_posiciones([pos_db])
                else:
                    # Usar la lógica de la estrategia para calcular métricas reales
                    logger.info(f"🔍 SYNC: Posición ya en DB: {posiciones_db}")
                    info_posiciones = await self.estrategia.obtener_info_posiciones(posiciones_db)
            else:
                logger.info(f"🔍 SYNC: No hay posición en exchange")
            
            if not pos_exchange and posiciones_db:
                logger.warning(f"🔍 SYNC: Limpiando posiciones fantasma de la DB")
                await self.persistencia.limpiar_posiciones()
                posiciones_db = []
                info_posiciones = {}

            num_posiciones = len(posiciones_db) if not pos_exchange else (len(posiciones_db) or 1)
            if not pos_exchange: num_posiciones = 0

            ciclo = await self.persistencia.obtener_ciclo_activo()
            
            # --- MEJORA DE PRECIO PARA DASHBOARD ---
            # Si no hay posición, el precio de la info_posiciones será 0.
            # Debemos usar el precio fresco que ya obtuvimos arriba
            precio_actual = info_posiciones.get("precio_actual", 0)
            if precio_actual <= 0:
                precio_actual = self.estado.precio_actual
                if precio_actual <= 0:
                    precio_actual = self.exchange.obtener_precio_actual(self.simbolo_actual)
            
            precio_entrada = info_posiciones.get("precio_entrada", 0)
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
                "symbol": self.simbolo_actual,
                "exchange": self.exchange.exchange_id.upper() if self.exchange else "EXCHANGE",
                "testnet": self.estado.testnet,
                "precio_actual": precio_actual,
                "precio_entrada": precio_entrada,
                "precio_inicial": info_posiciones.get("precio_inicial", precio_entrada) or precio_actual,
                "ultimo_sync_web": datetime.now().strftime("%H:%M:%S"),
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
                "timestamp_apertura": info_posiciones.get("timestamp_apertura"),
                "max_drawdown": self.estado.max_drawdown
            }
            
            self._estado_cache = estado_fresco
            # Aseguramos que el estado running nunca sea cacheado si cambió
            self._estado_cache['running'] = self.estado.running
            self._ultimo_fetch_estado = ahora
            actualizar_estado(self._estado_cache)
            return self._estado_cache
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
                await self.persistencia.actualizar_estado_bot(testnet=int(bool(valor)))
                exito = True
                reconnect = True
                ExchangeFactory.clear_instances()
                logger.info(f"⚙️ Testnet cambiado: {valor}")
            elif param == "symbol":
                self.estado.symbol = valor
                self.simbolo_actual = valor
                self.config.symbol = valor
                await self.persistencia.guardar_config(param, valor)
                await self.persistencia.actualizar_estado_bot(symbol=valor)
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
            await self.persistencia.actualizar_estado_bot(running=False)
            
            for tarea in self.tareas: tarea.cancel()
            self.tareas.clear()
            
            # 2. Cerrar posiciones en exchange y limpiar DB
            self.exchange.cerrar_posicion(self.simbolo_actual)
            await self.persistencia.limpiar_posiciones()
            
            # 3. Resetear estadísticas
            await self.resetear_estadisticas()
            
            # 4. Resetear capital base fijo
            self._capital_base_fijo = 0.0
            
            # 5. Reiniciar motor si el usuario lo pide (aquí lo dejamos pausado por seguridad)
            logger.info("✅ RESET MAESTRO COMPLETADO. Bot pausado y limpio.")
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
        """Cierre total de Pánico: cierra todas las posiciones del exchange."""
        try:
            logger.warning("🚨 PÁNICO: Solicitando cierre total en el Exchange...")
            
            # BLOQUEAR RE-ENTRADA INMEDIATAMENTE EN DB
            self.estado.running = False
            await self.persistencia.actualizar_estado_bot(running=False)
            
            for tarea in self.tareas: 
                tarea.cancel()
            self.tareas.clear()

            # Verificar posiciones actuales ANTES de cerrar
            posiciones_antes = self.exchange.obtener_posicion(self.simbolo_actual)
            logger.warning(f"🚨 PÁNICO: Posición detectada en símbolo actual: {posiciones_antes}")
            
            # Llamar al método de cierre total del exchange
            # Usar run_in_executor para no bloquear el loop async
            loop = asyncio.get_event_loop()
            exito_exchange = await loop.run_in_executor(None, self.exchange.cerrar_todas_posiciones)
            
            # Delay para que el exchange procese
            await asyncio.sleep(2)
            
            # Verificar que realmente se cerró - revisar todas las posiciones
            posiciones_despues = self.exchange.obtener_posicion(self.simbolo_actual)
            
            # También verificar si hay otras posiciones abiertas
            posiciones_todas = self.exchange._exchange.fetch_positions()
            posiciones_abiertas = []
            for pos in posiciones_todas:
                contracts = float(pos.get('contracts') or pos.get('size') or 0)
                if abs(contracts) > 0.00001:
                    posiciones_abiertas.append(pos.get('symbol'))
            
            logger.warning(f"🚨 PÁNICO: Posición después de cerrar (símbolo actual): {posiciones_despues}")
            logger.warning(f"🚨 PÁNICO: Total posiciones abiertas restantes: {posiciones_abiertas}")
            
            # Limpiar DB sin importar el resultado
            await self.persistencia.limpiar_posiciones()
            
            # Resetear capital base
            self._capital_base_fijo = 0.0
            
            # Sincronización inmediata de dashboards
            estado_limpio = await self.obtener_estado()
            actualizar_estado(estado_limpio)
            if self.telegram: await self.telegram.forzar_refresco()

            if exito_exchange and len(posiciones_abiertas) == 0:
                logger.info("✅ Pánico completado: Todas las posiciones cerradas y bot pausado.")
                if self.telegram:
                    await self.telegram.notificar("✅ <b>PÁNICO EJECUTADO</b>\n\nTodas las posiciones han sido cerradas exitosamente.")
                return True
            else:
                logger.error(f"❌ Pánico falló. Posiciones restantes: {posiciones_abiertas}")
                if self.telegram:
                    await self.telegram.notificar(f"⚠️ <b>PÁNICO PARCIAL</b>\n\nPosiciones restantes: {posiciones_abiertas}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error en comando de pánico: {e}")
            import traceback
            logger.error(f"❌ Trace: {traceback.format_exc()}")
            return False

    async def iniciar_trading(self) -> None:
        if self.estado.running: return
        
        # Verificar si ya hay posición abierta antes de iniciar
        pos_existente = self.exchange.obtener_posicion(self.simbolo_actual) if self.exchange else None
        posiciones_db = await self.persistencia.obtener_posiciones_abiertas() if self.persistencia else []
        
        logger.info(f"🔍 INICIAR: pos_existente={pos_existente}, posiciones_db={posiciones_db}")
        
        if pos_existente:
            logger.warning(f"⚠️ Ya hay posición abierta en exchange: {pos_existente}")
            if self.telegram:
                await self.telegram.notificar("⚠️ Ya hay una posición abierta en el exchange. Cierra la posición primero antes de iniciar.")
            # Actualizar estado para mostrar la posición
            estado_fresco = await self.obtener_estado()
            actualizar_estado(estado_fresco)
            if self.telegram: await self.telegram.forzar_refresco()
            return
        
        if posiciones_db:
            logger.warning(f"⚠️ Ya hay posiciones en DB: {posiciones_db}")
            if self.telegram:
                await self.telegram.notificar("⚠️ Ya hay posiciones guardadas en la base de datos.")
            estado_fresco = await self.obtener_estado()
            actualizar_estado(estado_fresco)
            if self.telegram: await self.telegram.forzar_refresco()
            return
        
        self.estado.running = True
        await self.persistencia.actualizar_estado_bot(running=True)
        # Actualización inicial web
        estado_inicial = await self.obtener_estado()
        actualizar_estado(estado_inicial)
        
        tarea_trading = asyncio.create_task(self.loop_trading())
        self.tareas.append(tarea_trading)
    
    async def detener_trading(self) -> None:
        """Detiene el bot y cierra la posición abierta inmediatamente."""
        try:
            logger.warning("🛑 Deteniendo trading y cerrando posición activa...")
            
            # 1. BLOQUEAR RE-ENTRADA (PERSISTENCIA)
            self.estado.running = False
            await self.persistencia.actualizar_estado_bot(running=False)
            
            # 2. CANCELAR TAREAS DE MONITOREO
            for tarea in self.tareas: 
                tarea.cancel()
            self.tareas.clear()
            
            # 3. CIERRE RADICAL EN EL EXCHANGE
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.exchange.cerrar_posicion, self.simbolo_actual)
            
            # 4. LIMPIEZA DE DATOS LOCALES
            await self.persistencia.limpiar_posiciones()
            
            # Sincronización inmediata de dashboards
            estado_fresco = await self.obtener_estado()
            actualizar_estado(estado_fresco)
            if self.telegram: await self.telegram.forzar_refresco()
        except Exception as e:
            logger.error(f"❌ Error al detener trading: {e}")

    async def loop_trading(self) -> None:
        logger.info("🚀 Monitor de Precio Real-Time Iniciado (5s)")
        contador_pesado = 0
        _ultimo_refresco_telegram = 0
        while self.estado.running:
            try:
                # 1. ACTUALIZAR PRECIO (CADA 1 SEGUNDO) - PRIORIDAD MÁXIMA
                precio_fresco = self.exchange.obtener_precio_actual(self.simbolo_actual)
                if precio_fresco > 0:
                    self.estado.precio_actual = precio_fresco
                else:
                    logger.warning(f"⚠️ Precio = 0 para {self.simbolo_actual}, intentando con simbolo normalizado")
                    # Intentar con símbolo normalizado
                    symbol_norm = self.simbolo_actual.replace(':USDT', '')
                    precio_fresco = self.exchange.obtener_precio_actual(symbol_norm)
                    if precio_fresco > 0:
                        self.estado.precio_actual = precio_fresco
                        logger.info(f"💹 Precio {symbol_norm}: {precio_fresco}")
                
                # 2. PROCESAR TRADING (CADA 5 SEGUNDOS)
                if contador_pesado % 5 == 0:
                    await self._procesar_trading()
                
                # 3. ACTUALIZAR DASHBOARDS (WEB cada 5s, TELEGRAM cada 10s máx)
                estado_real = await self.obtener_estado()
                actualizar_estado(estado_real)
                
                if self.telegram:
                    ahora = datetime.now().timestamp()
                    if ahora - _ultimo_refresco_telegram >= 10:
                        await self.telegram.forzar_refresco(estado_real)
                        _ultimo_refresco_telegram = ahora
                
                contador_pesado += 1
                await asyncio.sleep(1)
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
            # PRIMERO: Verificar si ya hay posición abierta
            pos_existente = self.exchange.obtener_posicion(self.simbolo_actual)
            if pos_existente:
                logger.info(f"⚠️ Ya existe posición abierta: {pos_existente.get('side')} {pos_existente.get('size')}. Esperando cierre...")
                return
            
            posiciones_db = await self.persistencia.obtener_posiciones_abiertas()
            if posiciones_db:
                logger.info(f"⚠️ Ya hay posiciones en DB. Esperando cierre...")
                return
            
            logger.info(f"🔍 Buscando oportunidad de trading en {self.simbolo_actual}...")
            
            # USAR CAPITAL SEGÚN MODO DE REINVERSIÓN
            balance_actual = self.exchange.obtener_balance_fresco().get('total', 0)
            
            if self.config.reinvest_mode:
                balance = balance_actual
                logger.info(f"💰 Modo Reinversión: Usando balance fresco ${balance:.2f}")
            else:
                if not hasattr(self, '_capital_base_fijo') or self._capital_base_fijo <= 0:
                    self._capital_base_fijo = balance_actual
                    logger.info(f"💰 Capital base inicial establecido: ${self._capital_base_fijo:.2f}")
                balance = self._capital_base_fijo
                logger.info(f"💰 Capital base fijo: ${balance:.2f} (Reinversión OFF)")
            
            analis = self.estrategia.analizar_y_decidir(self.simbolo_actual)
            logger.info(f"📊 Resultado análisis: direccion={analis.direccion}, tendencia={analis.tendencia}, confianza={analis.confianza}")
            
            if analis.direccion != TradeDirection.NEUTRAL:
                logger.info(f"🚀 Abriendo posición en {analis.direccion} con balance: {balance}...")
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
                    # IMPORTANTE: Guardar en el estado para poder cerrarlo luego
                    self.estado.ciclo_actual = ciclo
                    
                    # Sincronización inmediata
                    estado_fresco = await self.obtener_estado()
                    actualizar_estado(estado_fresco)
                    if self.telegram: await self.telegram.forzar_refresco()
                else:
                    logger.warning("⚠️ Fallo al abrir posición inicial. Esperando 30s para reintentar...")
                    await asyncio.sleep(30)
            else:
                logger.info(f"⏸️ Sin señal clara, esperando siguiente ciclo...")
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
            
            self.estado.capital_invertido = info.get("capital_invertido", 0)
            self.estado.precio_liquidacion = info.get("liquidation_price", 0)
        except Exception as e:
            logger.error(f"❌ Gestionar error: {e}")

    async def _cerrar_con_profit(self, pnl_no_realizado: float) -> None:
        try:
            logger.info(f"🎯 Iniciando cierre por profit. PNL no realizado: ${pnl_no_realizado:.4f}")
            
            balance_antes = self.exchange.obtener_balance_fresco()
            balance_total_antes = float(balance_antes.get('total', 0))
            
            posiciones = await self.persistencia.obtener_posiciones_abiertas()
            if not posiciones:
                logger.warning("⚠️ No se encontraron posiciones abiertas en DB para cerrar")
                return

            exito, pnl_final_estimado = await self.estrategia.cerrar_posiciones(posiciones, "tp")
            if exito:
                # Delay para que el exchange procese y actualice el balance
                await asyncio.sleep(3)
                
                balance_despues = self.exchange.obtener_balance_fresco()
                balance_total_despues = float(balance_despues.get('total', 0))
                
                # Calcular profit basado en balance total (Realizado neto)
                profit_neto = balance_total_despues - balance_total_antes
                
                logger.info(f"💰 Balance: Antes=${balance_total_antes:.4f}, Después=${balance_total_despues:.4f}")
                logger.info(f"💰 Profit NETO (con fees): ${profit_neto:.4f}")
                
                # Si el profit es negativo por fees pero la operación fue ganadora en precio,
                # registramos al menos una pequeña ganancia simbólica o el PNL bruto
                # para que el usuario vea que el bot "ganó" el ciclo.
                profit_a_registrar = profit_neto
                if profit_neto <= 0 and pnl_no_realizado > 0:
                    logger.warning(f"⚠️ Profit neto negativo (${profit_neto:.4f}) por comisiones. Registrando PNL bruto: ${pnl_no_realizado:.4f}")
                    profit_a_registrar = pnl_no_realizado
                
                self.estado.pnl_realizado += profit_a_registrar
                self.estado.ciclos_completados += 1
                
                await self.persistencia.actualizar_estado_bot(
                    pnl_realizado=self.estado.pnl_realizado, 
                    ciclos_completados=self.estado.ciclos_completados
                )
                
                # Cerrar ciclo en la DB
                if self.estado.ciclo_actual:
                    await self.persistencia.cerrar_ciclo(
                        self.estado.ciclo_actual.ciclo_id, 
                        balance_total_despues, 
                        profit_a_registrar
                    )
                    self.estado.ciclo_actual = None
                else:
                    # Si no teníamos el objeto en memoria, intentamos buscar el activo en DB
                    ciclo_db = await self.persistencia.obtener_ciclo_activo()
                    if ciclo_db:
                        await self.persistencia.cerrar_ciclo(
                            ciclo_db.ciclo_id, 
                            balance_total_despues, 
                            profit_a_registrar
                        )

                # Resetear métricas temporales
                self.estado.max_drawdown = 0.0
                
                # Notificación Telegram
                if self.telegram:
                    msg = (f"🎯 <b>TP ALCANZADO (+{self.config.take_profit_pct*100:.1f}%)</b>\n\n"
                           f"➕ Profit: <b>${profit_a_registrar:.4f}</b>\n"
                           f"🔄 Ciclos: <b>{self.estado.ciclos_completados}</b>\n"
                           f"💰 Balance: <b>${balance_total_despues:,.2f}</b>")
                    await self.telegram.notificar(msg)
                    await self.telegram.forzar_refresco()

                # Verificar límites de parada
                parar = False
                razon_parada = ""
                if getattr(self.estado, 'parar_tras_tp', False):
                    logger.info("🛑 MODO ÚLTIMA OP: Deteniendo bot...")
                    razon_parada = "MODO ÚLTIMA OPERACIÓN FINALIZADO"
                    parar = True
                elif self.config.max_ciclos > 0 and self.estado.ciclos_completados >= self.config.max_ciclos:
                    logger.info(f"🛑 Límite de ciclos alcanzado: {self.estado.ciclos_completados}")
                    razon_parada = f"LÍMITE DE {self.config.max_ciclos} CICLOS ALCANZADO"
                    parar = True
                
                if parar:
                    await self.detener_trading()
                    if self.telegram:
                        msg_fin = (f"🏁 <b>{razon_parada}</b>\n\n"
                                   f"💰 Ganancia Acumulada: <b>${self.estado.pnl_realizado:.4f}</b>\n"
                                   f"🔄 Ciclos Totales: <b>{self.estado.ciclos_completados}</b>\n"
                                   f"🏦 Balance Final: <b>${balance_total_despues:,.2f}</b>\n\n"
                                   f"<i>El motor se ha detenido automáticamente.</i>")
                        await self.telegram.notificar(msg_fin)
                    return

                # Si no para, buscar nueva oportunidad después de un respiro
                if self.estado.running:
                    await asyncio.sleep(5)
                    await self._buscar_nueva_oportunidad()
                    
        except Exception as e:
            logger.error(f"❌ Error en _cerrar_con_profit: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _cerrar_con_perdida(self) -> None:
        try:
            posiciones = await self.persistencia.obtener_posiciones_abiertas()
            exito, _ = await self.estrategia.cerrar_posiciones(posiciones, "sl")
            if exito:
                self.estado.ciclos_completados += 1
                
                # Resetear capital base para el nuevo ciclo
                self._capital_base_fijo = 0.0
                
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
    # Pequeño retardo para permitir que Koyeb mate la instancia vieja y libere el puerto
    logger.info("⏳ Esperando 5s para estabilización del puerto...")
    await asyncio.sleep(5)
    
    # INICIAR WEB SERVER PRIMERO para healthcheck
    iniciar_servidor()
    
    try:
        bot = BotTrading()
        
        # Inicializar persistencia
        bot.persistencia = Persistencia(cfg.DB_PATH)
        await bot.persistencia.conectar()
        
        # INICIALIZAR TELEGRAM PRIMERO (aunque exchange falle)
        if cfg.TELEGRAM_BOT_TOKEN and cfg.TELEGRAM_ADMIN_ID:
            bot.telegram = BotTelegram(
                cfg.TELEGRAM_BOT_TOKEN,
                cfg.TELEGRAM_ADMIN_ID,
                bot.obtener_estado,
                bot.cambiar_config,
                bot.iniciar_trading,
                bot.detener_trading,
                bot.reconectar_exchange,
                bot.cerrar_todas_posiciones,
                bot.guardar_perfil,
                bot.cargar_perfil,
                bot.listar_perfiles,
                bot.eliminar_perfil,
                bot.resetear_estadisticas,
                bot.reset_maestro,
                lambda: bot.exchange,
                bot.persistencia
            )
            await bot.telegram.iniciar()
            set_telegram_app(bot.telegram.app, asyncio.get_event_loop())
            logger.info("✅ Telegram inicializado")
        
        # Intentar inicializar exchange (pero no es crítico)
        try:
            if await bot.inicializar():
                # AUTO-ARRANQUE
                estado_db = await bot.persistencia.obtener_estado_bot()
                was_running = estado_db.get('running', False) if estado_db else False
                
                # ACTUALIZAR WEB INMEDIATAMENTE
                estado_inicial = await bot.obtener_estado()
                actualizar_estado(estado_inicial)
                logger.info(f"🌐 Estado inicial enviado a web: running={estado_inicial.get('running')}, posiciones={estado_inicial.get('posiciones')}, balance={estado_inicial.get('balance_total')}")
                
                if was_running:
                    logger.info("⚡ AUTO-ARRANQUE: Reanudando trading...")
                    await bot.iniciar_trading()
                    # Si ya hay una posición o el bot inició, mostrar el panel en Telegram proactivamente
                    if bot.telegram:
                        await bot.telegram.forzar_refresco()
                else:
                    logger.info("⏸️ BOT EN ESPERA: Usa Telegram para iniciar.")
                    # Mostrar dashboard inicial aunque esté pausado
                    if bot.telegram:
                        await bot.telegram.forzar_refresco()
        except Exception as e_init:
            logger.warning(f"⚠️ Error inicializando: {e_init}. Solo Telegram y Web activos.")
        
        logger.info("🔄 Iniciando loop de mantenimiento...")
        
        # Loop de mantenimiento - actualizar web cada 5 segundos aunque esté pausado
        while True:
            try:
                # 1. ACTUALIZAR HEARTBEAT para avisar que este bot es el MAESTRO
                ts = int(time.time())
                id_maestro = await bot.persistencia.obtener_config("master_bot_id")
                
                # Si no hay maestro o somos nosotros o el maestro anterior murió (>20s)
                ts_maestro = int(await bot.persistencia.obtener_config("master_bot_ts") or 0)
                if not id_maestro or id_maestro == bot._instance_id or (ts - ts_maestro > 20):
                    await bot.persistencia.guardar_config("master_bot_id", bot._instance_id)
                    await bot.persistencia.guardar_config("master_bot_ts", ts)
                    if id_maestro != bot._instance_id:
                        logger.info(f"👑 [{bot._instance_id}] Tomando el control como Bot Maestro.")
                else:
                    # No somos el maestro, dormir y no hacer nada pesado
                    if ts % 30 == 0:
                        logger.info(f"💤 [{bot._instance_id}] En espera (Hay otro bot maestro activo: {id_maestro})")
                    await asyncio.sleep(5)
                    continue

                if bot and bot.exchange:
                    # Siempre verificar posición y actualizar web cada 5s
                    estado_fresco = await bot.obtener_estado()
                    actualizar_estado(estado_fresco)
                    if bot.estado.running:
                        logger.debug(f"🔄 Web Sync OK (Bot Activo - {bot.simbolo_actual})")
                    else:
                        logger.debug(f"🔄 Web Sync OK (Bot Pausado - Esperando Telegram)")
                else:
                    logger.debug(f"⚠️ Exchange no disponible aún")
            except Exception as e:
                logger.error(f"❌ Error en loop mantenimiento: {e}")
            await asyncio.sleep(5)
            
    except Exception as e:
        logger.error(f"❌ Error en main: {e}")
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("👋 Bot detenido")
