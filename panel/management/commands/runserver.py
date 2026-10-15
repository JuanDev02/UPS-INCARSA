import os
import sys
import tempfile
import threading
import time
import webbrowser

from django.contrib.staticfiles.management.commands.runserver import Command as BaseRunserverCommand
from panel.management.commands.run_monitor import start_monitor_in_background


class Command(BaseRunserverCommand):
    help = "Inicia el servidor web Django Centinela, arranca automáticamente el monitor Multi-UPS y abre el navegador."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--open-browser',
            action='store_true',
            dest='open_browser',
            default=False,
            help='Abre automáticamente el proyecto en el navegador web predeterminado una vez el servidor esté listo.',
        )

    def inner_run(self, *args, **options):
        # Detectar si se solicitó abrir el navegador (por parámetro CLI o variable de entorno)
        self.should_open_browser = options.get('open_browser', False) or (os.environ.get("CENTINELA_OPEN_BROWSER") == "1")

        # Iniciar el monitor multi-UPS en un hilo demonio en segundo plano (proceso activo de ejecución)
        start_monitor_in_background()
        super().inner_run(*args, **options)

    def on_bind(self, server_port):
        super().on_bind(server_port)
        if getattr(self, 'should_open_browser', False):
            self.abrir_navegador(server_port)

    def abrir_navegador(self, server_port):
        """
        Abre el navegador web predeterminado en http://localhost:{server_port}/
        una vez el socket del servidor está enlazado y listo para recibir peticiones.
        Utiliza un archivo de bloqueo en TEMP para evitar aperturas duplicadas en auto-recargas.
        """
        if os.environ.get("CENTINELA_NO_BROWSER") == "1":
            return

        lock_path = os.path.join(tempfile.gettempdir(), "centinela_browser_opened.lock")
        try:
            if os.path.exists(lock_path):
                # Si ya se abrió en los últimos 10 segundos, no abrir una pestaña duplicada
                if time.time() - os.path.getmtime(lock_path) < 10:
                    return
            with open(lock_path, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

        url = f"http://localhost:{server_port}/"
        self.stdout.write(self.style.SUCCESS(f"\n  >> [CENTINELA] Abriendo panel en su navegador web: {url}\n"))

        def _lanzar():
            # Breve pausa para asegurar que el despachador HTTP esté escuchando conexiones entrantes
            time.sleep(0.3)
            try:
                webbrowser.open(url)
            except Exception as e:
                self.stderr.write(f"  [!] No se pudo abrir automáticamente el navegador: {e}")

        t = threading.Thread(target=_lanzar, daemon=True)
        t.start()

