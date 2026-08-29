import functools
import os

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import ai_client
import db
import metrics
import stripe_client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

PRICE_CENTS = int(os.environ.get("PRICE_CENTS", "9900"))  # $99.00 default
PRICE_CURRENCY = os.environ.get("PRICE_CURRENCY", "usd")
PRODUCT_NAME = os.environ.get("PRODUCT_NAME", "Bitácora Trader -- acceso de por vida")

with app.app_context():
    db.init_db()


# ---------------------------------------------------------------- helpers --
@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = db.get_user_by_id(user_id) if user_id else None


@app.context_processor
def inject_user():
    return {"user": g.get("user")}


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Iniciá sesión para continuar.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def paid_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if os.environ.get("SKIP_PAYWALL", "").lower() == "true":
            return view(*args, **kwargs)
        if not g.user["has_lifetime_access"]:
            return redirect(url_for("paywall"))
        return view(*args, **kwargs)
    return wrapped


def price_display():
    return f"{PRICE_CENTS / 100:,.2f}"


# --------------------------------------------------------------- landing --
@app.route("/")
def landing():
    return render_template("landing.html", price_display=price_display())


# ------------------------------------------------------------------ auth --
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if not email or "@" not in email:
            error = "Ingresá un email válido."
        elif len(password) < 8:
            error = "La contraseña debe tener al menos 8 caracteres."
        elif db.get_user_by_email(email):
            error = "Ya existe una cuenta con ese email."
        if error:
            flash(error, "error")
            return render_template("signup.html")
        user_id = db.create_user(email, generate_password_hash(password))
        session.clear()
        session["user_id"] = user_id
        if os.environ.get("SKIP_PAYWALL", "").lower() == "true":
            return redirect(url_for("dashboard"))
        return redirect(url_for("paywall"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email o contraseña incorrectos.", "error")
            return render_template("login.html")
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


# -------------------------------------------------------------- paywall --
@app.route("/paywall")
@login_required
def paywall():
    if g.user["has_lifetime_access"]:
        return redirect(url_for("dashboard"))
    return render_template("paywall.html", price_display=price_display())


@app.route("/checkout/create", methods=["POST"])
@login_required
def create_checkout():
    if g.user["has_lifetime_access"]:
        return redirect(url_for("dashboard"))
    checkout = stripe_client.create_checkout_session(
        user_id=g.user["id"],
        user_email=g.user["email"],
        amount_cents=PRICE_CENTS,
        currency=PRICE_CURRENCY,
        product_name=PRODUCT_NAME,
        success_url=url_for("checkout_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("checkout_cancel", _external=True),
    )
    return redirect(checkout["url"])


@app.route("/checkout/success")
@login_required
def checkout_success():
    session_id = request.args.get("session_id")
    paid = bool(g.user["has_lifetime_access"])
    # El webhook es la fuente de verdad, pero si ya llegó lo confirmamos
    # acá mismo para no dejar al usuario esperando sin explicación.
    if not paid and session_id:
        try:
            cs = stripe_client.retrieve_checkout_session(session_id)
            if cs.get("payment_status") == "paid":
                db.grant_lifetime_access(g.user["id"])
                paid = True
        except Exception:
            pass
    return render_template("checkout_result.html", success=True, paid=paid)


@app.route("/checkout/cancel")
@login_required
def checkout_cancel():
    return render_template("checkout_result.html", success=False, paid=False)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        return {"error": "webhook not configured"}, 500

    payload = request.get_data()  # cuerpo crudo, sin tocar
    sig_header = request.headers.get("Stripe-Signature")
    try:
        stripe_client.verify_webhook_signature(payload, sig_header, webhook_secret)
    except stripe_client.SignatureVerificationError as e:
        return {"error": str(e)}, 400

    event = request.get_json(force=True, silent=True) or {}
    event_id = event.get("id")
    if event_id and db.event_already_processed(event_id):
        return {"ok": True, "duplicate": True}, 200

    if event.get("type") == "checkout.session.completed":
        obj = event.get("data", {}).get("object", {})
        user_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
        if user_id and obj.get("payment_status") == "paid":
            db.grant_lifetime_access(int(user_id))

    if event_id:
        db.mark_event_processed(event_id)
    return {"ok": True}, 200


# ----------------------------------------------------------- dashboard --
@app.route("/dashboard")
@login_required
@paid_required
def dashboard():
    ops = db.list_operations(g.user["id"])
    rows = metrics.simulate(ops, g.user)
    m = metrics.compute_metrics(rows, g.user["capital_inicial"])
    chart = build_chart_svg(rows, g.user["capital_inicial"])
    tags = db.list_tags(g.user["id"])
    return render_template(
        "dashboard.html", rows=list(reversed(rows)), m=m, chart=chart,
        capital_inicial=g.user["capital_inicial"], calc_mode=g.user["calc_mode"],
        riesgo_pct=g.user["riesgo_pct"], riesgo_fijo=g.user["riesgo_fijo"],
        rr=g.user["rr"], be_trigger=g.user["be_trigger"], tags=tags,
    )


@app.route("/operations/add", methods=["POST"])
@login_required
@paid_required
def add_operation():
    f = request.form
    calc_mode = g.user["calc_mode"]

    session_tag = (f.get("session") or "").strip()
    if not session_tag:
        flash("Ingresá una sesión o etiqueta para la operación.", "error")
        return redirect(url_for("dashboard"))

    r_points = f.get("r_points") or None
    try:
        r_points = float(r_points) if r_points else None
    except ValueError:
        r_points = None

    r_multiple = None
    pnl_manual = None

    if calc_mode == "direct":
        raw = (f.get("pnl_manual") or "").strip().replace(",", ".")
        try:
            pnl_manual = float(raw)
        except ValueError:
            flash("Ingresá el resultado en $ de la operación.", "error")
            return redirect(url_for("dashboard"))
        result = "BE" if pnl_manual == 0 else ("TP" if pnl_manual > 0 else "SL")
    else:
        result = f.get("result", "").upper()
        if result not in ("TP", "SL", "BE"):
            flash("Resultado inválido.", "error")
            return redirect(url_for("dashboard"))
        raw = (f.get("r_multiple") or "").strip().replace(",", ".")
        if raw:
            try:
                r_multiple = float(raw)
            except ValueError:
                flash("El valor de R personalizado no es válido.", "error")
                return redirect(url_for("dashboard"))
            result = "BE" if r_multiple == 0 else ("TP" if r_multiple > 0 else "SL")

    db.add_operation(
        g.user["id"],
        f.get("op_date") or None,
        session_tag,
        f.get("direction") or None,
        r_points,
        result,
        r_multiple,
        pnl_manual,
        f.get("recorrido") or None,
    )
    return redirect(url_for("dashboard"))


@app.route("/operations/<int:op_id>/delete", methods=["POST"])
@login_required
@paid_required
def delete_operation(op_id):
    db.delete_operation(g.user["id"], op_id)
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------- settings --
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        try:
            capital = float(request.form["capital_inicial"])
            calc_mode = request.form.get("calc_mode", "pct")
            if calc_mode not in ("pct", "fixed", "direct"):
                raise ValueError
            riesgo_pct = float(request.form.get("riesgo_pct") or 0) / 100.0
            riesgo_fijo = float(request.form.get("riesgo_fijo") or 0)
            rr = float(request.form.get("rr") or 0)
            be_trigger = float(request.form.get("be_trigger") or 0)
            if capital <= 0:
                raise ValueError
            if calc_mode == "pct" and not (0 < riesgo_pct <= 1):
                raise ValueError
            if calc_mode == "fixed" and riesgo_fijo <= 0:
                raise ValueError
            if calc_mode in ("pct", "fixed") and (rr <= 0 or be_trigger < 0):
                raise ValueError
        except (KeyError, ValueError):
            flash("Revisá los valores ingresados.", "error")
            return render_template("settings.html")
        db.update_settings(g.user["id"], capital, calc_mode, riesgo_pct, riesgo_fijo, rr, be_trigger)
        flash("Configuración guardada.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html")


# ------------------------------------------------------------ asistente --
@app.route("/asistente")
@login_required
@paid_required
def asistente():
    ops = db.list_operations(g.user["id"])
    rows = metrics.simulate(ops, g.user)
    history = db.list_chat_messages(g.user["id"])
    ai_configured = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return render_template(
        "asistente.html", history=history, ai_configured=ai_configured, has_ops=bool(rows),
    )


@app.route("/asistente/mensaje", methods=["POST"])
@login_required
@paid_required
def asistente_mensaje():
    texto = (request.form.get("mensaje") or "").strip()
    if not texto:
        return redirect(url_for("asistente"))

    ops = db.list_operations(g.user["id"])
    rows = metrics.simulate(ops, g.user)
    if not rows:
        flash("Cargá al menos una operación antes de usar el asistente.", "error")
        return redirect(url_for("asistente"))
    m = metrics.compute_metrics(rows, g.user["capital_inicial"])
    context_summary = ai_client.build_context_summary(g.user, m)

    history = db.list_chat_messages(g.user["id"])
    api_messages = [{"role": h["role"], "content": h["content"]} for h in history]
    api_messages.append({"role": "user", "content": texto})

    try:
        reply = ai_client.chat(api_messages, context_summary)
    except ai_client.AIError as e:
        flash(str(e), "error")
        return redirect(url_for("asistente"))

    db.add_chat_message(g.user["id"], "user", texto)
    db.add_chat_message(g.user["id"], "assistant", reply)
    return redirect(url_for("asistente"))


@app.route("/asistente/limpiar", methods=["POST"])
@login_required
@paid_required
def asistente_limpiar():
    db.clear_chat(g.user["id"])
    return redirect(url_for("asistente"))


# --------------------------------------------------------- equity chart --
def build_chart_svg(rows, start_balance):
    W, H, PAD_L, PAD_R, PAD_T, PAD_B = 960, 220, 54, 16, 16, 28
    if not rows:
        return None
    balances = [start_balance] + [r["balance_after"] for r in rows]
    min_b, max_b = min(balances), max(balances)
    span = max(max_b - min_b, 1)
    pad = span * 0.12
    y_min, y_max = min_b - pad, max_b + pad

    def x_for(i):
        return PAD_L + (i / (len(balances) - 1 or 1)) * (W - PAD_L - PAD_R)

    def y_for(v):
        return PAD_T + (1 - (v - y_min) / (y_max - y_min)) * (H - PAD_T - PAD_B)

    line_pts = " ".join(f"{x_for(i):.1f},{y_for(b):.1f}" for i, b in enumerate(balances))
    area_pts = f"{x_for(0):.1f},{y_for(y_min):.1f} " + line_pts + f" {x_for(len(balances)-1):.1f},{y_for(y_min):.1f}"
    base_y = y_for(start_balance)

    grid = []
    for t in (0, 0.25, 0.5, 0.75, 1):
        y = PAD_T + t * (H - PAD_T - PAD_B)
        val = y_max - t * (y_max - y_min)
        grid.append((PAD_L, W - PAD_R, y, f"${val:,.0f}"))

    dots = [(x_for(i), y_for(b)) for i, b in enumerate(balances)]

    return {
        "W": W, "H": H, "line_pts": line_pts, "area_pts": area_pts, "base_y": base_y,
        "grid": grid, "dots": dots, "pad_l": PAD_L,
    }


if __name__ == "__main__":
    app.run(debug=True, port=5050)
