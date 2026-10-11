"""
تشغيل المنصة في وضع الإنتاج على Windows باستخدام waitress.
الاستخدام:  .venv\\Scripts\\python.exe serve.py  [--port 8000]
يستمع على جميع واجهات الشبكة (0.0.0.0) لتصل إليه أجهزة الشبكة الداخلية.
"""
import argparse
import os
import socket
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)
    from apps.core.bootstrap import ensure_reference_data

    ensure_reference_data()

    from waitress import serve

    from config.wsgi import application

    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "127.0.0.1"
    print(f"المنصة تعمل الآن:\n  على هذا الجهاز:   http://127.0.0.1:{args.port}\n  من الشبكة الداخلية: http://{ip}:{args.port}")
    sys.stdout.flush()
    serve(application, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
