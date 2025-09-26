# sensibilidade_h2verde.py
# Rotinas de análise de sensibilidade para o módulo h2verde_tea.py
# - Sensibilidade 1D (um parâmetro)
# - Sensibilidade 2D (dois parâmetros)
# - Dados para gráfico Tornado (baixa vs alta por parâmetro)
# - Dados “aranha/spider” (curvas de LCOH vs valor para vários parâmetros)
# - Monte Carlo (opcional) para distribuição de LCOH
#
# Requer: h2verde_tea.py no PYTHONPATH (mesma pasta) com:
#   CenarioEntrada, simular

from typing import List, Dict, Any, Tuple, Callable, Optional
import copy
import random

from h2verde_tea import CenarioEntrada, simular


# ==============================
# ==== Helpers de Navegação ====
# ==============================

def _get_attr_dotted(obj: Any, dotted: str) -> Any:
    """
    Retorna o valor de um caminho pontilhado em dataclasses aninhadas.
    Ex.: "energia.preco_mwh"
    """
    cur = obj
    for part in dotted.split("."):
        cur = getattr(cur, part)
    return cur


def _set_attr_dotted(obj: Any, dotted: str, value: Any) -> None:
    """
    Define o valor de um caminho pontilhado em dataclasses aninhadas.
    """
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = getattr(cur, p)
    setattr(cur, parts[-1], value)


def _clone_cenario(c: CenarioEntrada) -> CenarioEntrada:
    return copy.deepcopy(c)


# =========================================
# ==== Sensibilidade 1D (um parâmetro) ====
# =========================================

def sensibilidade_1d(
    cenario_base: CenarioEntrada,
    parametro: str,
    valores: List[float]
) -> List[Dict[str, float]]:
    """
    Varre 'valores' no parâmetro 'parametro' (caminho pontilhado) e retorna:
    [
      {"valor": x, "lcoh": L_x, "h2_anual_kg": H_x},
      ...
    ]
    """
    resultados = []
    for v in valores:
        c = _clone_cenario(cenario_base)
        _set_attr_dotted(c, parametro, v)
        out = simular(c)
        resultados.append({
            "valor": v,
            "lcoh": out["lcoh"],
            "h2_anual_kg": out["h2_anual_kg"]
        })
    return resultados


# =========================================
# ==== Sensibilidade 2D (dois parâmetros) =
# =========================================

def sensibilidade_2d(
    cenario_base: CenarioEntrada,
    param_x: str,
    valores_x: List[float],
    param_y: str,
    valores_y: List[float]
) -> Dict[str, Any]:
    """
    Gera uma malha X x Y retornando LCOH para cada combinação.
    Retorno:
    {
      "param_x": "energia.preco_mwh",
      "param_y": "capex.eletrolisador_capex_por_kw",
      "grid": [
         {"x": vx, "y": vy, "lcoh": L_xy} ... em ordem de loops (x externo, y interno)
      ]
    }
    """
    grid = []
    for vx in valores_x:
        for vy in valores_y:
            c = _clone_cenario(cenario_base)
            _set_attr_dotted(c, param_x, vx)
            _set_attr_dotted(c, param_y, vy)
            out = simular(c)
            grid.append({"x": vx, "y": vy, "lcoh": out["lcoh"]})
    return {"param_x": param_x, "param_y": param_y, "grid": grid}


# ============================================
# ==== Tornado (impactos baixa x alta) =======
# ============================================

def tornado_lcoh(
    cenario_base: CenarioEntrada,
    parametros: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Calcula dados para gráfico tornado.
    'parametros' é uma lista de dicionários com:
      {
        "nome": "Preço Energia",
        "path": "energia.preco_mwh",
        "baixo": 250.0,
        "alto": 450.0
      }

    Retorna lista ordenada pelo impacto absoluto (|delta|) decrescente:
      [
        {
          "nome": ...,
          "path": ...,
          "valor_baixo": ...,
          "lcoh_baixo": ...,
          "valor_alto": ...,
          "lcoh_alto": ...,
          "delta": lcoh_alto - lcoh_baixo
        }, ...
      ]
    """
    resultados = []

    # LCOH de referência (sem alterar nada)
    base_out = simular(cenario_base)
    lcoh_ref = base_out["lcoh"]

    for p in parametros:
        nome = p["nome"]
        path = p["path"]
        v_lo = p["baixo"]
        v_hi = p["alto"]

        c_lo = _clone_cenario(cenario_base)
        _set_attr_dotted(c_lo, path, v_lo)
        out_lo = simular(c_lo)
        l_lo = out_lo["lcoh"]

        c_hi = _clone_cenario(cenario_base)
        _set_attr_dotted(c_hi, path, v_hi)
        out_hi = simular(c_hi)
        l_hi = out_hi["lcoh"]

        resultados.append({
            "nome": nome,
            "path": path,
            "lcoh_referencia": lcoh_ref,
            "valor_baixo": v_lo,
            "lcoh_baixo": l_lo,
            "valor_alto": v_hi,
            "lcoh_alto": l_hi,
            "delta": l_hi - l_lo,
            "impacto_abs": abs(l_hi - l_lo),
        })

    # Ordena por impacto absoluto decrescente
    resultados.sort(key=lambda x: x["impacto_abs"], reverse=True)
    return resultados


# ==================================================
# ==== Spider/aranha (várias curvas 1D juntas) =====
# ==================================================

def spider_multivariavel(
    cenario_base: CenarioEntrada,
    definicoes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Gera curvas de LCOH vs valor para vários parâmetros.
    'definicoes' é uma lista:
      {
        "nome": "Preço Energia",
        "path": "energia.preco_mwh",
        "valores": [200, 250, 300, 350, 400, 450]
      }

    Retorna:
    {
      "series": [
        {"nome": ..., "path": ..., "pontos": [{"valor": v, "lcoh": L, "h2_anual_kg": H}, ...]},
        ...
      ]
    }
    """
    series = []
    for d in definicoes:
        nome = d["nome"]
        path = d["path"]
        valores = d["valores"]
        pontos = sensibilidade_1d(cenario_base, path, valores)
        series.append({"nome": nome, "path": path, "pontos": pontos})
    return {"series": series}


# ==========================================
# ==== Varredura linear utilitária =========
# ==========================================

def varredura_linear(inicio: float, fim: float, n: int) -> List[float]:
    """
    Gera n valores igualmente espaçados entre 'inicio' e 'fim' (inclusive).
    """
    if n <= 1:
        return [inicio]
    passo = (fim - inicio) / (n - 1)
    return [inicio + i * passo for i in range(n)]


# ==========================================
# ==== Monte Carlo (opcional) ==============
# ==========================================

def monte_carlo_lcoh(
    cenario_base: CenarioEntrada,
    distribuicoes: List[Dict[str, Any]],
    n_amostras: int = 1000,
    semente: Optional[int] = None
) -> Dict[str, Any]:
    """
    Executa Monte Carlo para LCOH.
    'distribuicoes' é uma lista de dicionários com:
      {
        "path": "energia.preco_mwh",
        "tipo": "normal" | "uniforme",
        # para normal:
        "media": 350.0,
        "desvio": 50.0,
        # para uniforme:
        "min": 250.0,
        "max": 450.0
      }

    Retorna:
    {
      "n": ...,
      "lcoh": {
        "amostras": [...],
        "min": ...,
        "max": ...,
        "media": ...,
        "p5": ...,
        "p50": ...,
        "p95": ...
      }
    }
    """
    if semente is not None:
        random.seed(semente)

    lcohs = []

    for _ in range(n_amostras):
        c = _clone_cenario(cenario_base)

        # Sorteia conforme as distribuições
        for d in distribuicoes:
            path = d["path"]
            tipo = d.get("tipo", "uniforme").lower()

            if tipo == "normal":
                mu = d["media"]
                sd = d["desvio"]
                val = random.gauss(mu, sd)
                # opcional: truncar a valores fisicamente plausíveis, se quiser
            elif tipo == "uniforme":
                vmin = d["min"]
                vmax = d["max"]
                val = random.uniform(vmin, vmax)
            else:
                raise ValueError(f"Tipo de distribuição não suportado: {tipo}")

            _set_attr_dotted(c, path, val)

        out = simular(c)
        lcohs.append(out["lcoh"])

    # Estatísticas simples
    lcohs_sorted = sorted(lcohs)
    n = len(lcohs_sorted)

    def _pct(p: float) -> float:
        if n == 0:
            return float("nan")
        k = (n - 1) * (p / 100.0)
        f = int(k)
        cidx = min(f + 1, n - 1)
        frac = k - f
        return lcohs_sorted[f] * (1 - frac) + lcohs_sorted[cidx] * frac

    resumo = {
        "amostras": lcohs,
        "min": lcohs_sorted[0] if n else float("nan"),
        "max": lcohs_sorted[-1] if n else float("nan"),
        "media": sum(lcohs_sorted) / n if n else float("nan"),
        "p5": _pct(5),
        "p50": _pct(50),
        "p95": _pct(95),
    }

    return {"n": n, "lcoh": resumo}


# ==========================================
# ==== Exemplo de uso (CLI) ================
# ==========================================

if __name__ == "__main__":
    base = CenarioEntrada()

    # 1) Sensibilidade 1D — preço de energia
    valores_energia = varredura_linear(200, 500, 7)
    s1d = sensibilidade_1d(base, "energia.preco_mwh", valores_energia)
    print("\nSensibilidade 1D (energia.preco_mwh):")
    for p in s1d:
        print(p)

    # 2) Sensibilidade 2D — preço de energia x CAPEX eletrolisador
    vals_x = varredura_linear(200, 500, 4)
    vals_y = varredura_linear(500, 900, 5)
    s2d = sensibilidade_2d(base, "energia.preco_mwh", vals_x, "capex.eletrolisador_capex_por_kw", vals_y)
    print("\nSensibilidade 2D (energia.preco_mwh x capex.eletrolisador_capex_por_kw):")
    print(f"Total de pontos: {len(s2d['grid'])}")

    # 3) Tornado — principais variáveis (exemplo)
    params_tornado = [
        {"nome": "Preço de Energia", "path": "energia.preco_mwh", "baixo": 250, "alto": 450},
        {"nome": "CAPEX Eletrolisador (R$/kW)", "path": "capex.eletrolisador_capex_por_kw", "baixo": 500, "alto": 900},
        {"nome": "WACC Real", "path": "financiamento.wacc_real", "baixo": 0.07, "alto": 0.14},
        {"nome": "SEC (kWh/kg)", "path": "eletrolisador.sec_kwh_por_kg", "baixo": 48, "alto": 58},
        {"nome": "Energia Compressão (kWh/kg)", "path": "cae.energia_compressao_kwh_por_kg", "baixo": 1.8, "alto": 3.2},
        {"nome": "CF Anual", "path": "fator_capacidade_anual", "baixo": 0.65, "alto": 0.95},
        {"nome": "O&M Fixo (%CAPEX/ano)", "path": "bop.om_fixo_pct_capex_ano", "baixo": 0.02, "alto": 0.05},
        {"nome": "Água (R$/m3)", "path": "agua.custo_agua_m3", "baixo": 3.0, "alto": 12.0},
    ]
    tornado = tornado_lcoh(base, params_tornado)
    print("\nTornado (ordenado por impacto absoluto):")
    for t in tornado:
        print({k: t[k] for k in ["nome", "valor_baixo", "lcoh_baixo", "valor_alto", "lcoh_alto", "delta"]})

    # 4) Spider — múltiplos parâmetros em paralelo
    spider = spider_multivariavel(base, [
        {"nome": "Preço Energia", "path": "energia.preco_mwh", "valores": [200, 250, 300, 350, 400, 450, 500]},
        {"nome": "SEC Eletrolisador", "path": "eletrolisador.sec_kwh_por_kg", "valores": [48, 50, 52, 54, 56, 58]},
        {"nome": "CAPEX/kW", "path": "capex.eletrolisador_capex_por_kw", "valores": [500, 600, 700, 800, 900]},
    ])
    print("\nSpider (series):")
    for serie in spider["series"]:
        print(serie["nome"], "->", len(serie["pontos"]), "pontos")

    # 5) Monte Carlo — exemplo com 3 distribuições
    mc = monte_carlo_lcoh(
        base,
        distribuicoes=[
            {"path": "energia.preco_mwh", "tipo": "normal", "media": 350.0, "desvio": 60.0},
            {"path": "capex.eletrolisador_capex_por_kw", "tipo": "uniforme", "min": 550.0, "max": 900.0},
            {"path": "eletrolisador.sec_kwh_por_kg", "tipo": "normal", "media": 52.0, "desvio": 2.0},
        ],
        n_amostras=500,
        semente=42
    )
    print("\nMonte Carlo LCOH (resumo):")
    print({k: round(v, 4) if isinstance(v, float) else v for k, v in mc["lcoh"].items() if k != "amostras"})
