# h2verde_tea.py
# Módulo único com as rotinas de cálculo técnico-financeiro (LCOH) para H2 verde via eletrólise.
# Apenas Python padrão.

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import math
import copy


# =========================
# ====== ESTRUTURAS =======
# =========================

@dataclass
class EspecificacaoEletrolisador:
    nome: str = "PEM_5MW_referencia"
    sec_kwh_por_kg: float = 52.0           # kWh/kg H2 (AC, incluindo BoP) no Ano 1
    fracao_minima_carga: float = 0.10      # fração mínima de carga (0-1)
    disponibilidade: float = 0.97          # disponibilidade anual
    potencia_kw: float = 5000.0            # potência nominal AC [kW]
    vida_util_anos: int = 8                # vida do stack (anos) para reposição
    degradacao_pct_ano: float = 0.5        # degradação anual da SEC (%/ano)
    fracao_reposicao_stack_capex: float = 0.25  # fração do CAPEX de eletrólise


@dataclass
class BalanceOfPlant:
    fracao_capex_bop: float = 0.35
    om_fixo_pct_capex_ano: float = 0.03    # fração do CAPEX por ano
    om_variavel_por_kg: float = 0.20       # moeda/kg (químicos, filtros etc.)


@dataclass
class TarifaEnergia:
    preco_mwh: float = 350.0               # moeda/MWh entregue
    demanda_kw_mes: float = 0.0            # moeda/kW-mês
    demanda_contratada_kw: float = 0.0     # kW


@dataclass
class AguaUtilidades:
    custo_agua_m3: float = 5.0             # moeda/m3
    litros_por_kg: float = 9.0             # L/kg


@dataclass
class CompressaoArmazenamentoEntrega:
    pressao_entrega_bar: float = 350.0
    energia_compressao_kwh_por_kg: float = 2.5   # kWh/kg até pressão de entrega
    capex_armazenamento_por_kg: float = 400.0    # moeda/kg capacidade de buffer
    horas_buffer: float = 4.0                    # h de buffer na taxa média
    secagem_purificacao_por_kg: float = 0.10     # moeda/kg


@dataclass
class Financiamento:
    wacc_real: float = 0.10                 # WACC real (fração)
    inflacao_pct: float = 4.0               # %/ano
    vida_projeto_anos: int = 20
    fracao_divida: float = 0.60             # informativo nesta versão
    contingencia_capex_pct: float = 10.0


@dataclass
class CapexDetalhado:
    eletrolisador_capex_por_kw: float = 700.0    # moeda/kW(ac)
    fracao_bop: float = 0.35
    instalacao_pct: float = 12.0                 # % do CAPEX direto
    custos_dono_pct: float = 5.0                 # % do CAPEX direto
    interconexao_por_kw: float = 80.0            # moeda/kW
    capex_tratamento_agua: float = 200000.0      # moeda
    compressor_capex_por_kg_h: float = 1200.0    # moeda por (kg/h) nominal


@dataclass
class CenarioEntrada:
    moeda: str = "BRL"
    eletrolisador: EspecificacaoEletrolisador = field(default_factory=EspecificacaoEletrolisador)
    bop: BalanceOfPlant = field(default_factory=BalanceOfPlant)
    energia: TarifaEnergia = field(default_factory=TarifaEnergia)
    agua: AguaUtilidades = field(default_factory=AguaUtilidades)
    cae: CompressaoArmazenamentoEntrega = field(default_factory=CompressaoArmazenamentoEntrega)
    financiamento: Financiamento = field(default_factory=Financiamento)
    capex: CapexDetalhado = field(default_factory=CapexDetalhado)
    fator_capacidade_anual: float = 0.85
    horas_ano: int = 8760
    emissoes_rede_kg_mwh: float = 80.0

    def validar(self):
        if not (0.0 <= self.fator_capacidade_anual <= 1.0):
            raise ValueError("fator_capacidade_anual deve estar entre 0 e 1")


@dataclass
class ItemLinha:
    nome: str
    valor: float
    unidade: str


# ==================================
# ====== FUNÇÕES FINANCEIRAS =======
# ==================================

def fator_recuperacao_capital(wacc_real: float, anos: int) -> float:
    i = wacc_real
    if anos <= 0:
        return 1.0
    if i == 0.0:
        return 1.0 / anos
    return i * (1.0 + i) ** anos / ((1.0 + i) ** anos - 1.0)


def anualizar_capex(capex_total: float, wacc_real: float, anos: int) -> float:
    return capex_total * fator_recuperacao_capital(wacc_real, anos)


# =========================================
# ====== MODELOS TÉCNICOS E CÁLCULOS ======
# =========================================

def consumo_especifico_ano(e: EspecificacaoEletrolisador, ano: int) -> float:
    crescimento = (1.0 + e.degradacao_pct_ano / 100.0) ** max(0, ano - 1)
    return e.sec_kwh_por_kg * crescimento


def producao_anual_kg(e: EspecificacaoEletrolisador, fator_cf: float, horas_ano: int = 8760) -> float:
    horas_efetivas = horas_ano * fator_cf * e.disponibilidade
    return (e.potencia_kw * horas_efetivas) / max(e.sec_kwh_por_kg, 1e-12)


def capacidade_armazenamento_kg(cae: CompressaoArmazenamentoEntrega, h2_anual_kg: float, horas_ano: float) -> float:
    media_kg_h = h2_anual_kg / max(horas_ano, 1e-12)
    return media_kg_h * cae.horas_buffer


# =========================================
# ====== SIMULAÇÃO TECNO-ECONÔMICA ========
# =========================================

def simular(c: CenarioEntrada) -> Dict[str, Any]:
    c.validar()

    # CAPEX
    itens_capex = calcular_capex(c)
    total_capex = next(i.valor for i in itens_capex if i.nome == "Total CAPEX")

    # Produção e energia
    h2_anual = producao_anual_kg(c.eletrolisador, c.fator_capacidade_anual, c.horas_ano)
    itens_energia, itens_var, mwh_anual, kwh_por_kg = calcular_energia_var(c, h2_anual)

    # O&M fixo
    itens_fixos = calcular_opex_fixo(c, itens_capex)
    custo_fixo = sum(i.valor for i in itens_fixos)
    custo_variavel = sum(i.valor for i in itens_var)

    # Reposição de stack
    base_stack = (c.capex.eletrolisador_capex_por_kw * c.eletrolisador.potencia_kw) * c.eletrolisador.fracao_reposicao_stack_capex
    reposicao_anual_equiv = base_stack / max(c.eletrolisador.vida_util_anos, 1)

    # CAPEX anualizado
    capex_anual = anualizar_capex(total_capex, c.financiamento.wacc_real, c.financiamento.vida_projeto_anos)

    # LCOH
    custo_total_anual = capex_anual + custo_fixo + custo_variavel + reposicao_anual_equiv
    lcoh = custo_total_anual / max(h2_anual, 1e-12)

    # Emissões
    emissoes = (kwh_por_kg / 1000.0) * c.emissoes_rede_kg_mwh

    return {
        "lcoh": lcoh,
        "h2_anual_kg": h2_anual,
        "mwh_anual": mwh_anual,
        "emissoes_kgco2_por_kg": emissoes,
        "capex": [i.__dict__ for i in itens_capex],
        "opex_fixo": [i.__dict__ for i in itens_fixos],
        "opex_variavel": [i.__dict__ for i in itens_var] + [ItemLinha("Reposição Stack (anual eq.)", reposicao_anual_equiv, c.moeda).__dict__],
        "energia": [i.__dict__ for i in itens_energia]
    }


def calcular_capex(c: CenarioEntrada) -> List[ItemLinha]:
    p_kw = c.eletrolisador.potencia_kw
    eletrolisador = p_kw * c.capex.eletrolisador_capex_por_kw
    bop = eletrolisador * c.capex.fracao_bop
    interconexao = p_kw * c.capex.interconexao_por_kw
    kg_h = p_kw / max(c.eletrolisador.sec_kwh_por_kg, 1e-12)
    compressor = kg_h * c.capex.compressor_capex_por_kg_h
    h2_anual = producao_anual_kg(c.eletrolisador, c.fator_capacidade_anual, c.horas_ano)
    armazenamento = capacidade_armazenamento_kg(c.cae, h2_anual, c.horas_ano * c.eletrolisador.disponibilidade) * c.cae.capex_armazenamento_por_kg
    agua = c.capex.capex_tratamento_agua
    diretos = eletrolisador + bop + interconexao + compressor + armazenamento + agua
    instalacao = diretos * (c.capex.instalacao_pct / 100.0)
    custos_dono = diretos * (c.capex.custos_dono_pct / 100.0)
    contingencia = (diretos + instalacao + custos_dono) * (c.financiamento.contingencia_capex_pct / 100.0)
    total = diretos + instalacao + custos_dono + contingencia

    return [
        ItemLinha("Eletrolisador", eletrolisador, c.moeda),
        ItemLinha("Balance of Plant", bop, c.moeda),
        ItemLinha("Interconexão", interconexao, c.moeda),
        ItemLinha("Compressor", compressor, c.moeda),
        ItemLinha("Armazenamento Buffer", armazenamento, c.moeda),
        ItemLinha("Tratamento Água", agua, c.moeda),
        ItemLinha("Instalação/EPC", instalacao, c.moeda),
        ItemLinha("Custos do Dono", custos_dono, c.moeda),
        ItemLinha("Contingência", contingencia, c.moeda),
        ItemLinha("Total CAPEX", total, c.moeda),
    ]


def calcular_opex_fixo(c: CenarioEntrada, itens_capex: List[ItemLinha]) -> List[ItemLinha]:
    total_capex = next(i.valor for i in itens_capex if i.nome == "Total CAPEX")
    om_fixo = total_capex * c.bop.om_fixo_pct_capex_ano
    demanda = (
        c.energia.demanda_kw_mes * c.energia.demanda_contratada_kw * 12.0
        if c.energia.demanda_kw_mes > 0 else 0.0
    )
    return [
        ItemLinha("O&M Fixo (% CAPEX)", om_fixo, c.moeda),
        ItemLinha("Custo Demanda (anual)", demanda, c.moeda),
    ]


def calcular_energia_var(c: CenarioEntrada, h2_anual: float) -> (List[ItemLinha], List[ItemLinha], float, float):
    sec = c.eletrolisador.sec_kwh_por_kg
    comp = c.cae.energia_compressao_kwh_por_kg
    total_kwh_kg = sec + comp
    mwh_anual = (total_kwh_kg * h2_anual) / 1000.0
    custo_energia = mwh_anual * c.energia.preco_mwh
    m3_agua = (c.agua.litros_por_kg / 1000.0) * h2_anual
    custo_agua = m3_agua * c.agua.custo_agua_m3
    vom = c.bop.om_variavel_por_kg * h2_anual + c.cae.secagem_purificacao_por_kg * h2_anual

    itens_energia = [
        ItemLinha("Eletricidade (Eletrólise+Compressão)", mwh_anual, "MWh/ano"),
        ItemLinha("SEC Médio (incl. compressão)", total_kwh_kg, "kWh/kg"),
    ]
    itens_var = [
        ItemLinha("Custo Energia", custo_energia, c.moeda),
        ItemLinha("Custo Água", custo_agua, c.moeda),
        ItemLinha("O&M Variável", vom, c.moeda),
    ]
    return itens_energia, itens_var, mwh_anual, total_kwh_kg


# Exemplo rápido
if __name__ == "__main__":
    cenario = CenarioEntrada()
    resultado = simular(cenario)
    print("LCOH [moeda/kg]:", round(resultado["lcoh"], 2))
    print("Produção anual [kg]:", round(resultado["h2_anual_kg"], 2))
    print("Energia anual [MWh]:", round(resultado["mwh_anual"], 2))
    print("Emissões [kgCO2/kgH2]:", round(resultado["emissoes_kgco2_por_kg"], 4))
