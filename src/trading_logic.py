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
            import config as cfg
            logger.info(f"📊 Analizando {symbol} en {timeframe}...")
            df = self.exchange.obtener_ohlcv(symbol, timeframe, limite=100)
            if df.empty:
                logger.warning(f"⚠️ Sin datos OHLCV para {symbol}")
                return ResultadoAnalisis(TradeDirection.NEUTRAL, "sin datos", 0, 0)
            
            precio_actual = df['close'].iloc[-1]
            logger.info(f"📈 Precio actual: {precio_actual}")
            
            ema_fast_len = getattr(cfg, 'EMA_FAST', 9)
            ema_slow_len = getattr(cfg, 'EMA_SLOW', 21)
            
            df['EMA_FAST'] = ta.ema(df['close'], length=ema_fast_len)
            df['EMA_SLOW'] = ta.ema(df['close'], length=ema_slow_len)
            
            ema_fast = df['EMA_FAST'].iloc[-1]
            ema_slow = df['EMA_SLOW'].iloc[-1]
            
            logger.info(f"📉 EMA-{ema_fast_len}: {ema_fast:.4f}, EMA-{ema_slow_len}: {ema_slow:.4f}")
            
            if ema_fast > ema_slow:
                logger.info(f"✅ Señal: LONG (alcista)")
                return ResultadoAnalisis(TradeDirection.LONG, "alcista", 70, precio_actual)
            elif ema_fast < ema_slow:
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
            logger.info(f"🔔 Calculando tamaño: balance=${balance}, precio=${precio}, DCA={nivel_dca}")
            
            # 1. Obtener límites del exchange
            info = self.exchange.obtener_info_symbolo(symbol)
            min_amount = info.get('min_amount', 0.001)
            min_notional = info.get('min_notional', 5.0)
            
            # 2. Calcular volumen teórico según configuración
            # Usamos el % de balance configurado multiplicado por el apalancamiento
            volumen_usdt_teorico = (balance * self.config.initial_volume_pct) * self.config.leverage
            # Aplicar multiplicador de DCA si corresponde
            volumen_usdt_actual = volumen_usdt_teorico * (self.config.volume_multiplier ** nivel_dca)
            
            # 3. Asegurar el MÍNIMO NOTIONAL (ej. $5 o $10 según el exchange)
            volumen_final_usdt = max(volumen_usdt_actual, min_notional)
            
            # 4. Convertir a cantidad de tokens
            cantidad_teorica = volumen_final_usdt / precio
            
            # 5. Asegurar el MÍNIMO de cantidad (ej. 0.001 BTC)
            cantidad_ajustada = max(cantidad_teorica, min_amount)
            
            # 6. Validar contra la posición máxima permitida por el balance real
            cantidad_maxima = self.exchange.calcular_posicion_maxima(symbol, self.config.leverage, precio)
            
            cantidad_final = min(cantidad_ajustada, cantidad_maxima)
            
            # 7. Verificación final de viabilidad
            if cantidad_final < min_amount:
                logger.warning(f"⚠️ Operación inviable: Cantidad final {cantidad_final} < Mínimo {min_amount}")
                return 0.0
            
            notional_final = cantidad_final * precio
            if notional_final < min_notional:
                logger.warning(f"⚠️ Operación inviable: Notional ${notional_final:.2f} < Mínimo ${min_notional:.2f}")
                return 0.0

            res = self.exchange.cantidad_a_precision(symbol, cantidad_final)
            logger.info(f"✅ Tamaño final calculado: {res} tokens (${notional_final:.2f})")
            return res
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
            
            # USO DE PNL VISUAL (Relativo al Capital Total del usuario)
            pnl_visual = info.get('pnl_pct', 0) / 100
            tp_objetivo = self.config.take_profit_pct
            
            if pnl_visual >= tp_objetivo and not self._tp_activado:
                self._tp_activado = True
                self._max_pnl_visual = pnl_visual
                self._floor_pnl_visual = tp_objetivo
                logger.info(f"🎯 TP ACTIVADO: Ganancia Real {pnl_visual*100:.2f}% de tu capital. Objetivo {tp_objetivo*100:.2f}%")
            
            if self.config.tp_inteligente and self._tp_activado:
                distancia_visual = getattr(self.config, 'trailing_distancia', 0.002) 
                
                if pnl_visual > self._max_pnl_visual:
                    self._max_pnl_visual = pnl_visual
                    nuevo_piso = pnl_visual - distancia_visual
                    if nuevo_piso > self._floor_pnl_visual:
                        self._floor_pnl_visual = nuevo_piso
                        logger.info(f"🚀 SUBIENDO: Beneficio {self._max_pnl_visual*100:.2f}%, Piso Protegido {self._floor_pnl_visual*100:.2f}%")
                
                if pnl_visual < self._floor_pnl_visual:
                    logger.info(f"🛑 CIERRE: El beneficio cayó a {pnl_visual*100:.2f}% (Bajo el piso de {self._floor_pnl_visual*100:.2f}%)")
                    return True, info.get('pnl', 0)
                
                return False, info.get('pnl', 0)
            
            return (pnl_visual >= tp_objetivo), info.get('pnl', 0)
        except Exception as e:
            logger.error(f"❌ Error verificando TP: {e}")
            return False, 0

    async def verificar_stop_loss(self, posiciones: List[Posicion]) -> Tuple[bool, float]:
        if not posiciones or self.config.stop_loss_pct <= 0: return False, 0
        info = await self.obtener_info_posiciones(posiciones)
        
        # SL basado en el Capital Total
        pnl_visual = info.get('pnl_pct', 0) / 100
        
        if pnl_visual <= -self.config.stop_loss_pct:
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

            # 3. MÉTRICAS DE CAPITAL REALES (VISIBILIDAD PARA EL USUARIO)
            pnl = float(pos_info.get('unrealized_pnl', 0))
            margin = float(pos_info.get('margin', 0))
            
            # ROE Real (como el exchange): Beneficio / Margen * 100
            roe_real_pct = (pnl / margin * 100) if margin > 0 else 0
            
            # PNL sobre Capital Total (Cartera)
            balance_fresco = self.exchange.obtener_balance_fresco().get('total', 0)
            pnl_visual_pct = (pnl / balance_fresco * 100) if balance_fresco > 0 else 0
            
            # 4. PROXIMIDAD DCA - Basada en el Step Dinámico desde el AVG
            mult_step = getattr(self.config, 'step_multiplier', 1.1)
            # Obtenemos el nivel actual de la lista de posiciones
            nivel_actual = max(p.dca_level for p in posiciones)
            
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
                'pnl_pct': pnl_visual_pct, # PNL real sobre capital total
                'roe_real_pct': roe_real_pct, # ROE real sobre margen
                'posiciones': len(posiciones),
                'capital_invertido': margin,
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
