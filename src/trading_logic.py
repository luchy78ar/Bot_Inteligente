"""
Lógica de Trading - Estrategia Martingala Dinámica PRO
====================================================
Análisis de tendencia, gestión de posiciones DCA, y toma de decisiones.
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import pandas as pd
import pandas_ta as ta
import numpy as np

from src.models import (
    Posicion, CicloTrading, ConfiguracionTrading, 
    TradeDirection, OrderSide, ResultadoAnalisis
)
from src.exchange_manager import ExchangeWrapper
from src.persistence import Persistencia

logger = logging.getLogger(__name__)


class AnalizadorTendencia:
    def __init__(self, exchange: ExchangeWrapper):
        self.exchange = exchange
    
    def analizar(self, symbol: str, timeframe: str = '15m', indicador: str = 'EMA') -> ResultadoAnalisis:
        try:
            logger.info(f"📊 Analizando {symbol} en {timeframe}...")
            df = self.exchange.obtener_ohlcv(symbol, timeframe, limite=100)
            if df.empty:
                logger.warning(f"⚠️ Sin datos OHLCV para {symbol}")
                return ResultadoAnalisis(TradeDirection.NEUTRAL, "sin datos", 0, 0)
            
            precio_actual = df['close'].iloc[-1]
            logger.info(f"📈 Precio actual: {precio_actual}")
            
            df['EMA_9'] = ta.ema(df['close'], length=9)
            df['EMA_21'] = ta.ema(df['close'], length=21)
            
            ema_9 = df['EMA_9'].iloc[-1]
            ema_21 = df['EMA_21'].iloc[-1]
            
            logger.info(f"📉 EMA-9: {ema_9:.4f}, EMA-21: {ema_21:.4f}")
            
            if ema_9 > ema_21:
                logger.info(f"✅ Señal: LONG (alcista)")
                return ResultadoAnalisis(TradeDirection.LONG, "alcista", 70, precio_actual)
            elif ema_9 < ema_21:
                logger.info(f"✅ Señal: SHORT (bajista)")
                return ResultadoAnalisis(TradeDirection.SHORT, "bajista", 70, precio_actual)
            logger.info(f"⏸️ Señal: NEUTRAL")
            return ResultadoAnalisis(TradeDirection.NEUTRAL, "neutral", 50, precio_actual)
        except Exception as e:
            logger.error(f"❌ Error análisis: {e}")
            return ResultadoAnalisis(TradeDirection.NEUTRAL, "error", 0, 0)


class EstrategiaMartingala:
    def __init__(self, exchange: ExchangeWrapper, persistencia: Persistencia,
                 config: ConfiguracionTrading, on_error_callback: Optional[Any] = None):
        self.exchange = exchange
        self.persistencia = persistencia
        self.config = config
        self.analizador = AnalizadorTendencia(exchange)
        self.on_error_callback = on_error_callback
        self.resetear_notificaciones()
    
    def resetear_notificaciones(self) -> None:
        self._ultima_notificacion_margen = 0
        self._tp_activado = False
    
    def analizar_y_decidir(self, symbol: str) -> ResultadoAnalisis:
        return self.analizador.analizar(symbol, self.config.trend_timeframe, 'EMA')
    
    async def calcular_tamano_posicion(self, symbol: str, balance: float, precio: float, nivel_dca: int = 0) -> float:
        try:
            logger.info(f"🔔 calcular_tamano_posicion: balance={balance}, precio={precio}, leverage={self.config.leverage}, initial_volume_pct={self.config.initial_volume_pct}")
            
            notional_minimo = 6.2
            volumen_usdt = (balance * self.config.initial_volume_pct) * self.config.leverage
            volumen_real = max(volumen_usdt, notional_minimo)
            
            logger.info(f"🔔 volumen_usdt={volumen_usdt}, volumen_real={volumen_real}")
            
            volumen_actual = volumen_real * (self.config.volume_multiplier ** nivel_dca)
            
            cantidad_maxima = self.exchange.calcular_posicion_maxima(symbol, self.config.leverage, precio)
            logger.info(f"🔔 cantidad_maxima={cantidad_maxima}, volumen_actual={volumen_actual}")
            
            if cantidad_maxima <= 0:
                return 0
            
            cantidad = min(volumen_actual / precio, cantidad_maxima)
            logger.info(f"🔔 cantidad antes de precision={cantidad}")
            return self.exchange.cantidad_a_precision(symbol, cantidad)
        except Exception as e:
            logger.error(f"❌ Error calculando tamaño: {e}")
            return 0.0
    
    async def abrir_posicion_inicial(self, symbol: str, direccion: TradeDirection, balance: float) -> Optional[Posicion]:
        try:
            precio = self.exchange.obtener_precio_actual(symbol)
            logger.info(f"🔔 Precio actual: {precio}")
            
            cantidad = await self.calcular_tamano_posicion(symbol, balance, precio, 0)
            logger.info(f"🔔 Cantidad calculada: {cantidad}")
            
            if cantidad <= 0: 
                logger.warning(f"⚠️ Cantidad <= 0, no se puede abrir posición")
                return None
            
            lado = 'long' if direccion == TradeDirection.LONG else 'short'
            logger.info(f"🔔 Abriendo posición: {lado} con {cantidad}")
            
            orden = self.exchange.abrir_posicion(symbol, lado, cantidad, self.config.leverage)
            
            if orden and 'id' in orden:
                posicion = Posicion(
                    order_id=orden['id'], symbol=symbol, side=OrderSide(lado),
                    entry_price=precio, quantity=cantidad, leverage=self.config.leverage,
                    dca_level=0, timestamp=datetime.now().timestamp()
                )
                await self.persistencia.guardar_posicion(posicion)
                logger.info(f"🚀 Posición inicial abierta: {lado.upper()} {cantidad} @ {precio}")
                return posicion
            logger.warning(f"⚠️ No se pudo abrir posición, orden sin ID")
            return None
        except Exception as e:
            logger.error(f"❌ Error abriendo inicial: {e}")
            import traceback
            logger.error(f"❌ Trace: {traceback.format_exc()}")
            return None

    async def ejecutar_dca(self, symbol: str, posiciones: List[Posicion], balance: float) -> Optional[Posicion]:
        try:
            if not posiciones: return None
            nivel_actual = max(p.dca_level for p in posiciones)
            if nivel_actual >= self.config.max_dca_levels: return None
            
            info = await self.obtener_info_posiciones(posiciones)
            precio_actual = info.get('precio_actual', 0)
            precio_avg = info.get('precio_entrada', 0) # AVG
            lado = info.get('lado', 'LONG')
            
            # 1. CALCULAR DISTANCIA DINÁMICA (Step Multiplier)
            mult_step = getattr(self.config, 'step_multiplier', 1.1)
            umbral_step_actual = self.config.dca_step_pct * (mult_step ** nivel_actual)
            
            # CALCULAR CAÍDA DE PRECIO RESPECTO AL AVG
            variacion_precio = (precio_actual - precio_avg) / precio_avg
            caida_precio_pct = abs(variacion_precio * 100)
            objetivo_pct = umbral_step_actual * 100
            
            logger.info(f"📉 DCA check: lado={lado}, Caída desde AVG={caida_precio_pct:.3f}%, Step Dinámico={objetivo_pct:.3f}% (Nivel {nivel_actual})")
            
            # 2. VALIDACIÓN DE PRECIO Y UMBRAL
            ultima_pos = max(posiciones, key=lambda p: p.dca_level)
            precio_ultimo_dca = ultima_pos.entry_price
            
            if lado == 'LONG':
                # El precio debe ser menor al último DCA Y haber caído lo suficiente (Step Dinámico)
                if precio_actual >= precio_ultimo_dca or caida_precio_pct < objetivo_pct:
                    return None
            else: # SHORT
                # El precio debe ser mayor al último DCA Y haber subido lo suficiente (Step Dinámico)
                if precio_actual <= precio_ultimo_dca or caida_precio_pct < objetivo_pct:
                    return None
            
            nuevo_nivel = nivel_actual + 1
            cantidad = await self.calcular_tamano_posicion(symbol, balance, precio_actual, nuevo_nivel)
            
            if cantidad <= 0:
                logger.warning(f"⚠️ DCA #{nuevo_nivel} cancelado: cantidad calculada <= 0")
                return None
            
            orden = self.exchange.abrir_posicion(symbol, lado.lower(), cantidad, self.config.leverage)
            if orden and 'id' in orden:
                nueva_pos = Posicion(
                    order_id=orden['id'], symbol=symbol, side=posiciones[0].side,
                    entry_price=precio_actual, quantity=cantidad, leverage=self.config.leverage,
                    dca_level=nuevo_nivel, timestamp=datetime.now().timestamp()
                )
                await self.persistencia.guardar_posicion(nueva_pos)
                logger.info(f"📉 DCA #{nuevo_nivel} ejecutado por AVG: {cantidad} @ {precio_actual}")
                return nueva_pos
            return None
        except Exception as e:
            logger.error(f"❌ Error en DCA: {e}")
            return None

    async def verificar_take_profit(self, posiciones: List[Posicion]) -> Tuple[bool, float]:
        try:
            if not posiciones: return False, 0
            info = await self.obtener_info_posiciones(posiciones)
            
            # ROI REAL (ROE%) - Beneficio sobre Margen Real
            roe_actual = info.get('pnl_pct', 0) / 100
            tp_objetivo = self.config.take_profit_pct
            
            if roe_actual >= tp_objetivo and not self._tp_activado:
                self._tp_activado = True
                self._max_roi = roe_actual
                # El piso inicial es el TP objetivo menos una pequeña holgura (0.05% de ROE)
                self._floor_roi = max(tp_objetivo, roe_actual - 0.0005)
                logger.info(f"🎯 ESCALERA ACTIVADA (ROE): Techo en {roe_actual*100:.2f}%, Piso en {self._floor_roi*100:.2f}%")
            
            if self.config.tp_inteligente and self._tp_activado:
                # Distancia de retroceso: usamos el 'Escalón' de la configuración como ROE directo
                # Si configuraste 0.2%, el precio no puede caer más de 0.2% de ROE desde el máximo alcanzado
                distancia = getattr(self.config, 'trailing_distancia', 0.002) 
                
                if roe_actual > self._max_roi:
                    self._max_roi = roe_actual
                    nuevo_piso = roe_actual - distancia
                    if nuevo_piso > self._floor_roi:
                        self._floor_roi = nuevo_piso
                        logger.info(f"📈 ESCALÓN SUBE: Nuevo Piso en {self._floor_roi*100:.2f}% ROE")
                
                if roe_actual < self._floor_roi:
                    logger.info(f"🛑 CIERRE INTELIGENTE: ROE {roe_actual*100:.2f}% cayó bajo el piso {self._floor_roi*100:.2f}%")
                    return True, info.get('pnl', 0)
                return False, info.get('pnl', 0)
            
            return (roe_actual >= tp_objetivo), info.get('pnl', 0)
        except Exception: return False, 0

    async def verificar_stop_loss(self, posiciones: List[Posicion]) -> Tuple[bool, float]:
        if not posiciones or self.config.stop_loss_pct <= 0: return False, 0
        info = await self.obtener_info_posiciones(posiciones)
        
        # El Stop Loss también se basa en ROE% (Pérdida sobre margen real)
        roe_actual = info.get('pnl_pct', 0) / 100
        
        if roe_actual <= -self.config.stop_loss_pct:
            return True, info.get('pnl', 0)
        return False, 0

    async def cerrar_posiciones(self, posiciones: List[Posicion], razon: str = "close") -> Tuple[bool, float]:
        if not posiciones: return True, 0
        symbol = posiciones[0].symbol
        info = await self.obtener_info_posiciones(posiciones)
        exito = self.exchange.cerrar_posicion(symbol)
        if exito:
            self._tp_activado = False
            await self.persistencia.limpiar_posiciones()
        return exito, info.get('pnl', 0)

    async def obtener_info_posiciones(self, posiciones: List[Posicion]) -> Dict[str, Any]:
        """Calcula métricas reales y profesionales (ROE%)."""
        try:
            if not posiciones: return {}
            symbol = posiciones[0].symbol
            pos_info = self.exchange.obtener_posicion(symbol)
            if not pos_info: return {}
            
            # 1. PRECIOS Y CANTIDADES
            total_qty = sum(abs(p.quantity) for p in posiciones)
            total_cost = sum(abs(p.quantity) * p.entry_price for p in posiciones)
            avg_entry = total_cost / total_qty if total_qty > 0 else 0
            precio_avg = avg_entry # Definir para uso en proximidad
            
            precio_actual = self.exchange.obtener_precio_actual(symbol)
            lado = posiciones[0].side.value.upper()
            
            # 2. CÁLCULO DE VARIACIÓN DE PRECIO (No apalancada)
            if lado == 'LONG':
                variacion_precio = (precio_actual - avg_entry) / avg_entry if avg_entry > 0 else 0
            else:
                variacion_precio = (avg_entry - precio_actual) / avg_entry if avg_entry > 0 else 0

            # 3. MÉTRICAS DE CAPITAL REALES (ROE%)
            pnl = float(pos_info.get('unrealized_pnl', 0))
            # Usar el margen real que el exchange reporta para la posición
            capital_real = float(pos_info.get('margin', 0))
            
            # Si el exchange no reporta margen (raro), usar cálculo teórico como respaldo
            if capital_real <= 0:
                capital_real = total_cost / posiciones[0].leverage
            
            # ROE (Return on Equity) - Basado en capital REAL bloqueado
            roe_pct = (pnl / capital_real * 100) if capital_real > 0 else 0
            
            # 4. PROXIMIDAD DCA - Basada en el Step Dinámico desde el AVG
            mult_step = getattr(self.config, 'step_multiplier', 1.1)
            nivel_actual = info_posiciones.get('nivel_dca', 0) if 'info_posiciones' in locals() else max(p.dca_level for p in posiciones)
            
            # Si ya alcanzamos el máximo de niveles, no hay 'Próximo DCA'
            if nivel_actual >= self.config.max_dca_levels:
                proximidad_dca = 0
            else:
                umbral_step_actual = self.config.dca_step_pct * (mult_step ** nivel_actual)
                caida_desde_avg = abs(precio_actual - precio_avg) / precio_avg
                
                # Solo mostrar proximidad si el precio es peor que el AVG
                es_peor = (lado == 'LONG' and precio_actual < precio_avg) or (lado == 'SHORT' and precio_actual > precio_avg)
                
                if es_peor:
                    # La barra se llena respecto al Step Dinámico de este nivel
                    proximidad_dca = min(1.0, caida_desde_avg / umbral_step_actual) if umbral_step_actual > 0 else 0
                else:
                    proximidad_dca = 0
            
            precios_dca = {int(p.dca_level): p.entry_price for p in posiciones if p.dca_level > 0}

            return {
                'precio_actual': precio_actual,
                'precio_mark': self.exchange.obtener_precio_mark(symbol),
                'precio_inicial': posiciones[0].entry_price,
                'precio_entrada': avg_entry, # Breakeven
                'precios_dca': precios_dca,
                'lado': lado,
                'pnl': pnl,
                'pnl_pct': roe_pct, # Ahora pasamos ROE como el PNL% principal
                'capital_invertido': capital_real,
                'inversion_apalancada': total_qty * precio_actual,
                'nivel_dca': max(p.dca_level for p in posiciones),
                'proximidad_dca': max(0, proximidad_dca),
                'liquidation_price': float(pos_info.get('liquidation_price', 0)),
                'timestamp_apertura': posiciones[0].timestamp
            }
        except Exception as e:
            logger.error(f"❌ Error info posiciones: {e}")
            return {}

class ModoSalvavidas:
    def __init__(self, exchange: ExchangeWrapper, persistencia: Persistencia):
        self.exchange = exchange
        self.persistencia = persistencia
    async def monitorear(self, symbol: str, intervalo_sec: int = 60):
        while True:
            await asyncio.sleep(intervalo_sec)
