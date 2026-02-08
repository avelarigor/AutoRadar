#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interface de Progresso - AutoRadar
Janela com logo centralizada, sem título, mensagens e barra do pipeline.
"""

import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import shutil
import webbrowser

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "logo_autoradar.png"
ICON_PATH = BASE_DIR / "autoradar_icon.ico"


def _safe_update(widget_or_root):
    """Atualiza widget apenas se a janela ainda existir (evita TclError)."""
    try:
        if hasattr(widget_or_root, 'winfo_exists') and not widget_or_root.winfo_exists():
            return
        widget_or_root.update()
    except (tk.TclError, Exception):
        pass


# Largura máxima da logo (maior para melhor presença visual)
LOGO_MAX_WIDTH = 340


def _is_main_thread():
    """True se estivermos na thread principal (tk)."""
    try:
        import threading
        return threading.current_thread() is threading.main_thread()
    except Exception:
        return True


class ProgressWindow:
    """Janela de progresso do AutoRadar: logo centralizada e redimensionada, sem título, mensagens + barra."""

    def __init__(self, on_config_clicked=None, on_restart_flow=None):
        self.on_config_clicked = on_config_clicked
        self.on_restart_flow = on_restart_flow
        self._close_scheduled = False
        self._closing = False
        self._after_ids = []  # IDs de eventos after() para cancelar no fechamento
        self._tray_icon = None
        self.root = tk.Tk()
        self.root.title("AutoRadar")
        self.root.geometry("820x620")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f4f0")
        if ICON_PATH.exists():
            try:
                self.root.iconbitmap(str(ICON_PATH))
            except Exception:
                pass
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (820 // 2)
        y = (self.root.winfo_screenheight() // 2) - (620 // 2)
        self.root.geometry(f"820x620+{x}+{y}")

        self._logo_photo = None
        self.create_widgets()

    def create_widgets(self):
        # Logo centralizada e maior
        logo_frame = tk.Frame(self.root, bg="#f0f4f0")
        logo_frame.pack(pady=(20, 12))
        if LOGO_PATH.exists():
            try:
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(LOGO_PATH).convert("RGBA")
                    ratio = min(LOGO_MAX_WIDTH / img.width, 280 / img.height) if img.width and img.height else 1
                    if ratio < 1:
                        new_w = max(1, int(img.width * ratio))
                        new_h = max(1, int(img.height * ratio))
                        img = img.resize((new_w, new_h), Image.LANCZOS)
                    self._logo_photo = ImageTk.PhotoImage(img)
                except Exception:
                    self._logo_photo = tk.PhotoImage(file=str(LOGO_PATH))
                    w = self._logo_photo.width()
                    if w > LOGO_MAX_WIDTH:
                        factor = max(1, (w + LOGO_MAX_WIDTH - 1) // LOGO_MAX_WIDTH)
                        self._logo_photo = self._logo_photo.subsample(factor, factor)
                logo_label = tk.Label(logo_frame, image=self._logo_photo, bg="#f0f4f0")
                logo_label.pack()
            except Exception:
                tk.Label(logo_frame, text="AutoRadar", font=("Arial", 18, "bold"), bg="#f0f4f0").pack()
        else:
            tk.Label(logo_frame, text="AutoRadar", font=("Arial", 18, "bold"), bg="#f0f4f0").pack()

        self.status_label = tk.Label(self.root, text="Aguardando...", font=("Arial", 11), bg="#f0f4f0", fg="#333")
        self.status_label.pack(pady=10)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.root, variable=self.progress_var, maximum=100, length=600, mode='determinate'
        )
        self.progress_bar.pack(pady=10)

        self.percent_label = tk.Label(self.root, text="0%", font=("Arial", 10), bg="#f0f4f0", fg="#555")
        self.percent_label.pack()

        # Botões em 2 linhas para caber confortavelmente
        button_frame = tk.Frame(self.root, bg="#f0f4f0")
        button_frame.pack(pady=20, padx=12)
        row1 = tk.Frame(button_frame, bg="#f0f4f0")
        row1.pack(pady=(0, 8))
        if self.on_config_clicked:
            ttk.Button(row1, text="⚙️ Configurações", command=self._open_config).pack(side=tk.LEFT, padx=6)
        ttk.Button(row1, text="📄 Abrir relatório", command=self._open_report).pack(side=tk.LEFT, padx=6)
        ttk.Button(row1, text="📤 Reenviar anúncios", command=self._resend_telegram).pack(side=tk.LEFT, padx=6)
        row2 = tk.Frame(button_frame, bg="#f0f4f0")
        row2.pack()
        ttk.Button(row2, text="🔄 Reiniciar fluxo", command=self._on_restart_flow).pack(side=tk.LEFT, padx=6)
        ttk.Button(row2, text="🗑️ Limpar Cache", command=self.on_clear_cache).pack(side=tk.LEFT, padx=6)
        ttk.Button(row2, text="📊 Atualizar FIPE", command=self._on_update_fipe).pack(side=tk.LEFT, padx=6)

        self.countdown_label = tk.Label(self.root, text="", font=("Arial", 10), fg="gray", bg="#f0f4f0")
        self.countdown_label.pack(pady=6)

        self.fipe_info_label = tk.Label(self.root, text="", font=("Arial", 9), fg="#555", bg="#f0f4f0")
        self.fipe_info_label.pack(pady=2)
        self._refresh_fipe_info()
        
        self.telegram_info_label = tk.Label(self.root, text="", font=("Arial", 9), fg="#2196F3", bg="#f0f4f0")
        self.telegram_info_label.pack(pady=2)
        self._refresh_telegram_info()

        # Créditos com link para e-mail
        credits_frame = tk.Frame(self.root, bg="#f0f4f0")
        credits_frame.pack(side=tk.BOTTOM, pady=(8, 12))
        credits_label = tk.Label(
            credits_frame,
            text="Created by Igor Avelar — ",
            font=("Arial", 9),
            fg="#555",
            bg="#f0f4f0",
            cursor="hand2",
        )
        credits_label.pack(side=tk.LEFT)
        email_label = tk.Label(
            credits_frame,
            text="avelar.igor@gmail.com",
            font=("Arial", 9),
            fg="#2196F3",
            bg="#f0f4f0",
            cursor="hand2",
        )
        email_label.pack(side=tk.LEFT)
        email_label.bind("<Button-1>", lambda e: webbrowser.open("mailto:avelar.igor@gmail.com"))
        credits_label.bind("<Button-1>", lambda e: webbrowser.open("mailto:avelar.igor@gmail.com"))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)
        self.safe_after(200, self._setup_tray)
        _safe_update(self.root)

    def _open_config(self):
        if self.on_config_clicked:
            self.on_config_clicked()

    def _on_restart_flow(self):
        """Reinicia o fluxo: coleta → scan → consolidação → ranking (e Telegram se configurado)."""
        if self.on_restart_flow:
            self.on_restart_flow()

    def _refresh_fipe_info(self):
        """Atualiza o label com mês/ano de REFERÊNCIA dos preços FIPE (ex.: fev/2026), não a data do arquivo."""
        try:
            if not getattr(self, "fipe_info_label", None) or not self.fipe_info_label.winfo_exists():
                return
            cache_dir = BASE_DIR / "out" / "cache"
            last_update_file = cache_dir / "fipe_last_update.json"
            if not last_update_file.exists():
                self.fipe_info_label.config(text="Referência FIPE: não disponível (execute Atualizar FIPE)")
                return
            with open(last_update_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            ref_month = data.get("fipe_reference_month") or (data.get("reference_month") or "").strip()
            if ref_month:
                self.fipe_info_label.config(text="Referência FIPE: %s" % ref_month)
                return
            # Referência não foi gravada (arquivo antigo ou atualização sem API v2): explicar e mostrar data do arquivo
            last = data.get("last_update") or (data.get("iso") or "")[:10]
            if last:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(last[:10], "%Y-%m-%d")
                    self.fipe_info_label.config(
                        text="Referência FIPE: não informada (arquivo de %s). Use Atualizar FIPE para obter (ex.: fev/2026)."
                        % dt.strftime("%d/%m/%Y")
                    )
                except Exception:
                    self.fipe_info_label.config(text="Referência FIPE: não informada. Use Atualizar FIPE.")
            else:
                self.fipe_info_label.config(text="Referência FIPE: não informada. Use Atualizar FIPE.")
        except Exception:
            try:
                if getattr(self, "fipe_info_label", None) and self.fipe_info_label.winfo_exists():
                    self.fipe_info_label.config(text="")
            except Exception:
                pass

    def _refresh_telegram_info(self):
        """Atualiza o label com informações da última execução do Telegram."""
        try:
            last_exec_file = BASE_DIR / "last_telegram_execution.json"
            if last_exec_file.exists():
                try:
                    with open(last_exec_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    time_str = data.get("time", "")
                    sent_count = data.get("sent_count", 0)
                    if time_str and sent_count > 0:
                        self.telegram_info_label.config(
                            text=f"Última execução: {time_str} - {sent_count} anúncios enviados no Telegram"
                        )
                    elif time_str:
                        self.telegram_info_label.config(
                            text=f"Última execução: {time_str} - 0 anúncios enviados"
                        )
                    else:
                        self.telegram_info_label.config(text="")
                except Exception:
                    self.telegram_info_label.config(text="")
            else:
                self.telegram_info_label.config(text="")
        except Exception:
            try:
                if getattr(self, "telegram_info_label", None) and self.telegram_info_label.winfo_exists():
                    self.telegram_info_label.config(text="")
            except Exception:
                pass

    def _open_report(self):
        """Abre o relatório HTML (ranking de oportunidades) no navegador padrão."""
        report_path = BASE_DIR / "UI" / "index.html"
        if report_path.exists():
            try:
                webbrowser.open(f"file:///{report_path.absolute().as_posix()}")
            except Exception:
                messagebox.showwarning("AutoRadar", "Não foi possível abrir o relatório.")
        else:
            messagebox.showinfo("AutoRadar", "Relatório ainda não gerado.\nExecute o pipeline para gerar o ranking.")

    def _on_update_fipe(self):
        """Abre janela de progresso e roda atualização FIPE em thread; ao terminar mostra Concluído (não fecha sozinho)."""
        try:
            try:
                from path_utils import get_out_dir
                out_dir = get_out_dir()
            except Exception:
                out_dir = BASE_DIR / "out"
            cache_dir = out_dir / "cache"
            last_update = cache_dir / "fipe_last_update.json"
            if last_update.exists():
                last_update.unlink()
            self.update_status("Atualizando tabela FIPE...")
            _safe_update(self.root)

            win = tk.Toplevel(self.root)
            win.title("Atualização FIPE")
            win.geometry("420x180")
            win.resizable(False, False)
            win.configure(bg="#f0f4f0")
            if ICON_PATH.exists():
                try:
                    win.iconbitmap(str(ICON_PATH))
                except Exception:
                    pass
            tk.Label(win, text="Atualizando tabela FIPE...", font=("Arial", 11, "bold"), bg="#f0f4f0").pack(pady=(14, 8))
            progress_var = tk.DoubleVar(value=0)
            progress_bar = ttk.Progressbar(win, variable=progress_var, maximum=100, length=380, mode="determinate")
            progress_bar.pack(pady=6)
            step_label = tk.Label(win, text="0/0", font=("Arial", 10), bg="#f0f4f0", fg="#333")
            step_label.pack(pady=2)
            status_label = tk.Label(win, text="", font=("Arial", 9), bg="#f0f4f0", fg="#555")
            status_label.pack(pady=2)
            btn_frame = tk.Frame(win, bg="#f0f4f0")
            btn_frame.pack(pady=(12, 14))
            close_btn = ttk.Button(btn_frame, text="Fechar", state=tk.DISABLED, command=win.destroy)
            close_btn.pack()

            def update_progress(current, total, message):
                try:
                    if not win.winfo_exists():
                        return
                    if total and total > 0:
                        pct = min(100.0, 100 * current / total)
                        progress_var.set(pct)
                        step_label.config(text="%d / %d (%.0f%%)" % (current, total, pct))
                    status_label.config(text=(message or "Aguardando...").strip()[:80])
                    _safe_update(win)
                except (tk.TclError, Exception):
                    pass

            def show_done(ok, err_msg=None):
                try:
                    if not win.winfo_exists():
                        return
                    progress_var.set(100)
                    step_label.config(text="Concluído (100%)")
                    status_label.config(text="Atualização concluída com sucesso." if ok else ("Erro: " + (err_msg or "erro desconhecido")))
                    close_btn.config(state=tk.NORMAL)
                    _safe_update(win)
                except (tk.TclError, Exception):
                    pass

            def run():
                result, err = True, None
                try:
                    import fipe_download
                    fipe_download.main(
                        progress_callback=lambda c, t, m: self.root.after(0, lambda: update_progress(c, t, m)),
                        tipos=["carros", "motos", "caminhoes"],
                        no_resume=False,
                    )
                except Exception as e:
                    result, err = False, str(e)
                try:
                    self.root.after(0, lambda: show_done(result, err))
                except Exception:
                    pass
                try:
                    self.root.after(0, lambda: self._fipe_update_done(result, err))
                except Exception:
                    pass

            import threading
            threading.Thread(target=run, daemon=True).start()
        except Exception as e:
            messagebox.showerror("AutoRadar", "Erro ao iniciar atualização FIPE: %s" % e)

    def _fipe_update_done(self, ok, err_msg=None):
        try:
            self.update_status("Aguardando...")
            if ok:
                pass  # Janela de progresso já mostra "Concluído"
            else:
                messagebox.showerror("AutoRadar", "Erro ao atualizar FIPE: %s" % (err_msg or "erro desconhecido"))
        except Exception:
            pass
        if ok:
            self._refresh_fipe_info()

    def _resend_telegram(self):
        """Reenvia os anúncios do último ranking para o Telegram."""
        last_file = BASE_DIR / "out" / "last_ranking_for_telegram.json"
        if not last_file.exists():
            messagebox.showinfo("AutoRadar", "Nenhum ranking salvo para reenvio.\nExecute o pipeline primeiro.")
            return
        try:
            with open(last_file, "r", encoding="utf-8") as f:
                ranking = json.load(f)
        except Exception:
            messagebox.showwarning("AutoRadar", "Erro ao ler último ranking.")
            return
        if not ranking:
            messagebox.showinfo("AutoRadar", "Último ranking está vazio.")
            return
        try:
            from send_telegram import load_config, send_opportunities
            if not load_config():
                messagebox.showwarning("AutoRadar", "Configure telegram_config.json para enviar.")
                return
            self.update_status("Reenviando para o Telegram...")
            _safe_update(self.root)
            n = send_opportunities(ranking)
            self.update_status("Aguardando...")
            messagebox.showinfo("AutoRadar", f"Reenviados {n} anúncios para o Telegram.")
        except Exception as e:
            messagebox.showerror("AutoRadar", "Erro ao reenviar: %s" % e)
            self.update_status("Aguardando...")

    def _do_update_status(self, status):
        try:
            if self.root.winfo_exists() and self.status_label.winfo_exists():
                self.status_label.config(text=str(status))
                _safe_update(self.root)
        except (tk.TclError, Exception):
            pass

    def update_status(self, status):
        """Atualiza o texto de status. Thread-safe: se chamado de outra thread, agenda na main."""
        if _is_main_thread():
            self._do_update_status(status)
        else:
            try:
                self.safe_after(0, lambda s=status: self._do_update_status(s))
            except (tk.TclError, Exception):
                pass

    def _do_update_progress(self, current, total):
        try:
            if not self.root.winfo_exists():
                return
            if total > 0:
                percent = (current / total) * 100
                self.progress_var.set(percent)
                if self.percent_label.winfo_exists():
                    self.percent_label.config(text=f"{percent:.1f}%")
            else:
                self.progress_var.set(0)
                if self.percent_label.winfo_exists():
                    self.percent_label.config(text="0%")
            _safe_update(self.root)
        except (tk.TclError, Exception):
            pass

    def update_progress(self, current, total):
        """Atualiza a barra de progresso. Thread-safe: se chamado de outra thread, agenda na main."""
        if _is_main_thread():
            self._do_update_progress(current, total)
        else:
            try:
                self.safe_after(0, lambda c=current, t=total: self._do_update_progress(c, t))
            except (tk.TclError, Exception):
                pass

    def safe_after(self, ms, func):
        """Agenda um evento after() e armazena o ID para cancelamento no fechamento. Callback é executado em try/except para evitar TclError quando a janela já foi destruída."""
        if self._closing:
            return None
        def _run():
            try:
                func()
            except (tk.TclError, Exception):
                pass
        try:
            after_id = self.root.after(ms, _run)
            if after_id:
                self._after_ids.append(after_id)
            return after_id
        except Exception:
            return None

    def update_countdown(self, text):
        """Atualiza o texto da contagem regressiva. Thread-safe."""
        def do_it(t):
            try:
                if getattr(self, "countdown_label", None) and self.countdown_label.winfo_exists():
                    self.countdown_label.config(text=str(t))
                    _safe_update(self.root)
            except (tk.TclError, Exception):
                pass
        if _is_main_thread():
            do_it(text)
        else:
            try:
                self.safe_after(0, lambda t=text: do_it(t))
            except Exception:
                pass

    def on_clear_cache(self):
        """Limpa o cache de anúncios (não apaga user_preferences nem fipe_db_norm)."""
        removed = 0
        try:
            for name in ["links.txt", "seen_links.json"]:
                p = BASE_DIR / name
                if p.exists():
                    p.unlink()
                    removed += 1

            out_dir = BASE_DIR / "out"
            if out_dir.exists():
                for f in out_dir.glob("listings_*.json"):
                    f.unlink()
                    removed += 1
                fipe_clean = out_dir / "listings_all_clean.json"
                if fipe_clean.exists():
                    fipe_clean.unlink()
                    removed += 1
                fb = out_dir / "listings_facebook.json"
                if fb.exists():
                    fb.unlink()
                    removed += 1

            ui_data = BASE_DIR / "UI" / "data.js"
            if ui_data.exists():
                ui_data.unlink()
                removed += 1

            cache_dir = BASE_DIR / "cache_listing"
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
                removed += 1

            self.update_status(f"✅ Cache limpo! ({removed} itens removidos)")
        except Exception as e:
            self.update_status(f"❌ Erro ao limpar cache: {e}")

    def prompt_before_browser(self):
        """Aviso antes de abrir o navegador: bloqueia até o usuário clicar em OK."""
        try:
            _safe_update(self.root)
            self.root.update_idletasks()
            messagebox.showinfo(
                "AutoRadar",
                "O navegador Chromium será aberto em instantes.\n\n"
                "Se não estiver logado, faça login no Facebook na janela do navegador.\n"
                "Clique em OK para abrir o navegador."
            )
            _safe_update(self.root)
        except (tk.TclError, Exception):
            pass

    def wait_for_login(self):
        """Após o navegador abrir: bloqueia até o usuário clicar em OK para iniciar a coleta."""
        try:
            _safe_update(self.root)
            self.root.update_idletasks()
            messagebox.showinfo(
                "AutoRadar - Coleta",
                "O navegador foi aberto.\n\n"
                "Faça login no Facebook se necessário e deixe o Marketplace carregar.\n\n"
                "Clique em OK para iniciar a coleta de links."
            )
            _safe_update(self.root)
        except (tk.TclError, Exception):
            pass

    def show(self):
        _safe_update(self.root)

    def _on_close_window(self):
        """Fechar: cancela eventos agendados, fecha Ollama (se iniciado por nós), fecha tray e força saída do processo."""
        self._closing = True
        # Cancelar todos os eventos after() agendados
        try:
            for after_id in self._after_ids[:]:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
            self._after_ids.clear()
        except Exception:
            pass
        # Fechar Ollama se foi iniciado pelo app
        try:
            from ai_fipe_helper import stop_ollama_if_started_by_us
            stop_ollama_if_started_by_us()
        except Exception:
            pass
        # Parar tray icon
        if getattr(self, "_tray_icon", None) is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        # Fechar janela
        try:
            if self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except Exception:
            pass
        # Forçar saída do processo imediatamente (os._exit termina todas as threads)
        import os
        import sys
        try:
            # Tentar saída normal primeiro
            sys.exit(0)
        except Exception:
            pass
        # Se sys.exit não funcionar, forçar com os._exit (termina tudo, inclusive threads daemon)
        os._exit(0)

    def _show_from_tray(self):
        """Restaura a janela ao clicar no ícone da bandeja."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _setup_tray(self):
        """Configura ícone na bandeja do sistema (minimizar para tray)."""
        if not ICON_PATH.exists():
            return
        try:
            import pystray
            from PIL import Image
            img = Image.open(ICON_PATH)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem("Abrir AutoRadar", self._show_from_tray, default=True),
                pystray.MenuItem("Sair", lambda: self.close()),
            )
            self._tray_icon = pystray.Icon("AutoRadar", img, "AutoRadar", menu)
            self.safe_after(500, self._run_tray)
        except ImportError:
            self._tray_icon = None
        except Exception:
            self._tray_icon = None

    def _run_tray(self):
        """Executa o ícone da bandeja em thread separada."""
        if getattr(self, "_tray_icon", None) is None:
            return
        try:
            import threading
            def run():
                try:
                    self._tray_icon.run()
                except Exception:
                    pass
            t = threading.Thread(target=run, daemon=True)
            t.start()
        except Exception:
            pass

    def schedule_close_after(self, seconds):
        """Fecha a janela após N segundos de inatividade."""
        self._close_scheduled = True
        try:
            if self.root.winfo_exists():
                self.safe_after(seconds * 1000, self.close)
        except Exception:
            pass

    def close(self):
        """Fecha a janela e força saída do processo."""
        self._closing = True
        try:
            # Cancelar eventos agendados
            for after_id in self._after_ids[:]:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
            self._after_ids.clear()
            # Fechar Ollama se foi iniciado pelo app
            try:
                from ai_fipe_helper import stop_ollama_if_started_by_us
                stop_ollama_if_started_by_us()
            except Exception:
                pass
            # Parar tray
            if getattr(self, "_tray_icon", None) is not None:
                try:
                    self._tray_icon.stop()
                except Exception:
                    pass
            # Fechar janela
            if self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except Exception:
            pass
        # Forçar saída do processo imediatamente (os._exit termina todas as threads)
        import os
        import sys
        try:
            # Tentar saída normal primeiro
            sys.exit(0)
        except Exception:
            pass
        # Se sys.exit não funcionar, forçar com os._exit (termina tudo, inclusive threads daemon)
        os._exit(0)
