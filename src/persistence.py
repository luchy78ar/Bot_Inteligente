"""
Módulo de Persistencia - SQLite
================================
Manejo de base de datos local para guardar estado del bot.
"""
import sqlite3
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import aiosqlite

from src.models import Posicion, CicloTrading, ConfiguracionTrading, OrderSide, OrderStatus, TradeDirection

logger = logging.getLogger(__name__)


class Persistencia:
    """
    Manejo de base de datos SQLite para persistencia del estado.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
    
    async def conectar(self) -> None:
        """Inicializa la conexión a la base de datos."""
        try:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._crear_tablas()
            logger.info(f"✅ Base de datos conectada: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Error conectando a SQLite: {e}")
            raise
    
    async def cerrar(self) -> None:
        """Cierra la conexión a la base de datos."""
        if self._db:
            await self._db.close()
            logger.info("🔒 Conexión a SQLite cerrada")
    
    async def _crear_tablas(self) -> None:
        """Crea las tablas necesarias si no existen."""
        query = """
        -- Tabla de posiciones abiertas
        CREATE TABLE IF NOT EXISTS posiciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            quantity REAL NOT NULL,
            leverage INTEGER NOT NULL,
            dca_level INTEGER DEFAULT 0,
            timestamp REAL NOT NULL,
            status TEXT DEFAULT 'filled'
        );
        
        -- Tabla de ciclos de trading
        CREATE TABLE IF NOT EXISTS ciclos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ciclo_id INTEGER UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            direccion_inicial TEXT NOT NULL,
            capital_inicial REAL NOT NULL,
            capital_final REAL DEFAULT 0,
            profit REAL DEFAULT 0,
            profit_pct REAL DEFAULT 0,
            max_dca_alcanzado INTEGER DEFAULT 0,
            timestamp_inicio REAL NOT NULL,
            timestamp_fin REAL DEFAULT 0,
            status TEXT DEFAULT 'activo'
        );
        
        -- Tabla de configuración
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );
        
        -- Tabla de historial de operaciones
        CREATE TABLE IF NOT EXISTS historial_operaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posicion_id TEXT NOT NULL,
            tipo TEXT NOT NULL,  -- 'open', 'dca', 'close', 'sl'
            precio REAL NOT NULL,
            cantidad REAL NOT NULL,
            precio_promedio REAL NOT NULL,
            pnl REAL DEFAULT 0,
            timestamp REAL NOT NULL,
            detalles TEXT
        );
        
        -- Tabla de balance histórico
        CREATE TABLE IF NOT EXISTS balance_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance_total REAL NOT NULL,
            balance_disponible REAL NOT NULL,
            timestamp REAL NOT NULL
        );
        
        -- Tabla de perfiles de configuración
        CREATE TABLE IF NOT EXISTS perfiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            config_json TEXT NOT NULL,
            es_default INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        
        -- Tabla de estado del bot
        CREATE TABLE IF NOT EXISTS estado_bot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            running INTEGER DEFAULT 0,
            direccion_actual TEXT DEFAULT 'neutral',
            pnl_realizado REAL DEFAULT 0,
            ciclos_completados INTEGER DEFAULT 0,
            ultimo_update REAL,
            perfil_actual TEXT DEFAULT 'default',
            testnet INTEGER DEFAULT 1,
            symbol TEXT DEFAULT 'BTC/USDT:USDT'
        );
        
        -- Insertar estado inicial si no existe
        INSERT OR IGNORE INTO estado_bot (id, running, direccion_actual, perfil_actual, testnet, symbol) VALUES (1, 0, 'neutral', 'default', 1, 'BTC/USDT:USDT');
        """
        
        await self._db.executescript(query)
        await self._db.commit()
        
        # Agregar columnas si no existen (para bases de datos antiguas)
        try:
            async with self._db.execute("PRAGMA table_info(estado_bot)") as cursor:
                columns = [row['name'] for row in await cursor.fetchall()]
                if 'testnet' not in columns:
                    await self._db.execute("ALTER TABLE estado_bot ADD COLUMN testnet INTEGER DEFAULT 1")
                if 'symbol' not in columns:
                    await self._db.execute("ALTER TABLE estado_bot ADD COLUMN symbol TEXT DEFAULT 'BTC/USDT:USDT'")
            await self._db.commit()
            logger.info("✅ Columnas adicionales verificadas/agregadas")
        except Exception as e:
            logger.warning(f"⚠️ Nota: Error verificando columnas extras (posiblemente ya existen): {e}")
            
        logger.info("📊 Tablas de SQLite creadas/verificadas")
    
    # =====================
    # OPERACIONES DE POSICIONES
    # =====================
    
    async def guardar_posicion(self, posicion: Posicion) -> None:
        """Guarda una nueva posición en la base de datos."""
        try:
            query = """
            INSERT OR REPLACE INTO posiciones 
            (order_id, symbol, side, entry_price, quantity, leverage, dca_level, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            await self._db.execute(query, (
                posicion.order_id,
                posicion.symbol,
                posicion.side.value,
                posicion.entry_price,
                posicion.quantity,
                posicion.leverage,
                posicion.dca_level,
                posicion.timestamp,
                posicion.status.value
            ))
            await self._db.commit()
            logger.debug(f"💾 Posición guardada: {posicion.order_id}")
        except Exception as e:
            logger.error(f"❌ Error guardando posición: {e}")
            raise
    
    async def obtener_posiciones_abiertas(self) -> List[Posicion]:
        """Obtiene todas las posiciones abiertas."""
        try:
            query = "SELECT * FROM posiciones WHERE status = 'filled'"
            async with self._db.execute(query) as cursor:
                rows = await cursor.fetchall()
                posiciones = []
                for row in rows:
                    posiciones.append(Posicion(
                        order_id=row['order_id'],
                        symbol=row['symbol'],
                        side=OrderSide(row['side']),
                        entry_price=row['entry_price'],
                        quantity=row['quantity'],
                        leverage=row['leverage'],
                        dca_level=row['dca_level'],
                        timestamp=row['timestamp'],
                        status=OrderStatus(row['status'])
                    ))
                return posiciones
        except Exception as e:
            logger.error(f"❌ Error obteniendo posiciones: {e}")
            return []
    
    async def actualizar_posicion(self, order_id: str, **kwargs) -> None:
        """Actualiza campos de una posición existente."""
        try:
            campos = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            query = f"UPDATE posiciones SET {campos} WHERE order_id = ?"
            await self._db.execute(query, list(kwargs.values()) + [order_id])
            await self._db.commit()
            logger.debug(f"✏️ Posición actualizada: {order_id}")
        except Exception as e:
            logger.error(f"❌ Error actualizando posición: {e}")
            raise
    
    async def eliminar_posicion(self, order_id: str) -> None:
        """Elimina una posición de la base de datos."""
        try:
            await self._db.execute("DELETE FROM posiciones WHERE order_id = ?", (order_id,))
            await self._db.commit()
            logger.debug(f"🗑️ Posición eliminada: {order_id}")
        except Exception as e:
            logger.error(f"❌ Error eliminando posición: {e}")
            raise
    
    async def limpiar_posiciones(self) -> None:
        """Elimina todas las posiciones (para reset completo)."""
        try:
            await self._db.execute("DELETE FROM posiciones")
            await self._db.commit()
            logger.info("🗑️ Todas las posiciones eliminadas")
        except Exception as e:
            logger.error(f"❌ Error limpiando posiciones: {e}")
            raise
    
    # =====================
    # OPERACIONES DE CICLOS
    # =====================
    
    async def guardar_ciclo(self, ciclo: CicloTrading) -> None:
        """Guarda un nuevo ciclo de trading."""
        try:
            query = """
            INSERT OR REPLACE INTO ciclos 
            (ciclo_id, symbol, direccion_inicial, capital_inicial, capital_final, 
             profit, profit_pct, max_dca_alcanzado, timestamp_inicio, timestamp_fin, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            await self._db.execute(query, (
                ciclo.ciclo_id,
                ciclo.symbol,
                ciclo.direccion_inicial.value,
                ciclo.capital_inicial,
                ciclo.capital_final,
                ciclo.profit,
                ciclo.profit_pct,
                ciclo.max_dca_alcanzado,
                ciclo.timestamp_inicio,
                ciclo.timestamp_fin,
                ciclo.status
            ))
            await self._db.commit()
            logger.debug(f"💾 Ciclo guardado: #{ciclo.ciclo_id}")
        except Exception as e:
            logger.error(f"❌ Error guardando ciclo: {e}")
            raise
    
    async def obtener_ciclo_activo(self) -> Optional[CicloTrading]:
        """Obtiene el ciclo activo actual."""
        try:
            query = "SELECT * FROM ciclos WHERE status = 'activo' ORDER BY ciclo_id DESC LIMIT 1"
            async with self._db.execute(query) as cursor:
                row = await cursor.fetchone()
                if row:
                    return CicloTrading(
                        ciclo_id=row['ciclo_id'],
                        symbol=row['symbol'],
                        direccion_inicial=TradeDirection(row['direccion_inicial']),
                        capital_inicial=row['capital_inicial'],
                        capital_final=row['capital_final'],
                        profit=row['profit'],
                        profit_pct=row['profit_pct'],
                        max_dca_alcanzado=row['max_dca_alcanzado'],
                        timestamp_inicio=row['timestamp_inicio'],
                        timestamp_fin=row['timestamp_fin'],
                        status=row['status']
                    )
                return None
        except Exception as e:
            logger.error(f"❌ Error obteniendo ciclo activo: {e}")
            return None
    
    async def obtener_ultimo_ciclo_id(self) -> int:
        """Obtiene el ID del último ciclo."""
        try:
            query = "SELECT MAX(ciclo_id) as max_id FROM ciclos"
            async with self._db.execute(query) as cursor:
                row = await cursor.fetchone()
                return row['max_id'] or 0
        except Exception as e:
            logger.error(f"❌ Error obteniendo último ID: {e}")
            return 0
    
    async def cerrar_ciclo(self, ciclo_id: int, capital_final: float, profit: float) -> None:
        """Marca un ciclo como completado."""
        try:
            query = """
            UPDATE ciclos 
            SET status = 'completado', 
                capital_final = ?, 
                profit = ?, 
                profit_pct = ?,
                timestamp_fin = ?
            WHERE ciclo_id = ?
            """
            profit_pct = (profit / capital_final * 100) if capital_final > 0 else 0
            await self._db.execute(query, (
                capital_final, 
                profit, 
                profit_pct,
                datetime.now().timestamp(),
                ciclo_id
            ))
            await self._db.commit()
            logger.info(f"🏁 Ciclo #{ciclo_id} completado: Profit ${profit:.2f} ({profit_pct:.2f}%)")
        except Exception as e:
            logger.error(f"❌ Error cerrando ciclo: {e}")
            raise
    
    # =====================
    # CONFIGURACIÓN
    # =====================
    
    async def guardar_config(self, clave: str, valor: Any) -> None:
        """Guarda una configuración."""
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                (clave, json.dumps(valor))
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"❌ Error guardando config: {e}")
            raise
    
    async def obtener_config(self, clave: str, default: Any = None) -> Any:
        """Obtiene una configuración."""
        try:
            async with self._db.execute(
                "SELECT valor FROM configuracion WHERE clave = ?", (clave,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row['valor'])
                return default
        except Exception as e:
            logger.error(f"❌ Error obteniendo config: {e}")
            return default
    
    # =====================
    # ESTADO DEL BOT
    # =====================
    
    async def resetear_estadisticas(self) -> bool:
        """Reinicia el PNL realizado y los ciclos completados a cero."""
        try:
            query = "UPDATE estado_bot SET pnl_realizado = 0, ciclos_completados = 0 WHERE id = 1"
            await self._db.execute(query)
            await self._db.commit()
            logger.info("📊 Estadísticas del bot reseteadas a cero.")
            return True
        except Exception as e:
            logger.error(f"❌ Error reseteando estadísticas: {e}")
            return False

    async def obtener_estado_bot(self) -> Dict[str, Any]:
        """Obtiene el estado general del bot."""
        try:
            query = "SELECT * FROM estado_bot WHERE id = 1"
            async with self._db.execute(query) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "running": bool(row[1]),
                        "direccion_actual": row[2],
                        "pnl_realizado": row[3],
                        "ciclos_completados": row[4],
                        "ultimo_update": row[5],
                        "testnet": bool(row[7]) if len(row) > 7 else True,
                        "symbol": row[8] if len(row) > 8 else 'BTC/USDT:USDT'
                    }
                return {}
        except Exception as e:
            logger.error(f"❌ Error obteniendo estado bot: {e}")
            return {}
    
    async def actualizar_estado_bot(self, **kwargs) -> None:
        """Actualiza el estado del bot."""
        try:
            kwargs['ultimo_update'] = datetime.now().timestamp()
            campos = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            query = f"UPDATE estado_bot SET {campos} WHERE id = 1"
            await self._db.execute(query, list(kwargs.values()))
            await self._db.commit()
        except Exception as e:
            logger.error(f"❌ Error actualizando estado: {e}")
            raise
    
    # =====================
    # HISTORIAL
    # =====================
    
    async def guardar_operacion(self, posicion_id: str, tipo: str, precio: float, 
                                  cantidad: float, precio_promedio: float, 
                                  pnl: float = 0, detalles: str = "") -> None:
        """Guarda una operación en el historial."""
        try:
            query = """
            INSERT INTO historial_operaciones 
            (posicion_id, tipo, precio, cantidad, precio_promedio, pnl, timestamp, detalles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            await self._db.execute(query, (
                posicion_id, tipo, precio, cantidad, precio_promedio, pnl,
                datetime.now().timestamp(), detalles
            ))
            await self._db.commit()
        except Exception as e:
            logger.error(f"❌ Error guardando operación: {e}")
            raise
    
    async def guardar_balance(self, balance_total: float, balance_disponible: float) -> None:
        """Guarda el balance actual."""
        try:
            await self._db.execute(
                "INSERT INTO balance_historico (balance_total, balance_disponible, timestamp) VALUES (?, ?, ?)",
                (balance_total, balance_disponible, datetime.now().timestamp())
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"❌ Error guardando balance: {e}")
            raise
    
    # =====================
    # PERFILES DE CONFIGURACIÓN
    # =====================
    
    async def guardar_perfil(self, nombre: str, config_dict: Dict[str, Any], es_default: bool = False) -> bool:
        """Guarda un perfil de configuración."""
        try:
            now = datetime.now().timestamp()
            
            if es_default:
                await self._db.execute("UPDATE perfiles SET es_default = 0")
            
            query = """
            INSERT OR REPLACE INTO perfiles (nombre, config_json, es_default, created_at, updated_at)
            VALUES (?, ?, ?, COALESCE((SELECT created_at FROM perfiles WHERE nombre = ?), ?), ?)
            """
            await self._db.execute(query, (
                nombre, json.dumps(config_dict), 1 if es_default else 0, nombre, now, now
            ))
            await self._db.commit()
            logger.info(f"💾 Perfil '{nombre}' guardado")
            return True
        except Exception as e:
            logger.error(f"❌ Error guardando perfil: {e}")
            return False
    
    async def cargar_perfil(self, nombre: str) -> Optional[Dict[str, Any]]:
        """Carga un perfil de configuración."""
        try:
            async with self._db.execute(
                "SELECT config_json FROM perfiles WHERE nombre = ?", (nombre,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row['config_json'])
                return None
        except Exception as e:
            logger.error(f"❌ Error cargando perfil: {e}")
            return None
    
    async def listar_perfiles(self) -> List[Dict[str, Any]]:
        """Lista todos los perfiles guardados."""
        try:
            query = "SELECT nombre, es_default, created_at, updated_at FROM perfiles ORDER BY nombre"
            async with self._db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "nombre": row['nombre'],
                        "es_default": bool(row['es_default']),
                        "created_at": row['created_at'],
                        "updated_at": row['updated_at']
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"❌ Error listando perfiles: {e}")
            return []
    
    async def eliminar_perfil(self, nombre: str) -> bool:
        """Elimina un perfil."""
        try:
            await self._db.execute("DELETE FROM perfiles WHERE nombre = ?", (nombre,))
            await self._db.commit()
            logger.info(f"🗑️ Perfil '{nombre}' eliminado")
            return True
        except Exception as e:
            logger.error(f"❌ Error eliminando perfil: {e}")
            return False
    
    async def obtener_perfil_default(self) -> Optional[Dict[str, Any]]:
        """Obtiene el perfil por defecto."""
        try:
            async with self._db.execute(
                "SELECT config_json FROM perfiles WHERE es_default = 1 LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row['config_json'])
                return None
        except Exception as e:
            logger.error(f"❌ Error obteniendo perfil default: {e}")
            return None
    
    async def guardar_perfil_actual(self, nombre: str) -> None:
        """Guarda el nombre del perfil actual."""
        await self.actualizar_estado_bot(perfil_actual=nombre)
    
    async def obtener_perfil_actual(self) -> str:
        """Obtiene el nombre del perfil actual."""
        estado = await self.obtener_estado_bot()
        return estado.get('perfil_actual', 'default')
