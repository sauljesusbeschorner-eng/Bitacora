"""
Cliente minimalista para el Asistente de IA (Anthropic Messages API),
con el mismo estilo que stripe_client.py: requests crudo, sin SDK.

Requiere la variable de entorno ANTHROPIC_API_KEY (se configura en
Render, nunca se pega en el código ni se muestra en la app).
"""
import json
import os

import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

SYSTEM_PROMPT = (
    "Sos el asistente de IA de Bitácora Trader, una app de diario de operaciones. "
    "Tu única función es ayudar al usuario a entender su propio historial de "
    "operaciones, usando las métricas que se te dan como contexto (win rate, "
    "profit factor, drawdown, rendimiento por sesión/etiqueta, rachas, etc.). "
    "Respondé siempre en español, de forma clara, breve y concreta. "
    "No dés señales de entrada, no recomiendes comprar o vender ningún "
    "instrumento financiero, y no actúes como asesor de inversión — si te "
    "preguntan eso, aclará amablemente que no es tu función. Podés señalar "
    "patrones, fortalezas y debilidades en la gestión de riesgo y disciplina "
    "del usuario, y hacer preguntas que lo ayuden a reflexionar sobre su propio "
    "desempeño."
)


class AIError(Exception):
    pass


def build_context_summary(user, m):
    pf = m.get("pf")
    pf_display = "∞" if pf == float("inf") else (f"{pf:.2f}" if pf is not None else "—")
    win_rate = m.get("win_rate")
    lines = [
        f"Modo de cálculo: {user['calc_mode']}",
        f"Capital inicial: ${user['capital_inicial']:.2f}",
        f"Balance actual: ${m['final_balance']:.2f} "
        f"({'+' if m['pnl_total'] >= 0 else ''}{m['pnl_total']:.2f}, {m['pnl_pct']:.1f}%)",
        f"Operaciones totales: {m['n']} ({m['wins']} ganadoras, {m['losses']} perdedoras, {m['scratches']} en breakeven)",
        f"Win rate: {win_rate:.1f}%" if win_rate is not None else "Win rate: sin datos todavía",
        f"Profit factor: {pf_display}",
        f"Drawdown actual: {m['cur_dd']:.1f}% | Drawdown máximo: {m['max_dd']:.1f}%",
        f"Mejor racha ganadora: {m['best_win']} | Peor racha perdedora: {m['worst_loss']}",
    ]
    if m.get("sessions"):
        lines.append("Desempeño por sesión/etiqueta:")
        for name, s in m["sessions"].items():
            lines.append(f"  - {name}: {s['n']} operaciones ({s['w']}G / {s['l']}P / {s['be']}BE)")
    return "\n".join(lines)


def chat(messages, context_summary):
    """messages: lista de {"role": "user"|"assistant", "content": str},
    en orden cronológico, terminando en el mensaje nuevo del usuario.
    context_summary: texto con las métricas actuales, se antepone al
    primer mensaje de la conversación para que el modelo tenga contexto
    sin tener que reenviarlo en cada turno."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIError("El asistente de IA todavía no está activado en esta cuenta (falta ANTHROPIC_API_KEY).")
    if not messages:
        raise AIError("No hay ningún mensaje para enviar.")

    full_messages = [dict(m) for m in messages]
    full_messages[0]["content"] = (
        f"[Contexto actual de mi bitácora]\n{context_summary}\n\n[Mi mensaje]\n{full_messages[0]['content']}"
    )

    payload = {
        "model": DEFAULT_MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": full_messages,
    }
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            data=json.dumps(payload),
            timeout=30,
        )
    except requests.RequestException as e:
        raise AIError(f"No se pudo contactar al servicio de IA: {e}")

    if resp.status_code != 200:
        raise AIError(f"Error del servicio de IA ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    parts = data.get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return text.strip() or "No obtuve una respuesta del asistente. Probá de nuevo en un momento."
