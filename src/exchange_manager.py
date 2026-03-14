"""
Gestor de Exchanges - Factory Pattern
=======================================
Manejo de conexiones a múltiples exchanges usando ccxt.
"""
import ccxt
import logging
import time
import math
from typing import Optional, Dict, Any, List
from datetime import datetime
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np

logger = logging.getLogger(__name__)


class ExchangeFactory:
    """
    Factory para crear instancias de exchanges.
    """
    
    _instances: Dict[str, 'ExchangeWrapper'] = {}
    
    @staticmethod
    def create(exchange_id: str, api_key: str = "", api_secret: str = "", 
               testnet: bool = False) -> 'ExchangeWrapper':
        """
        Crea una instancia de ExchangeWrapper.
        """
        cache_key = f"{exchange_id}_{testnet}"
        
        if cache_key in ExchangeFactory._instances:
            logger.info(f"♻️ Reutilizando instancia existente de {exchange_id}")
            return ExchangeFactory._instances[cache_key]
        
        logger.info(f"🔧 Creando nueva instancia de {exchange_id}")
        instance = ExchangeWrapper(exchange_id, api_key, api_secret, testnet)
        ExchangeFactory._instances[cache_key] = instance
        return instance
    
    @staticmethod
    def clear_instances() -> None:
        """Limpia todas las instancias cacheadas."""
        ExchangeFactory._instances.clear()
        logger.info("🗑️ Instancias de exchange cacheadas eliminadas")


class ExchangeWrapper:
    """
    Wrapper para operaciones con exchanges (ccxt 4.x - sync).
    """
    
    def __init__(self, exchange_id: str, api_key: str, api_secret: str, testnet: bool = False):
        self.exchange_id = exchange_id.lower()
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self._exchange: Optional[ccxt.Exchange] = None
        self.last_error: Optional[str] = None
        self._balance_cache: Dict[str, float] = {}
        self._last_balance_fetch_time: float = 0
        self._initialize_exchange()
    
    def _initialize_exchange(self) -> None:
        """Inicializa la instancia de ccxt."""
        try:
            import config as cfg
            
            exchange_class = getattr(ccxt, self.exchange_id)
            
            config = {
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            }
            
            if self.testnet:
                config['testnet'] = True
            
            config['apiKey'] = self.api_key
            config['secret'] = self.api_secret
            
            if self.api_key and self.api_secret:
                logger.info(f"🔑 API Key configurada: {self.api_key[:10]}...")
            else:
                logger.warning("⚠️ API Key o Secret vacíos!")
            
            # Silenciar advertencia de fetchOpenOrders sin símbolo
            config['options'] = config.get('options', {})
            config['options']['warnOnFetchOpenOrdersWithoutSymbol'] = False
            
            self._exchange = exchange_class(config)
            self._exchange.load_markets()
            logger.info(f"✅ Exchange inicializado y mercados cargados: {self.exchange_id}")
            
        except AttributeError:
            logger.error(f"❌ Exchange no soportado: {self.exchange_id}")
            raise ValueError(f"Exchange no soportado: {self.exchange_id}")
        except Exception as e:
            logger.error(f"❌ Error inicializando exchange: {e}")
            raise

    def cantidad_a_precision(self, symbol: str, cantidad: float) -> float:
        """Ajusta la cantidad a la precisión permitida por el exchange."""
        try:
            if not self._exchange.markets:
                self._exchange.load_markets()
            
            return float(self._exchange.amount_to_precision(symbol, cantidad))
        except Exception as e:
            logger.error(f"❌ Error ajustando precisión de cantidad: {e}")
            return cantidad
    
    def verificar_conexion(self) -> bool:
        """Verifica la conexión con el exchange."""
        try:
            self._exchange.fetch_time()
            logger.info(f"✅ Conexión verificada: {self.exchange_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error verificando conexión: {e}")
            return False
    
    def obtener_balance(self) -> Dict[str, float]:
        """Obtiene el balance de la cuenta con caché de 2 segundos y reintentos."""
        return self._obtener_balance(refresh=False)
    
    def obtener_balance_fresco(self) -> Dict[str, float]:
        """Obtiene el balance FORZANDO-refresco desde el exchange (sin caché)."""
        return self._obtener_balance(refresh=True)
    
    def _obtener_balance(self, refresh: bool = False) -> Dict[str, float]:
        """Obtiene el balance de la cuenta con caché de 2 segundos y reintentos."""
        try:
            ahora = time.time()
            if not refresh and ahora - self._last_balance_fetch_time < 2.0 and self._balance_cache:
                return self._balance_cache

            logger.info(f"🔍 Obtener balance - API Key: {self.api_key[:10] if self.api_key else 'EMPTY'}..., testnet: {self.testnet}")
            
            # Reintentos para errores temporales de Bybit
            max_intentos = 3
            for intento in range(max_intentos):
                try:
                    # En Bybit V5 (Unified Account), el balance suele estar bajo 'linear' para futuros USDT
                    if self.exchange_id == 'bybit':
                        balance = self._exchange.fetch_balance({'type': 'swap', 'category': 'linear'})
                    else:
                        balance = self._exchange.fetch_balance()
                    break
                except Exception as api_err:
                    error_str = str(api_err)
                    if '10016' in error_str and intento < max_intentos - 1:
                        wait_time = 1 + intento
                        logger.warning(f"⚠️ Bybit error 10016, reintento {intento+1}/{max_intentos} en {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    # Si falla con 'type' swap, intentar por defecto
                    if 'invalid' in error_str.lower() or 'type' in error_str.lower():
                        balance = self._exchange.fetch_balance()
                        break
                    raise
            
            # Extraer USDT con logging detallado
            usdt_data = balance.get('USDT', {})
            logger.debug(f"🔍 Datos crudos de USDT: {usdt_data}")
            
            total = free = used = 0
            if isinstance(usdt_data, dict):
                total = usdt_data.get('total', 0)
                free = usdt_data.get('free', 0)
                used = usdt_data.get('used', 0)
            elif isinstance(usdt_data, (int, float)):
                total = usdt_data
            
            # Fallback para Unified Account de Bybit si no se encontró USDT
            if total == 0 and self.exchange_id == 'bybit':
                try:
                    # En Bybit V5 unified, a veces viene en balance['info']['result']['list'][0]['totalEquity']
                    info = balance.get('info', {})
                    result = info.get('result', {})
                    if isinstance(result, dict) and 'list' in result:
                        assets = result['list'][0]
                        total = float(assets.get('totalEquity', 0))
                        free = float(assets.get('totalAvailableBalance', 0))
                        used = total - free
                        logger.info(f"💼 Balance detectado vía Bybit Unified: Total={total}, Free={free}")
                except:
                    pass

            # Último recurso: buscar cualquier cosa que parezca un total en el balance general
            if total == 0:
                total = balance.get('total', {}).get('USDT', 0)
                free = balance.get('free', {}).get('USDT', 0)
            
            logger.info(f"💰 Balance final: total={total}, free={free}, used={used}")
            
            self._balance_cache = {
                'total': float(total),
                'free': float(free),
                'used': float(used)
            }
            self._last_balance_fetch_time = ahora
            return self._balance_cache
        except Exception as e:
            logger.error(f"❌ Error obteniendo balance: {e}")
            return self._balance_cache if self._balance_cache else {'total': 0, 'free': 0, 'used': 0}
    
    def obtener_balance_total_usdt(self) -> float:
        """Obtiene el balance total en USDT (fresco, sin caché)."""
        balance = self.obtener_balance_fresco()
        return balance.get('total', 0)
    
    def obtener_balance_disponible_usdt(self) -> float:
        """Obtiene el balance disponible (free) en USDT (fresco, sin caché)."""
        balance = self.obtener_balance_fresco()
        return balance.get('free', 0)
    
    def calcular_posicion_maxima(self, symbol: str, leverage: int, precio: float) -> float:
        """
        Calcula la cantidad máxima de tokens que se pueden comprar basándose en:
        - Balance disponible
        - Leverage
        - Precio actual
        - Requisitos mínimos del exchange
        """
        try:
            if precio <= 0:
                logger.warning("⚠️ Precio inválido para calcular posición máxima")
                return 0.0
            
            info_symbolo = self.obtener_info_symbolo(symbol)
            min_notional = info_symbolo['min_notional']
            min_amount = info_symbolo['min_amount']
            
            balance = self.obtener_balance_disponible_usdt()
            balance_con_leverage = balance * leverage
            
            # Usar un margen de seguridad del 5% para evitar "Insufficient balance" por fees
            cantidad_maxima = (balance_con_leverage * 0.95) / precio
            
            if cantidad_maxima < min_amount:
                logger.warning(f"⚠️ Cantidad calculada ({cantidad_maxima}) menor al mínimo ({min_amount})")
                return 0.0
            
            cantidad_ajustada = self.cantidad_a_precision(symbol, cantidad_maxima)
            
            notional = cantidad_ajustada * precio
            if notional < min_notional:
                logger.warning(f"⚠️ Notional ({notional}) menor al mínimo ({min_notional})")
                cantidad_minima = min_notional / precio
                cantidad_minima = self.cantidad_a_precision(symbol, cantidad_minima)
                if cantidad_minima >= min_amount:
                    cantidad_ajustada = cantidad_minima
                else:
                    return 0.0
            
            logger.info(f"💰 Posición máxima: {cantidad_ajustada} tokens (balance: ${balance}, leverage: {leverage}x, precio: {precio})")
            return cantidad_ajustada
            
        except Exception as e:
            logger.error(f"❌ Error calculando posición máxima: {e}")
            return 0.0
    
    def obtener_info_symbolo(self, symbol: str) -> Dict[str, Any]:
        """Obtiene información de límites y requisitos mínimos de un símbolo."""
        try:
            if not self._exchange.markets:
                self._exchange.load_markets()
            
            mercado = self._exchange.markets.get(symbol, {})
            if not mercado:
                return {'min_amount': 0.001, 'min_notional': 5.0, 'precision_amount': 3}
            
            limits = mercado.get('limits', {})
            amount_limits = limits.get('amount', {})
            cost_limits = limits.get('cost', {})
            
            min_amount = amount_limits.get('min')
            max_amount = amount_limits.get('max')
            min_notional = cost_limits.get('min')
            
            precision = mercado.get('precision', {})
            precision_amount = precision.get('amount', 3)
            
            # Validar que no sean None antes de comparar
            final_min_amount = 0.001
            if min_amount is not None:
                final_min_amount = max(min_amount, 0.0001)
                
            final_min_notional = 5.0
            if min_notional is not None:
                final_min_notional = max(min_notional, 1.0)
            
            return {
                'min_amount': final_min_amount,
                'max_amount': max_amount,
                'min_notional': final_min_notional,
                'precision_amount': precision_amount
            }
        except Exception as e:
            logger.error(f"❌ Error obteniendo info símbolo: {e}")
            return {'min_amount': 0.001, 'min_notional': 5.0, 'precision_amount': 3}
    
    def validar_leverage(self, symbol: str, leverage: int, balance: Optional[float] = None) -> Dict[str, Any]:
        """
        Valida si el leverage seleccionado es viable con el balance disponible.
        Retorna: {
            'valido': bool,
            'leverage_minimo_necesario': int,
            'leverage_maximo_permitido': int,
            'balance_minimo_necesario': float,
            'mensaje': str,
            'sugerencia': str
        }
        """
        try:
            info_symbolo = self.obtener_info_symbolo(symbol)
            min_notional = info_symbolo['min_notional']
            
            if balance is None:
                balance = self.obtener_balance_disponible_usdt()
            
            leverage = int(leverage)
            if leverage < 1:
                leverage = 1
            
            leverage_max_permitido = 100
            try:
                tiers = self._exchange.fetch_leverage_tiers(symbol)
                if tiers and 'tiers' in tiers:
                    leverage_max_permitido = max([t.get('maxLeverage', 100) for t in tiers['tiers']])
            except:
                pass
            
            balance_actual_apalancado = balance * leverage
            es_suficiente = balance_actual_apalancado >= min_notional
            
            if es_suficiente:
                return {
                    'valido': True,
                    'leverage_minimo_necesario': 1,
                    'leverage_max_permitido': leverage_max_permitido,
                    'balance_minimo_necesario': min_notional / leverage,
                    'mensaje': f'✅ Leverage {leverage}x válido con balance ${balance:.2f}',
                    'sugerencia': ''
                }
            
            leverage_min_necesario = int(math.ceil(min_notional / balance)) if balance > 0 else min_notional
            leverage_min_necesario = max(1, leverage_min_necesario)
            
            if leverage_min_necesario > leverage_max_permitido:
                return {
                    'valido': False,
                    'leverage_minimo_necesario': leverage_min_necesario,
                    'leverage_max_permitido': leverage_max_permitido,
                    'balance_minimo_necesario': min_notional / leverage,
                    'mensaje': f'⚠️ Balance insuficiente para {leverage}x',
                    'sugerencia': f'❌ Necesitas al menos ${min_notional:.2f} USDT para operar. Aumenta tu balance o usa leverage ≥{leverage_min_necesario}x'
                }
            
            return {
                'valido': False,
                'leverage_minimo_necesario': leverage_min_necesario,
                'leverage_max_permitido': leverage_max_permitido,
                'balance_minimo_necesario': min_notional / leverage,
                'mensaje': f'⚠️ Balance insuficiente para {leverage}x',
                'sugerencia': f'💡 Con ${balance:.2f} USDT, usa al menos {leverage_min_necesario}x de leverage para cumplir el mínimo de ${min_notional:.2f} USDT'
            }
        except Exception as e:
            logger.error(f"❌ Error validando leverage: {e}")
            return {
                'valido': True,
                'leverage_minimo_necesario': 1,
                'leverage_max_permitido': 100,
                'balance_minimo_necesario': 5.0,
                'mensaje': '✅ Leverage válido',
                'sugerencia': ''
            }
    
    def _normalizar_symbol(self, symbol: str) -> str:
        """Normaliza el símbolo para CCXT/Bybit."""
        # Por defecto CCXT usa formato como SOL/USDT
        # Bybit USDT perpetual usa SOL/USDT:USDT
        if self.exchange_id == 'bybit':
            if ':' not in symbol:
                return f"{symbol}:USDT"
        return symbol.replace(':USDT', '') if self.exchange_id != 'bybit' else symbol

    def obtener_precio_actual(self, symbol: str) -> float:
        """Obtiene el precio actual (Last Price) de forma ultra-rápida."""
        symbol_original = symbol
        try:
            # Asegurar que el mercado esté cargado
            if not self._exchange.markets:
                self._exchange.load_markets()
            
            # Normalizar símbolo
            symbol_buscar = self._normalizar_symbol(symbol)
            
            ticker = self._exchange.fetch_ticker(symbol_buscar)
            precio = float(ticker.get('last', 0))
            if precio > 0:
                logger.info(f"💹 Precio {symbol_buscar}: {precio}")
            return precio
        except Exception as e:
            logger.error(f"❌ Error obteniendo precio de {symbol_original}: {e}")
            return 0.0
    
    def obtener_precio_mark(self, symbol: str) -> float:
        """Obtiene el precio mark (para liquidaciones)."""
        try:
            symbol_buscar = self._normalizar_symbol(symbol)
            ticker = self._exchange.fetch_ticker(symbol_buscar)
            return ticker.get('markPrice', ticker.get('last', 0))
        except Exception as e:
            logger.error(f"❌ Error obteniendo precio mark: {e}")
            return 0
    
    def obtener_precios(self, symbol: str) -> Dict[str, float]:
        """Obtiene varios precios de un símbolo."""
        try:
            symbol_buscar = self._normalizar_symbol(symbol)
            ticker = self._exchange.fetch_ticker(symbol_buscar)
            return {
                'last': ticker.get('last', 0),
                'mark': ticker.get('markPrice', 0),
                'index': ticker.get('indexPrice', 0),
                'bid': ticker.get('bid', 0),
                'ask': ticker.get('ask', 0)
            }
        except Exception as e:
            logger.error(f"❌ Error obteniendo precios: {e}")
            return {'last': 0, 'mark': 0, 'index': 0, 'bid': 0, 'ask': 0}
    
    def obtener_ohlcv(self, symbol: str, timeframe: str = '15m', 
                      limite: int = 100) -> pd.DataFrame:
        """Obtiene datos OHLCV en formato DataFrame."""
        try:
            # Normalizar símbolo
            symbol_buscar = self._normalizar_symbol(symbol)
            
            ohlcv = self._exchange.fetch_ohlcv(symbol_buscar, timeframe, limit=limite)
            
            if not ohlcv:
                logger.warning(f"⚠️ Sin datos OHLCV para {symbol_buscar}")
                return pd.DataFrame()
            
            df = pd.DataFrame(ohlcv, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
        except Exception as e:
            logger.error(f"❌ Error obteniendo OHLCV de {symbol}: {e}")
            return pd.DataFrame()
    
    def configurar_apalancamiento(self, symbol: str, leverage: int) -> bool:
        """Configura el apalancamiento y el modo de margen."""
        try:
            symbol_buscar = self._normalizar_symbol(symbol)
            leverage_int = int(float(leverage))
            
            # Forzar modo de margen cruzado (CROSS)
            try:
                self._exchange.set_margin_mode('CROSS', symbol_buscar)
                logger.info(f"✅ Modo de margen CROSS configurado en {symbol_buscar}")
            except Exception as e:
                logger.debug(f"ℹ️ Modo margen: {e}")

            # En Bybit a veces es necesario pasar 'buy' o 'sell' si se está en modo Hedge
            # pero en modo One-Way (por defecto) esto debería funcionar:
            try:
                self._exchange.set_leverage(leverage_int, symbol_buscar)
                logger.info(f"✅ Apalancamiento configurado: {leverage_int}x en {symbol_buscar}")
            except Exception as e:
                if self.exchange_id == 'bybit':
                    # Intento alternativo para Bybit si falla el estándar
                    params = {'category': 'linear'}
                    self._exchange.set_leverage(leverage_int, symbol_buscar, params)
                    logger.info(f"✅ Apalancamiento Bybit configurado con params: {leverage_int}x en {symbol_buscar}")
                elif "leverage not modified" in str(e).lower():
                    logger.info(f"ℹ️ El apalancamiento ya estaba en {leverage_int}x")
                else:
                    raise e
            return True
        except Exception as e:
            if "leverage not modified" in str(e).lower():
                logger.info(f"ℹ️ El apalancamiento ya estaba configurado")
            else:
                logger.error(f"❌ Error configurando apalancamiento/margen: {e}")
            return False

    def obtener_posicion(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtiene información de la posición actual de forma ultra-robusta."""
        try:
            # Reintentos para errores temporales de Bybit
            max_intentos = 3
            for intento in range(max_intentos):
                try:
                    positions = self._exchange.fetch_positions()
                    break
                except Exception as api_err:
                    error_str = str(api_err)
                    if '10016' in error_str and intento < max_intentos - 1:
                        wait_time = 1 + intento
                        logger.warning(f"⚠️ Bybit error 10016 en posiciones, reintento {intento+1}/{max_intentos} en {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    raise
            
            for pos in positions:
                # CCXT 4.x usa 'contracts' para el tamaño, pero 'size' o 'positionAmt' pueden estar en 'info'
                contracts = float(pos.get('contracts') or pos.get('size') or pos.get('info', {}).get('positionAmt', 0))
                
                # FILTRO ANTI-DUST: Ignorar posiciones infinitesimales
                if abs(contracts) > 0.00001:
                    pos_symbol = pos.get('symbol')
                    # Normalizar símbolos para comparación (quitar /, :, USDT, etc)
                    norm_pos = pos_symbol.replace('/', '').replace(':', '').replace('USDT', '').split('_')[0].upper()
                    norm_target = symbol.replace('/', '').replace(':', '').replace('USDT', '').split('_')[0].upper()
                    
                    if pos_symbol == symbol or norm_pos == norm_target:
                        # Extraer datos con nombres de campos de CCXT 4.x
                        liq_price = float(pos.get('liquidationPrice') or pos.get('liqPrice') or pos.get('info', {}).get('liquidationPrice') or 0)
                        
                        # Fallback de liquidación para Binance (v3 API)
                        if liq_price == 0 and self.exchange_id == 'binance':
                            try:
                                clean_symbol = pos_symbol.replace('/', '').split(':')[0]
                                risk_info = self._exchange.fapiPrivateGetPositionRisk({'symbol': clean_symbol})
                                if risk_info:
                                    # Buscar el símbolo exacto en la lista de riesgos
                                    for r in risk_info:
                                        if r.get('symbol') == clean_symbol:
                                            liq_price = float(r.get('liquidationPrice', 0))
                                            break
                            except Exception as e:
                                logger.debug(f"ℹ️ Fallback liq falló: {e}")

                        return {
                            'size': contracts,
                            'side': 'long' if contracts > 0 else 'short',
                            'entry_price': float(pos.get('entryPrice') or pos.get('entry_price') or pos.get('info', {}).get('entryPrice', 0)),
                            'unrealized_pnl': float(pos.get('unrealizedPnl') or pos.get('unrealized_pnl') or pos.get('info', {}).get('unrealizedProfit', 0)),
                            'leverage': int(pos.get('leverage') or pos.get('info', {}).get('leverage', 1)),
                            'liquidation_price': liq_price,
                            'margin': float(pos.get('initialMargin') or pos.get('info', {}).get('initialMargin', 0))
                        }
            return None
        except Exception as e:
            logger.error(f"❌ Error obteniendo posición: {e}")
            return None
    
    def crear_orden(self, symbol: str, lado: str, cantidad: float,
                    precio: Optional[float] = None, 
                    tipo_orden: str = 'market',
                    reduce_only: bool = False) -> Optional[Dict[str, Any]]:
        """Crea una orden de trading."""
        try:
            params = {'reduceOnly': reduce_only} if reduce_only else {}
            
            # Ajustar cantidad a precisión del exchange por seguridad
            cantidad_final = self.cantidad_a_precision(symbol, cantidad)
            
            orden = self._exchange.create_order(
                symbol=symbol,
                type=tipo_orden,
                side=lado,
                amount=cantidad_final,
                price=precio,
                params=params
            )
            
            logger.info(f"✅ Orden creada: {lado} {cantidad_final} {symbol} @ {precio or 'market'}")
            return orden
            
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"❌ Error creando orden: {e}")
            return None
    
    def abrir_posicion(self, symbol: str, lado: str, cantidad: float,
                       leverage: int = 20) -> Optional[Dict[str, Any]]:
        """Abre una posición larga o corta."""
        try:
            logger.info(f"🔔 ABRIENDO POSICIÓN: {lado} {cantidad} {symbol} con {leverage}x")
            
            # Normalizar símbolo
            symbol_norm = self._normalizar_symbol(symbol)
            logger.info(f"🔔 Símbolo normalizado: {symbol_norm}")
            
            self.configurar_apalancamiento(symbol_norm, leverage)
            
            lado_orden = 'buy' if lado == 'long' else 'sell'
            
            logger.info(f"🔔 Creando orden: {lado_orden} {cantidad} {symbol_norm}")
            
            orden = self.crear_orden(
                symbol=symbol_norm,
                lado=lado_orden,
                cantidad=cantidad,
                tipo_orden='market'
            )
            
            if orden:
                logger.info(f"📈 Posición abierta: {lado.upper()} {cantidad} {symbol}")
            
            return orden
            
        except Exception as e:
            logger.error(f"❌ Error abriendo posición: {e}")
            import traceback
            logger.error(f"❌ Trace: {traceback.format_exc()}")
            return None
    
    def cerrar_posicion(self, symbol: str, cantidad: Optional[float] = None) -> bool:
        """Cierra la posición actual de forma radical e infalible (Bybit & Binance)."""
        try:
            # 1. Normalizar símbolo
            symbol_buscar = self._normalizar_symbol(symbol)
            logger.info(f"🔒 Solicitado cierre de posición en {symbol_buscar}...")

            # 2. Limpieza de órdenes previas (Evitar bloqueos)
            try:
                self._exchange.cancel_all_orders(symbol_buscar)
                logger.info(f"🧹 Órdenes canceladas para {symbol_buscar}")
            except Exception as e:
                logger.debug(f"ℹ️ Info limpieza órdenes: {e}")

            # 3. Obtener la posición exacta
            pos = self.obtener_posicion(symbol_buscar)
            
            if not pos or abs(pos.get('size', 0)) < 0.00001:
                logger.warning(f"⚠️ No hay posición activa en {symbol_buscar} para cerrar.")
                return True 
            
            cantidad_real = abs(pos['size'])
            cantidad_a_cerrar = cantidad_real if cantidad is None else min(cantidad, cantidad_real)
            
            # Ajustar a precisión
            cantidad_a_cerrar = self.cantidad_a_precision(symbol_buscar, cantidad_a_cerrar)
            
            # Determinar lado de la orden (contrario a la posición)
            # Usamos el campo 'side' que ya viene normalizado como 'long' o 'short'
            lado_actual = pos.get('side', 'long').lower()
            lado_orden = 'sell' if lado_actual == 'long' else 'buy'
            
            params = {'reduceOnly': True}
            if self.exchange_id == 'bybit':
                params['category'] = 'linear'
                params['positionIdx'] = 0 # 0 para modo One-way (Standard)

            logger.info(f"🔒 Cerrando {symbol_buscar} ({lado_actual.upper()}): {lado_orden.upper()} {cantidad_a_cerrar} (Market)")
            
            try:
                orden = self._exchange.create_order(
                    symbol=symbol_buscar,
                    type='market',
                    side=lado_orden,
                    amount=cantidad_a_cerrar,
                    params=params
                )
            except Exception as e_order:
                error_str = str(e_order)
                debe_reintentar = '110017' in error_str or 'reduce-only' in error_str.lower() or 'same side' in error_str.lower()
                
                if debe_reintentar:
                    logger.warning("⚠️ Cierre con reduce-only falló. Intentando cierre radical sin restricción...")
                    params.pop('reduceOnly', None)
                    try:
                        orden = self._exchange.create_order(
                            symbol=symbol_buscar,
                            type='market',
                            side=lado_orden,
                            amount=cantidad_a_cerrar,
                            params=params
                        )
                    except Exception as e_retry:
                        logger.error(f"❌ Fallback también falló: {e_retry}")
                        raise e_retry
                else:
                    raise e_order
            
            if orden:
                logger.info(f"✅ Posición de {symbol_buscar} CERRADA con éxito.")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error crítico cerrando {symbol}: {e}")
            return False
    
    def cerrar_todas_posiciones(self) -> bool:
        """Cierra todas las posiciones abiertas de forma radical (Pánico)."""
        try:
            # 1. Obtener posiciones actuales (específico para Bybit V5)
            if self.exchange_id == 'bybit':
                positions = self._exchange.fetch_positions(params={'category': 'linear'})
            else:
                positions = self._exchange.fetch_positions()
                
            exito_total = True
            
            for pos in positions:
                contracts = float(pos.get('contracts') or pos.get('size') or pos.get('info', {}).get('positionAmt', 0))
                if abs(contracts) > 0.00001:
                    symbol = pos.get('symbol')
                    logger.info(f"🚨 PÁNICO: Detectada posición en {symbol} ({contracts}). Cerrando de forma radical...")
                    
                    # REUTILIZAR la lógica infalible de cerrar_posicion
                    if not self.cerrar_posicion(symbol):
                        exito_total = False
            
            if exito_total:
                logger.info("🔒 Todas las posiciones cerradas exitosamente en el exchange.")
            
            return exito_total
            
        except Exception as e:
            logger.error(f"❌ Error crítico en cierre de pánico: {e}")
            return False
    
    def obtener_tasas_fondeo(self, symbol: str) -> float:
        """Obtiene la tasa de fondeo actual."""
        try:
            funding = self._exchange.fetch_funding_rate(symbol)
            return funding.get('fundingRate', 0)
        except Exception as e:
            logger.error(f"❌ Error obteniendo tasa de fondeo: {e}")
            return 0
    
    def transferir_a_futuros(self, cantidad: float) -> bool:
        """Transfiere saldo de spot a futuros."""
        try:
            if self.exchange_id not in ['binance']:
                logger.warning(f"⚠️ Transferencia no soportada en {self.exchange_id}")
                return False
            
            result = self._exchange.transfer(
                currency='USDT',
                amount=cantidad,
                fromWallet='spot',
                toWallet='future'
            )
            
            logger.info(f"💰 Transferido {cantidad} USDT a futuros")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en transferencia: {e}")
            return False
    
    def obtener_ordenes_abiertas(self, symbol: str) -> List[Dict[str, Any]]:
        """Obtiene las órdenes abiertas para un símbolo."""
        try:
            ordenes = self._exchange.fetch_open_orders(symbol)
            return ordenes
        except Exception as e:
            logger.error(f"❌ Error obteniendo órdenes: {e}")
            return []
    
    def cancelar_orden(self, orden_id: str, symbol: str) -> bool:
        """Cancela una orden."""
        try:
            self._exchange.cancel_order(orden_id, symbol)
            logger.info(f"❌ Orden cancelada: {orden_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error cancelando orden: {e}")
            return False
    
    def obtener_orden(self, orden_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Obtiene el estado de una orden."""
        try:
            orden = self._exchange.fetch_order(orden_id, symbol)
            return orden
        except Exception as e:
            logger.error(f"❌ Error obteniendo orden: {e}")
            return None
    
    def cerrar(self) -> None:
        """Cierra la conexión del exchange."""
        try:
            if self._exchange:
                logger.info(f"🔒 Conexión cerrada: {self.exchange_id}")
        except Exception as e:
            logger.error(f"❌ Error cerrando exchange: {e}")
