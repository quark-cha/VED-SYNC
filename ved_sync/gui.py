"""Tkinter stays on its own thread; hashing runs in a single worker."""
import queue
import threading
import tkinter as tk

COLORS = {'verde': '#198754', 'amarillo': '#ffc107', 'rojo': '#dc3545', 'gris': '#808080'}


def run(engine):
    window = tk.Tk()
    window.title('VED-SYNC — ' + ('APLICANDO' if engine.apply else 'SIMULACIÓN'))
    window.attributes('-topmost', True)
    updates = queue.Queue()
    stop = threading.Event()
    rows = {}
    for name in engine.repos:
        row = tk.Label(window, text=f'● {name}: gris', fg=COLORS['gris'], anchor='w', font=('Arial', 14))
        row.pack(fill='x', padx=15, pady=5)
        rows[name] = row
    message = tk.Label(window, text='Iniciando…', wraplength=480)
    message.pack(padx=15, pady=10)

    def worker():
        while not stop.is_set():
            try:
                report = engine.run_once(on_status=lambda s: updates.put((s, 'Escaneando y verificando SHA-256…')))
                updates.put((report['status'], json_summary(report)))
            except Exception as exc:
                updates.put(({n: 'rojo' for n in rows}, str(exc)))
            stop.wait(engine.interval)
        updates.put((None, None))

    thread = threading.Thread(target=worker, daemon=False)
    thread.start()

    def poll():
        try:
            while True:
                statuses, detail = updates.get_nowait()
                if statuses is None:
                    window.destroy()
                    return
                for name, status in statuses.items():
                    rows[name].configure(text=f'● {name}: {status}', fg=COLORS[status])
                message.configure(text=detail)
        except queue.Empty:
            pass
        window.after(100, poll)

    def close():
        stop.set()
        message.configure(text='Terminando el ciclo actual de forma segura…')
    window.protocol('WM_DELETE_WINDOW', close)
    poll()
    window.mainloop()


def json_summary(report):
    problems = [e for e in report['events'] if e['type'] in ('error', 'conflict', 'pending')]
    return str(problems[-1]) if problems else f"{'Simulación' if report['simulation'] else 'Aplicación'}: {len(report['events'])} operaciones."
