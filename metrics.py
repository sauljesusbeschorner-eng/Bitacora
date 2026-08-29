"""
Motor de cálculo de la bitácora.

Soporta tres formas de calcular el resultado de cada operación, según
la configuración de cada usuario (user["calc_mode"]):

  - "pct":    el riesgo de cada operación es un % del balance en ese
              momento (compuesto). El resultado se expresa en múltiplos
              de R: si la operación no trae un r_multiple propio, se usa
              +rr para TP, -1 para SL y 0 para BE (comportamiento
              histórico, compatible con operaciones viejas).
  - "fixed":  igual que "pct" pero el riesgo es un monto fijo en $ que
              no cambia con el balance (no compone).
  - "direct": no hay cálculo de riesgo en absoluto. El usuario carga el
              P&L real en $ de cada operación (pnl_manual) y listo.

En los modos "pct"/"fixed", cualquier operación puede traer su propio
r_multiple (por ejemplo 1.8 para un cierre parcial, -0.3 para una
salida anticipada) que pisa el TP/SL/BE fijo — así una sola estrategia
de riesgo fijo no obliga a que todos los TP paguen exactamente lo mismo.
"""


def simulate(operations, user):
    """operations: lista de dicts con session, direction, r_points,
    result ('TP'/'SL'/'BE'), r_multiple, pnl_manual, recorrido, op_date
    -- ordenadas cronológicamente.
    user: dict/Row con capital_inicial, calc_mode, riesgo_pct,
    riesgo_fijo, rr.
    Devuelve la misma lista enriquecida con risk/pnl/balance_before/after."""
    bal = user["capital_inicial"]
    mode = user["calc_mode"] if user["calc_mode"] else "pct"
    rows = []
    for i, o in enumerate(operations, start=1):
        if mode == "direct":
            pnl = round(o.get("pnl_manual") or 0.0, 2)
            risk = None
            is_be = pnl == 0
        else:
            if mode == "fixed":
                risk = round(user["riesgo_fijo"], 2)
            else:
                risk = round(bal * user["riesgo_pct"], 2)
            r_mult = o.get("r_multiple")
            if r_mult is None:
                if o["result"] == "BE":
                    r_mult = 0.0
                elif o["result"] == "TP":
                    r_mult = user["rr"]
                else:
                    r_mult = -1.0
            pnl = round(risk * r_mult, 2)
            is_be = r_mult == 0
        before = bal
        bal = round(bal + pnl, 2)
        rows.append({
            **o,
            "idx": i,
            "risk": risk,
            "pnl": pnl,
            "balance_before": before,
            "balance_after": bal,
            "is_be": is_be,
        })
    return rows


def compute_metrics(rows, start_balance):
    n = len(rows)
    wins = losses = scratches = 0
    gross_win = gross_loss = 0.0
    cur_win = cur_loss = best_win = worst_loss = 0

    for r in rows:
        if r["is_be"]:
            scratches += 1
            cur_win = cur_loss = 0
        elif r["pnl"] > 0:
            wins += 1
            gross_win += r["pnl"]
            cur_win += 1
            cur_loss = 0
            best_win = max(best_win, cur_win)
        else:
            losses += 1
            gross_loss += -r["pnl"]
            cur_loss += 1
            cur_win = 0
            worst_loss = max(worst_loss, cur_loss)

    # racha actual (desde la última operación hacia atrás)
    cur_streak_type, cur_streak = None, 0
    for r in reversed(rows):
        if r["is_be"]:
            break
        t = "win" if r["pnl"] > 0 else "loss"
        if cur_streak_type is None:
            cur_streak_type, cur_streak = t, 1
        elif t == cur_streak_type:
            cur_streak += 1
        else:
            break

    peak, max_dd, cur_dd = start_balance, 0.0, 0.0
    for r in rows:
        peak = max(peak, r["balance_after"])
        dd = (peak - r["balance_after"]) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
    if rows:
        last = rows[-1]["balance_after"]
        cur_dd = (peak - last) / peak * 100 if peak > 0 else 0

    final_bal = rows[-1]["balance_after"] if rows else start_balance
    pnl_total = final_bal - start_balance
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)

    # Las sesiones/etiquetas ahora son libres: se arman a partir de lo
    # que el usuario haya cargado, no de una lista fija.
    sessions = {}
    for r in rows:
        tag = r["session"] or "Sin etiqueta"
        s = sessions.setdefault(tag, {"n": 0, "w": 0, "l": 0, "be": 0})
        s["n"] += 1
        if r["is_be"]:
            s["be"] += 1
        elif r["pnl"] > 0:
            s["w"] += 1
        else:
            s["l"] += 1

    return {
        "n": n, "wins": wins, "losses": losses, "scratches": scratches,
        "gross_win": gross_win, "gross_loss": gross_loss, "pf": pf,
        "win_rate": (wins / n * 100) if n else None,
        "final_balance": final_bal, "pnl_total": pnl_total,
        "pnl_pct": (pnl_total / start_balance * 100) if start_balance else 0,
        "max_dd": max_dd, "cur_dd": cur_dd,
        "best_win": best_win, "worst_loss": worst_loss,
        "cur_streak": cur_streak, "cur_streak_type": cur_streak_type,
        "sessions": sessions,
    }
