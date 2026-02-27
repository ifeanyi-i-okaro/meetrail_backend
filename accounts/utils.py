import os
import json
import requests

# Ensure Google OAuth calls can verify TLS certs (prevents "missing auth credential" errors)
try:
    import certifi

    ca_bundle = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
    os.environ.setdefault("CURL_CA_BUNDLE", ca_bundle)
    print("🔒 Using CA bundle:", ca_bundle)
except Exception as err:
    print("⚠️ certifi not available:", err)

# IMPORTANT: set CA bundle env before importing firebase_admin/google-auth
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize once (prefer AppConfig.ready or module-level guard)
FIREBASE_SERVICE_ACCOUNT = "/Users/ifeanyi.okaro/Downloads/PROJ/MEETRAIL/App/frontend/meetrail_frontend/meetrail-app-firebase-adminsdk-fbsvc-73eabd795b.json"
FIREBASE_PROJECT_ID = "meetrail-app"
firebase_app = None

def get_firebase_app():
    global firebase_app
    if firebase_app is not None:
        return firebase_app

    # Remove any previously-initialized apps so we don't reuse ADC/External creds.
    if firebase_admin._apps:
        print("⚠️ Clearing existing Firebase apps to avoid ExternalCredentials.")
        for app in list(firebase_admin._apps.values()):
            firebase_admin.delete_app(app)

    print("🔑 Initializing Firebase Admin SDK (service account)")
    cert_cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
    firebase_app = firebase_admin.initialize_app(
        cert_cred,
        {"projectId": FIREBASE_PROJECT_ID},
    )
    return firebase_app



#EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

def send_push_notification(tokens, title, body, data=None, image=None):
    import json
    from firebase_admin import messaging

    firebase_app = get_firebase_app()

    data = data or {}

    print("🔔 send_push_notification called")
    print("🔔 title:", title)
    print("🔔 body:", body)
    print("🔔 data:", data)

    # Remove Expo tokens + de-duplicate
    tokens = list({t for t in tokens if t and not t.startswith("ExponentPushToken[")})
    print("🔔 tokens (deduped):", tokens)

    if not tokens:
        print("⚠️ No valid FCM tokens")
        return None

    notifee_payload = {
        "title": title,
        "body": body,
        "data": data,
        "android": {
            "channelId": "default",
            "largeIcon": image,
            "style": {"type": "BIGPICTURE", "picture": image} if image else None,
        },
        "ios": {
            "attachments": [{"url": image}] if image else []
        },
    }

    message = messaging.MulticastMessage(
        tokens=tokens,
        data={"notifee": json.dumps(notifee_payload)},
        notification=messaging.Notification(
            title=title,
            body=body,
            image=image,
        ),
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="default",
                image=image,
            ),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    content_available=True,
                    mutable_content=True,
                ),
            ),
        ),
    )

    def log_batch_response(response):
        try:
            print("🔔 Push response:", {
                "success_count": response.success_count,
                "failure_count": response.failure_count,
            })
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    print(f"⚠️ Token[{idx}] error:", resp.exception)
                    try:
                        print(f"⚠️ Token[{idx}] error type:", type(resp.exception))
                        print(f"⚠️ Token[{idx}] error repr:", repr(resp.exception))
                        code = getattr(resp.exception, "code", None)
                        if code:
                            print(f"⚠️ Token[{idx}] error code:", code)
                        http_resp = getattr(resp.exception, "http_response", None)
                        if http_resp is not None:
                            status = getattr(http_resp, "status_code", None)
                            print(f"⚠️ Token[{idx}] http status:", status)
                            content = getattr(http_resp, "content", None)
                            if content:
                                try:
                                    print(f"⚠️ Token[{idx}] http body:", content.decode("utf-8"))
                                except Exception:
                                    print(f"⚠️ Token[{idx}] http body (raw):", content)
                    except Exception as err:
                        print("⚠️ Failed to log detailed token error:", err)
        except Exception as err:
            print("⚠️ Failed to parse push response:", err)

    # Log the exact endpoint that FCM will receive (v1 HTTP API)
    try:
        fcm_endpoint = f"https://fcm.googleapis.com/v1/projects/{firebase_app.project_id}/messages:send"
        print("🔔 FCM endpoint:", fcm_endpoint)
    except Exception as err:
        print("⚠️ Failed to build FCM endpoint:", err)

    # Log a safe view of the payload (data + notification + platform configs)
    try:
        print("🔔 FCM payload (preview):", {
            "tokens_count": len(tokens),
            "notification": {"title": title, "body": body},
            "data_keys": list((data or {}).keys()),
            "has_image": bool(image),
            "android": {"channelId": "default", "has_image": bool(image)},
            "apns": {"aps": {"sound": "default", "mutable-content": True}},
        })
    except Exception as err:
        print("⚠️ Failed to log payload preview:", err)

    # Force an access token fetch so we can see auth errors clearly
    try:
        print("🔔 Firebase app name:", firebase_app.name)
        print("🔔 Firebase project_id:", firebase_app.project_id)
        print("🔔 Credential type:", type(firebase_app.credential))
        access = firebase_app.credential.get_access_token()
        token_preview = access.token[:10] + "..." if getattr(access, "token", None) else "none"
        print("🔔 Access token OK, expires:", access.expiry, "| token:", token_preview)
    except Exception as err:
        print("❌ Failed to obtain Google OAuth token:", err)
        return None

    # Use whichever your firebase-admin supports
    if hasattr(messaging, "send_each_for_multicast"):
        print("🔔 Sending via send_each_for_multicast")
        response = messaging.send_each_for_multicast(message, app=firebase_app)
        log_batch_response(response)
        return response

    # Fallback for older versions
    messages = []
    for t in tokens:
        messages.append(
            messaging.Message(
                token=t,
                data={"notifee": json.dumps(notifee_payload)},
                notification=messaging.Notification(
                    title=title,
                    body=body,
                    image=image,
                ),
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="default",
                        image=image,
                    ),
                ),
                apns=messaging.APNSConfig(
                    headers={"apns-priority": "10"},
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            content_available=True,
                            mutable_content=True,
                        ),
                    ),
                ),
            )
        )
    print("🔔 Sending via send_all")
    response = messaging.send_all(messages, app=firebase_app)
    log_batch_response(response)
    return response
