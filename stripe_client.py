"""
Integración con Stripe SIN el SDK oficial (no se puede instalar paquetes
nuevos en este entorno) -- llamando directo a la API REST de Stripe con
`requests`, y verificando la firma del webhook a mano con hmac/hashlib.
Esto es exactamente lo que hace el SDK por dentro; no es un hack.
"""
import hashlib
import hmac
import os
import time

import requests

STRIPE_API_BASE = "https://api.stripe.com/v1"


def _secret_key():
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("Falta STRIPE_SECRET_KEY en las variables de entorno.")
    return key


def create_checkout_session(*, user_id, user_email, amount_cents, currency,
                             product_name, success_url, cancel_url):
    """Crea una Checkout Session de Stripe en modo 'payment' (pago único,
    ideal para un acceso 'de por vida'). Devuelve la URL a la que hay que
    redirigir al cliente."""
    data = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "customer_email": user_email,
        "client_reference_id": str(user_id),
        "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": currency,
        "line_items[0][price_data][unit_amount]": amount_cents,
        "line_items[0][price_data][product_data][name]": product_name,
        "metadata[user_id]": str(user_id),
    }
    resp = requests.post(
        f"{STRIPE_API_BASE}/checkout/sessions",
        data=data,
        auth=(_secret_key(), ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def retrieve_checkout_session(session_id):
    resp = requests.get(
        f"{STRIPE_API_BASE}/checkout/sessions/{session_id}",
        auth=(_secret_key(), ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class SignatureVerificationError(Exception):
    pass


def verify_webhook_signature(payload_bytes, sig_header, webhook_secret, tolerance_seconds=300):
    """Verificación manual de la firma de un webhook de Stripe.
    Ver: https://docs.stripe.com/webhooks/signatures (sección 'Verify manually').
    payload_bytes debe ser el cuerpo CRUDO de la request (sin tocar)."""
    if not sig_header:
        raise SignatureVerificationError("Falta el header Stripe-Signature.")

    parts = {}
    for item in sig_header.split(","):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        parts.setdefault(k.strip(), []).append(v.strip())

    if "t" not in parts or "v1" not in parts:
        raise SignatureVerificationError("Header de firma con formato inesperado.")

    timestamp = parts["t"][0]
    signed_payload = f"{timestamp}.".encode() + payload_bytes
    expected = hmac.new(webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    if not any(hmac.compare_digest(expected, v1) for v1 in parts["v1"]):
        raise SignatureVerificationError("La firma no coincide -- el evento no vino de Stripe.")

    if abs(time.time() - int(timestamp)) > tolerance_seconds:
        raise SignatureVerificationError("El evento es demasiado viejo (posible replay attack).")

    return True
