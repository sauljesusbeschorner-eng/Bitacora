"""
Motor de cálculo de la bitácora — misma convención usada en toda la
conversación con el trader:

  - Cualquier operación marcada BE cierra en $0, sin importar qué diga
    después ("recorrido" es solo información extra, no cambia el P&L).
  - TP paga 2x el riesgo (relación configurable, default 1:2).
  - SL pierde 1x el riesgo.
  - El riesgo de cada operación es un % del balance en ese momento
    (compuesto), configurable por usuario.
"""


def simulate(operations, start_balance, risk_pct, rr):
    """operations: lista de dicts con session, direction, r_points,
    result ('TP'/'SL'/'BE'), recorrido, op_date -- ordenadas cronológicamente.
    Devuelve la misma lista enriquecida con risk/pnl/balance_before/after."""
    bal = start_balance
    rows = []
    for i, o in enumerate(operations, start=1):
        risk = round(bal * risk_pct, 2)
        is_be = o["result"] == "BE"
        if is_be:
            pnl = 0.0
        elif o["result"] == "TP":
            pnl = round(risk * rr, 2)
        else:  # SL
            pnl = -risk
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
        elif r["result"] == "TP":
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
        t = "win" if r["result"] == "TP" else "loss"
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

    sessions = {"Asia": {"n": 0, "w": 0, "l": 0, "be": 0},
                "Londres": {"n": 0, "w": 0, "l": 0, "be": 0},
                "NY": {"n": 0, "w": 0, "l": 0, "be": 0}}
    for r in rows:
        s = sessions.setdefault(r["session"], {"n": 0, "w": 0, "l": 0, "be": 0})
        s["n"] += 1
        if r["is_be"]:
            s["be"] += 1
        elif r["result"] == "TP":
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
