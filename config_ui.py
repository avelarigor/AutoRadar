#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interface de Configuração - AutoRadar
Localização: usa a do Facebook. Preço, margem em R$, palavras a evitar (golpe).
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "autoradar_icon.ico"

# UFs e cidades em padrão compatível com o Facebook Marketplace (evita erros de digitação)
UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO")
CIDADES = (
    "Montes Claros", "Belo Horizonte", "Uberlândia", "Contagem", "Juiz de Fora", "Betim", "Ribeirão das Neves",
    "Santa Luzia", "Ibirité", "Sabará", "Governador Valadares", "Poços de Caldas", "Patos de Minas", "Pouso Alegre",
    "São Paulo", "Guarulhos", "Campinas", "São Bernardo do Campo", "Santo André", "Osasco", "Ribeirão Preto",
    "Sorocaba", "Santos", "São José dos Campos", "Mauá", "Diadema", "Carapicuíba", "Piracicaba", "Bauru",
    "Rio de Janeiro", "Niterói", "Nova Iguaçu", "Duque de Caxias", "São Gonçalo", "Belford Roxo", "Campos dos Goytacazes",
    "Curitiba", "Londrina", "Maringá", "Ponta Grossa", "Cascavel", "Foz do Iguaçu", "Colombo",
    "Porto Alegre", "Caxias do Sul", "Pelotas", "Canoas", "Santa Maria", "Gravataí", "Novo Hamburgo",
    "Salvador", "Feira de Santana", "Vitória da Conquista", "Camaçari", "Itabuna", "Juazeiro", "Lauro de Freitas",
    "Fortaleza", "Caucaia", "Juazeiro do Norte", "Maracanaú", "Sobral", "Crato", "Itapipoca",
    "Recife", "Jaboatão dos Guararapes", "Olinda", "Caruaru", "Petrolina", "Paulista", "Cabo de Santo Agostinho",
    "Brasília", "Taguatinga", "Ceilândia", "Samambaia", "Planaltina", "Gama", "Águas Claras",
    "Goiânia", "Aparecida de Goiânia", "Anápolis", "Rio Verde", "Luziânia", "Águas Lindas de Goiás",
    "Belém", "Ananindeua", "Santarém", "Marabá", "Castanhal", "Parauapebas", "Cametá",
    "Manaus", "Parintins", "Itacoatiara", "Manacapuru", "Coari", "Tefé",
    "Campo Grande", "Dourados", "Três Lagoas", "Corumbá", "Ponta Porã", "Sidrolândia",
    "Cuiabá", "Várzea Grande", "Rondonópolis", "Sinop", "Tangará da Serra", "Cáceres",
    "Florianópolis", "Joinville", "Blumenau", "Itajaí", "São José", "Criciúma", "Chapecó", "Jaraguá do Sul",
    "Vitória", "Vila Velha", "Serra", "Cariacica", "Viana", "Linhares", "São Mateus",
    "Aracaju", "Nossa Senhora do Socorro", "Lagarto", "Itabaiana", "Estância", "Tobias Barreto",
    "Maceió", "Arapiraca", "Palmeira dos Índios", "Rio Largo", "Penedo", "União dos Palmares",
    "Natal", "Mossoró", "Parnamirim", "São Gonçalo do Amarante", "Macaíba", "Ceará-Mirim",
    "João Pessoa", "Campina Grande", "Santa Rita", "Patos", "Bayeux", "Cabedelo", "Sousa",
    "Teresina", "Parnaíba", "Picos", "Piripiri", "Floriano", "Campo Maior", "Barras",
    "São Luís", "Imperatriz", "Caxias", "Codó", "Paço do Lumiar", "Timon", "Bacabal",
    "Macapá", "Rio Branco", "Boa Vista", "Palmas", "Porto Velho",
)


def _fmt_thousands(s):
    """Formata número com separador de milhar (ex.: 20000 -> 20.000)."""
    if not s:
        return s
    digits = "".join(c for c in str(s) if c in "0123456789")
    if not digits:
        return s
    n = int(digits)
    return f"{n:,}".replace(",", ".")


def _parse_thousands(s):
    """Remove separador de milhar e retorna string numérica (ex.: 20.000 -> 20000)."""
    if not s:
        return "0"
    return (str(s).replace(".", "").replace(",", "").strip() or "0")


def _log(msg, level="info"):
    try:
        from log_config import get_logger
        get_logger().info(f"[Config] {msg}")
    except Exception:
        pass


class ConfigWindow:
    """Janela de configuração do AutoRadar"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AutoRadar - Configurações")
        self.root.geometry("720x680")
        self.root.resizable(True, True)
        if ICON_PATH.exists():
            try:
                self.root.iconbitmap(str(ICON_PATH))
            except Exception:
                pass

        self.result = None
        self.preferences = self.load_preferences()
        self.create_widgets()
        _log("Janela de configuração aberta")

    def load_preferences(self):
        prefs_file = BASE_DIR / "user_preferences.json"
        if prefs_file.exists():
            try:
                with open(prefs_file, 'r', encoding='utf-8') as f:
                    prefs = json.load(f)
                # #region agent log
                try:
                    import time as _t
                    with open(r"c:\Projects\.cursor\debug.log", "a", encoding="utf-8") as _f:
                        _f.write(json.dumps({"location": "config_ui:load_preferences", "message": "prefs_from_file", "data": {"city": prefs.get("city"), "state": prefs.get("state")}, "hypothesisId": "H2", "timestamp": _t.time() * 1000}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                return prefs
            except Exception:
                pass
        default = {
            "city": "Montes Claros",
            "state": "MG",
            "price_min": 20000,
            "price_max": 100000,
            "margin_min_reais": 5000,
            "vehicle_types": {"car": True, "motorcycle": True, "truck": True},
            "keywords_avoid": []
        }
        return default

    def _margin_from_prefs(self):
        """Compatível com arquivo antigo (margin_min em %) ou novo (margin_min_reais)."""
        if "margin_min_reais" in self.preferences:
            return self.preferences["margin_min_reais"]
        # Antigo: margin_min era %; usar valor padrão em R$
        return 5000

    def load_keywords(self):
        keywords_file = BASE_DIR / "keywords_golpe.txt"
        if keywords_file.exists():
            try:
                with open(keywords_file, 'r', encoding='utf-8') as f:
                    return [line.strip() for line in f if line.strip()]
            except Exception:
                pass
        return []

    def save_keywords(self, keywords_text):
        keywords_file = BASE_DIR / "keywords_golpe.txt"
        try:
            with open(keywords_file, 'w', encoding='utf-8') as f:
                f.write(keywords_text)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar palavras: {e}")

    def create_widgets(self):
        title = tk.Label(self.root, text="⚙️ Configurações do AutoRadar", font=("Arial", 16, "bold"))
        title.pack(pady=10)

        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Localização: cidade e estado para a busca no Marketplace (obrigatório para anúncios na sua região, em R$)
        loc_frame = ttk.LabelFrame(main_frame, text="Localização (cidade da busca no Facebook Marketplace)", padding=8)
        loc_frame.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))
        ttk.Label(
            loc_frame,
            text="Informe a cidade e o estado em que deseja buscar. A busca usará essa localização na URL.",
            font=("Arial", 9)
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 6))
        row_loc = 1
        ttk.Label(loc_frame, text="Estado (UF):").grid(row=row_loc, column=0, sticky=tk.W, padx=(0, 5), pady=2)
        self.state_var = tk.StringVar(value=self.preferences.get("state", ""))
        self.state_cb = ttk.Combobox(loc_frame, textvariable=self.state_var, values=UFS, width=6, state="readonly")
        self.state_cb.grid(row=row_loc, column=1, sticky=tk.W, pady=2)
        row_loc += 1
        ttk.Label(loc_frame, text="Cidade:").grid(row=row_loc, column=0, sticky=tk.W, padx=(0, 5), pady=2)
        self.city_var = tk.StringVar(value=self.preferences.get("city", ""))
        self.city_cb = ttk.Combobox(loc_frame, textvariable=self.city_var, values=sorted(set(CIDADES)), width=28)
        self.city_cb.grid(row=row_loc, column=1, sticky=tk.EW, pady=2)
        loc_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(1, weight=1)

        row = 1
        ttk.Label(main_frame, text="Preço Mínimo (R$):").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.price_min_var = tk.StringVar(value=_fmt_thousands(self.preferences.get("price_min", 20000)))
        price_min_entry = ttk.Entry(main_frame, textvariable=self.price_min_var, width=18)
        price_min_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        price_min_entry.bind("<FocusOut>", lambda e: self.price_min_var.set(_fmt_thousands(self.price_min_var.get())))
        row += 1

        ttk.Label(main_frame, text="Preço Máximo (R$):").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.price_max_var = tk.StringVar(value=_fmt_thousands(self.preferences.get("price_max", 100000)))
        price_max_entry = ttk.Entry(main_frame, textvariable=self.price_max_var, width=18)
        price_max_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        price_max_entry.bind("<FocusOut>", lambda e: self.price_max_var.set(_fmt_thousands(self.price_max_var.get())))
        row += 1

        ttk.Label(main_frame, text="Margem Mínima (R$):").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.margin_reais_var = tk.StringVar(value=_fmt_thousands(self._margin_from_prefs()))
        margin_entry = ttk.Entry(main_frame, textvariable=self.margin_reais_var, width=18)
        margin_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        margin_entry.bind("<FocusOut>", lambda e: self.margin_reais_var.set(_fmt_thousands(self.margin_reais_var.get())))
        ttk.Label(main_frame, text="Diferença mínima em reais (FIPE - Preço). Ex: 5000 = R$ 5.000", font=("Arial", 9), foreground="gray").grid(row=row+1, column=1, sticky=tk.W)
        row += 2

        # Tipos de veículo (Carro, Moto, Caminhões) — filtro no escaneamento (se não marcar, ignora na coleta)
        vt = self.preferences.get("vehicle_types") or {"car": True, "motorcycle": True, "truck": True}
        type_frame = ttk.LabelFrame(main_frame, text="Tipos de veículo a escanear", padding=6)
        type_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))
        self.vehicle_car_var = tk.BooleanVar(value=vt.get("car", True))
        self.vehicle_moto_var = tk.BooleanVar(value=vt.get("motorcycle", True))
        self.vehicle_truck_var = tk.BooleanVar(value=vt.get("truck", True))
        ttk.Checkbutton(type_frame, text="Carro", variable=self.vehicle_car_var).pack(anchor=tk.W)
        ttk.Checkbutton(type_frame, text="Moto", variable=self.vehicle_moto_var).pack(anchor=tk.W)
        ttk.Checkbutton(type_frame, text="Caminhões", variable=self.vehicle_truck_var).pack(anchor=tk.W)
        row += 1

        ttk.Label(main_frame, text="Palavras a evitar (golpe, sinistro, etc.):").grid(row=row, column=0, sticky=tk.NW, pady=5)
        keywords_frame = ttk.Frame(main_frame)
        keywords_frame.grid(row=row, column=1, pady=5, sticky=tk.NSEW)
        keywords_scroll = ttk.Scrollbar(keywords_frame)
        self.keywords_text = tk.Text(keywords_frame, width=48, height=18, wrap=tk.WORD, yscrollcommand=keywords_scroll.set)
        keywords_scroll.config(command=self.keywords_text.yview)
        self.keywords_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        keywords_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        keywords = self.load_keywords()
        self.keywords_text.insert("1.0", "\n".join(keywords))
        main_frame.rowconfigure(row, weight=1)
        row += 1

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=20)
        ttk.Button(button_frame, text="✅ Salvar e Continuar", command=self.on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="❌ Cancelar", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

    def on_save(self):
        try:
            price_min = int(_parse_thousands(self.price_min_var.get()))
            price_max = int(_parse_thousands(self.price_max_var.get()))
            margin_reais = int(_parse_thousands(self.margin_reais_var.get()))
            if price_min >= price_max:
                messagebox.showerror("Erro", "Preço mínimo deve ser menor que preço máximo")
                return
            if margin_reais < 0:
                messagebox.showerror("Erro", "Margem mínima (R$) deve ser >= 0")
                return
            keywords_text = self.keywords_text.get("1.0", tk.END).strip()
            self.save_keywords(keywords_text)
            keywords_list = [k.strip() for k in keywords_text.split("\n") if k.strip()]
            # Ler do widget (Combobox com state="readonly" nem sempre atualiza o StringVar ao selecionar)
            city = (self.city_cb.get() or self.city_var.get() or "").strip()
            state = (self.state_cb.get() or self.state_var.get() or "").strip()
            if not city or not state:
                messagebox.showerror("Erro", "Informe Cidade e Estado (UF) para que a busca seja feita na sua região (anúncios em R$).")
                return
            self.result = {
                **self.preferences,
                "city": city,
                "state": state,
                "price_min": price_min,
                "price_max": price_max,
                "margin_min_reais": margin_reais,
                "vehicle_types": {
                    "car": self.vehicle_car_var.get(),
                    "motorcycle": self.vehicle_moto_var.get(),
                    "truck": self.vehicle_truck_var.get()
                },
                "keywords_avoid": keywords_list,
            }
            _log("Configurações salvas")
            self.root.quit()
        except ValueError as e:
            messagebox.showerror("Erro", f"Valor inválido: {e}")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar: {e}")

    def on_cancel(self):
        self.result = None
        _log("Configuração cancelada")
        self.root.quit()

    def run(self):
        self.root.mainloop()
        self.root.destroy()
        return self.result
