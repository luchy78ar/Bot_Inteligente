import time
import asyncio
import logging
from datetime import datetime
from flask import Flask, jsonify, request, make_response

app = Flask(__name__)
logger = logging.getLogger(__name__)
persistencia = None
estado_bot = {}

def actualizar_estado(nuevo_estado):
    global estado_bot
    estado_bot = nuevo_estado.copy()

@app.after_request
def add_header(response):
    """Evitar cache del dashboard."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/', methods=['GET'])
def index():
    """Ruta raíz con Dashboard Profesional COMPACTO en Español."""
    logger.info(f"🌐 Acceso al Dashboard desde {request.remote_addr}")
    
    # Forzar no cache
    from flask import make_response
    response = make_response(render_dashboard())
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
    
    if not estado_bot:
        return """
        <body style='background:#0b0e11; color:#eaecef; display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif;'>
            <div style='text-align:center;'>
                <h2 style='color:#2ebdff;'>NEXUS PRO TERMINAL</h2>
                <p style='color:#848e9c; margin-top:10px;'>📡 Sincronizando con el motor de trading...</p>
                <script>setTimeout(() => { window.location.reload(); }, 2000);</script>
            </div>
        </body>
        """

    running = estado_bot.get('running', False)
    symbol = estado_bot.get('symbol', '---')
    precio = estado_bot.get('precio_actual', 0)
    entrada_breakeven = estado_bot.get('precio_entrada', 0)
    precio_inicial = estado_bot.get('precio_inicial', entrada_breakeven)
    pnl = estado_bot.get('pnl', 0)
    pnl_pct = estado_bot.get('pnl_pct', 0)
    lado = str(estado_bot.get('lado', 'NEUTRAL')).upper()
    testnet = estado_bot.get('testnet', True)
    from datetime import datetime
    current_time = datetime.now().strftime("%H:%M:%S")
    
    # Capital y Riesgo
    balance = estado_bot.get('balance_total', 0)
    invertido = estado_bot.get('capital_invertido', 0)
    apalancado = estado_bot.get('inversion_apalancada', 0)
    liq = estado_bot.get('liquidation_price', 0)
    tp = estado_bot.get('precio_tp', 0)
    
    # Configuración y Martingala
    cfg = estado_bot.get('config', {})
    dca_actual = estado_bot.get('dca_level', 0)
    dca_max = int(cfg.get('max_dca_levels', 2))
    leverage = int(cfg.get('leverage', 10))
    step_pct = float(cfg.get('dca_step_pct', 0.01)) * 100
    multiplicador = float(cfg.get('volume_multiplier', 1.5))
    tp_mode = "INTELIGENTE" if cfg.get('tp_inteligente') else "ESTÁNDAR"
    ciclos_completados = estado_bot.get('ciclos_completados', 0)
    
    # Lógica Visual
    pnl_color = "#02c076" if pnl >= 0 else "#f84960"
    pnl_sign = "+" if pnl >= 0 else ""
    lado_text = "COMPRA (LONG)" if lado == "LONG" else "VENTA (SHORT)" if lado == "SHORT" else "NEUTRAL"
    lado_color = "#02c076" if lado == "LONG" else "#f84960" if lado == "SHORT" else "#848e9c"
    
    # Cálculos de progreso (Basados en ROE% Real para que coincida con la ganancia de capital)
    tp_objetivo_pct = cfg.get('take_profit_pct', 0.01) * 100
    progreso_tp = min(100, (pnl_pct / tp_objetivo_pct * 100)) if (tp_objetivo_pct > 0 and pnl_pct > 0) else 0
    
    dist_total_liq = abs(liq - entrada_breakeven)
    dist_actual_liq = abs(precio - entrada_breakeven)
    en_perdida = (lado == "LONG" and precio < entrada_breakeven) or (lado == "SHORT" and precio > entrada_breakeven)
    riesgo_liq = min(100, (dist_actual_liq / dist_total_liq * 100)) if (dist_total_liq > 0 and en_perdida) else 0
    
    prog_next_dca = (estado_bot.get('proximidad_dca', 0) * 100)
    progreso_total_dca = (dca_actual / dca_max * 100) if dca_max > 0 else 0
    
    # Formatear Liquidación
    liq_display = f"${liq:,.2f}" if liq > 0 else "N/A (SIN RIESGO)"
    liq_color_text = "var(--neon-red)" if liq > 0 else "var(--text-dim)"
    
    modo_badge = "<span style='color:#f0b90b; font-weight:bold; font-size:0.75em; border:1px solid #f0b90b; padding:2px 8px; border-radius:4px; background:rgba(240,185,11,0.1);'>MODO PRUEBAS (TESTNET)</span>" if testnet else "<span style='color:#f84960; font-weight:bold; font-size:0.75em; border:1px solid #f84960; padding:2px 8px; border-radius:4px; background:rgba(248,73,96,0.1);'>DINERO REAL (PROD)</span>"

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=0.8">
        <meta http-equiv="refresh" content="5">
        <title>NEXUS PRO | {symbol}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0b0e11; --card: #181a20; --border: #2b2f36;
                --text-main: #eaecef; --text-dim: #848e9c;
                --neon-green: #02c076; --neon-red: #f84960; --neon-blue: #2ebdff; --neon-yellow: #f0b90b;
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; font-family: 'Inter', sans-serif; }}
            body {{ background: var(--bg); color: var(--text-main); height: 100vh; overflow: hidden; padding: 10px; display: flex; flex-direction: column; }}
            
            .container {{ 
                display: grid; 
                grid-template-columns: repeat(12, 1fr); 
                grid-template-rows: auto auto 1fr auto; 
                gap: 10px; 
                height: 100%; 
                max-width: 1400px; 
                margin: 0 auto; 
                width: 100%;
            }}
            
            .header-pro {{ 
                grid-column: span 12; 
                background: var(--card); 
                padding: 10px 20px; 
                border-radius: 8px; 
                border: 1px solid var(--border); 
                display: flex; 
                justify-content: space-between; 
                align-items: center; 
            }}
            
            .pnl-hero {{ 
                grid-column: span 12; 
                background: var(--card); 
                border-radius: 8px; 
                border: 1px solid var(--border); 
                padding: 12px 25px; 
                display: flex; 
                justify-content: space-between; 
                align-items: center; 
                border-left: 5px solid {pnl_color};
            }}
            .hero-val-main {{ font-size: 2.5em; font-weight: 800; color: {pnl_color}; font-family: 'JetBrains Mono'; line-height: 1; }}
            .hero-label {{ font-size: 0.7em; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 2px; }}
            
            .card-pro {{ 
                grid-column: span 4; 
                background: var(--card); 
                border-radius: 8px; 
                border: 1px solid var(--border); 
                padding: 15px; 
                display: flex; 
                flex-direction: column; 
                justify-content: space-between;
            }}
            .card-title {{ font-size: 0.75em; font-weight: 800; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 12px; display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 5px; }}
            
            .data-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 0.85em; }}
            .data-row:last-child {{ border-bottom: none; }}
            .val-mono {{ font-family: 'JetBrains Mono'; font-weight: 600; font-size: 1.1em; }}

            .progress-block {{ margin-top: 10px; }}
            .progress-info {{ display: flex; justify-content: space-between; font-size: 0.7em; margin-bottom: 4px; color: var(--text-dim); font-weight: 700; }}
            .bar-bg {{ height: 6px; background: #2b2f36; border-radius: 3px; overflow: hidden; }}
            .bar-fill {{ height: 100%; transition: width 1s ease-out; }}
            
            .summary-card {{ 
                grid-column: span 12; 
                display: flex; 
                justify-content: space-between; 
                gap: 10px; 
            }}
            .stat-box {{ 
                flex: 1; 
                background: var(--card); 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid var(--border); 
                text-align: center; 
            }}
            .stat-label {{ font-size: 0.65em; color: var(--text-dim); text-transform: uppercase; font-weight: bold; }}
            .stat-val {{ font-size: 1.1em; font-weight: 800; font-family: 'JetBrains Mono'; margin-top: 3px; }}

            .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 8px; }}
            .dot-online {{ background: var(--neon-green); box-shadow: 0 0 8px var(--neon-green); animation: pulse 2s infinite; }}
            @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} 100% {{ opacity: 1; }} }}

            @media (max-width: 950px) {{ 
                body {{ height: auto; overflow: auto; }} 
                .card-pro {{ grid-column: span 12; }} 
                .pnl-hero {{ flex-direction: column; text-align: center; gap: 15px; padding: 20px; }}
                .summary-card {{ flex-wrap: wrap; }}
                .stat-box {{ min-width: 48%; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <!-- CABECERA -->
            <header class="header-pro">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div style="background: var(--neon-blue); color: #000; padding: 3px 8px; border-radius: 4px; font-weight: 900;">N</div>
                    <div style="font-weight: 800; font-size: 1.1em; letter-spacing: 0.5px;">NEXUS PRO <span style="color: var(--neon-blue);">TERMINAL</span></div>
                </div>
                <div style="display: flex; gap: 20px; align-items: center;">
                    <div style="font-size: 0.85em; font-family: 'JetBrains Mono'; color: var(--text-dim);">🕐 {current_time}</div>
                    {modo_badge}
                    <div style="font-size: 0.75em; font-weight: bold; color: {'var(--neon-green)' if running else 'var(--neon-red)'};">
                        <span class="dot {'dot-online' if running else ''}"></span>{'MOTOR ACTIVO' if running else 'PAUSADO'}
                    </div>
                </div>
            </header>

            <!-- SECCIÓN PRINCIPAL PNL -->
            <section class="pnl-hero">
                <div>
                    <div class="hero-label">Rentabilidad (ROE%)</div>
                    <div style="display: flex; align-items: baseline;">
                        <div class="hero-val-main">{pnl_sign}{pnl_pct:.2f}%</div>
                    </div>
                </div>
                <div style="text-align: right; display: flex; align-items: center; gap: 30px;">
                    <div>
                        <div class="hero-label">PNL No Realizado</div>
                        <div style="font-size: 1.4em; font-weight: 800; color: {pnl_color}; font-family: 'JetBrains Mono';">{pnl_sign}${abs(pnl):,.2f}</div>
                    </div>
                    <div style="text-align: right; border-left: 2px solid var(--border); padding-left: 30px;">
                        <div class="hero-label">Posición Actual</div>
                        <div style="font-size: 1.3em; font-weight: 800; color: {lado_color};">{lado_text} {leverage}X</div>
                        <div style="font-size: 0.8em; color: var(--text-dim); font-family: 'JetBrains Mono';">Precio Mark: ${precio:,.2f}</div>
                    </div>
                </div>
            </section>

            <!-- BLOQUE 1: MERCADO -->
            <div class="card-pro">
                <div>
                    <div class="card-title">Datos de Mercado <span style="color: var(--neon-blue);">EN VIVO</span></div>
                    <div class="data-row"><span>Precio Entrada</span><span class="val-mono">${precio_inicial:,.2f}</span></div>
                    <div class="data-row"><span>Precio Mark</span><span class="val-mono">${precio:,.2f}</span></div>
                    <div class="data-row"><span>Punto Empate (AVG)</span><span class="val-mono" style="color: var(--neon-green); font-weight: 800;">${entrada_breakeven:,.2f}</span></div>
                    <div class="data-row"><span>Liquidación</span><span class="val-mono" style="color: {liq_color_text}; font-weight: 800;">{liq_display}</span></div>
                </div>
                <div class="progress-block">
                    <div class="progress-info"><span>Progreso al Objetivo (TP)</span><span>{int(progreso_tp)}%</span></div>
                    <div class="bar-bg"><div class="bar-fill" style="width: {progreso_tp}%; background: var(--neon-green); box-shadow: 0 0 10px rgba(2,192,118,0.3);"></div></div>
                </div>
            </div>

            <!-- BLOQUE 2: ESTRATEGIA -->
            <div class="card-pro">
                <div>
                    <div class="card-title">Motor Martingala <span style="color: var(--neon-yellow);">Activo</span></div>
                    <div class="data-row"><span>Nivel DCA</span><span class="val-mono" style="color: var(--neon-blue);">{dca_actual} / {dca_max}</span></div>
                    <div class="data-row"><span>Distancia (Step)</span><span class="val-mono">{step_pct:.2f}%</span></div>
                    <div class="data-row"><span>Mult. Step</span><span class="val-mono">{cfg.get('step_multiplier', 1.1)}x</span></div>
                    <div class="data-row"><span>Multiplicador Vol.</span><span class="val-mono">{multiplicador}x</span></div>
                    <div class="data-row"><span>Modo Salida</span><span class="val-mono" style="color: var(--neon-blue);">{tp_mode}</span></div>
                </div>
                <div class="progress-block">
                    <div class="progress-info"><span>Carga Próximo DCA</span><span>{int(prog_next_dca)}%</span></div>
                    <div class="bar-bg"><div class="bar-fill" style="width: {prog_next_dca}%; background: var(--neon-blue); box-shadow: 0 0 8px rgba(46,189,255,0.3);"></div></div>
                </div>
            </div>

            <!-- BLOQUE 3: RIESGO -->
            <div class="card-pro">
                <div>
                    <div class="card-title">Métricas de Riesgo <span style="color: var(--neon-red);">Seguridad</span></div>
                    <div class="data-row"><span>Inversión Real (Margen)</span><span class="val-mono" style="color: var(--neon-green);">${invertido:,.2f}</span></div>
                    <div class="data-row"><span>Exposición (Apalancado)</span><span class="val-mono" style="color: var(--neon-blue);">${apalancado:,.2f}</span></div>
                    <div class="data-row"><span>Ratio de Margen</span><span class="val-mono" style="color: var(--neon-yellow);">{(invertido/balance*100) if balance > 0 else 0:.2f}%</span></div>
                    <div class="data-row"><span>Máx. Drawdown (Récord)</span><span class="val-mono" style="color: var(--neon-red);">{abs(estado_bot.get('max_drawdown', 0)):.2f}%</span></div>
                </div>
                <div class="progress-block">
                    <div class="progress-info"><span>Riesgo Liquidación</span><span>{int(riesgo_liq)}%</span></div>
                    <div class="bar-bg"><div class="bar-fill" style="width: {riesgo_liq}%; background: var(--neon-red); box-shadow: 0 0 8px rgba(248,73,96,0.3);"></div></div>
                </div>
            </div>

            <!-- RESUMEN FINAL -->
            <div class="summary-card">
                <div class="stat-box">
                    <div class="stat-label">Balance Cuenta</div>
                    <div class="stat-val">${balance:,.2f}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Margen en Uso</div>
                    <div class="stat-val" style="color: var(--neon-blue);">${invertido:,.2f}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Profit Realizado</div>
                    <div class="stat-val" style="color: var(--neon-green);">${estado_bot.get('pnl_realizado', 0):,.2f}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Ciclos Completos</div>
                    <div class="stat-val">{ciclos_completados}</div>
                </div>
            </div>
        </div>
        <script>
            // Recarga suave cada 5 segundos para máxima fluidez
            setTimeout(() => {{ window.location.reload(); }}, 5000);
        </script>
    </body>
    </html>
    """

@app.route('/api/status')
def get_status():
    return jsonify(estado_bot)

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

# Ruta de webhook para Telegram - se configura dinámicamente
telegram_app = None
main_event_loop = None

def set_telegram_app(app, loop=None):
    global telegram_app, main_event_loop
    telegram_app = app
    main_event_loop = loop or asyncio.get_event_loop()

@app.route('/webhook/<token>', methods=['POST'])
def telegram_webhook(token: str):
    """Maneja las actualizaciones de Telegram."""
    if telegram_app is None:
        return jsonify({"error": "Telegram not configured"}), 500
    
    try:
        from telegram import Update
        import json
        
        update_data = request.get_data()
        update = Update.de_json(json.loads(update_data), telegram_app.bot)
        
        # Ejecutar en el bucle principal de forma segura desde este hilo
        if main_event_loop:
            future = asyncio.run_coroutine_threadsafe(
                telegram_app.process_update(update), 
                main_event_loop
            )
            # Esperar resultado con timeout
            future.result(timeout=30)
        else:
            return jsonify({"error": "Main loop not found"}), 500
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

import threading

def iniciar_servidor(port=8080):
    """Inicia el servidor web en un hilo separado para no bloquear."""
    def run():
        # Desactivar el logger de Werkzeug para reducir ruido si se desea
        # logging.getLogger('werkzeug').setLevel(logging.ERROR)
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    
    t = threading.Thread(target=run, daemon=True)
    t.start()
