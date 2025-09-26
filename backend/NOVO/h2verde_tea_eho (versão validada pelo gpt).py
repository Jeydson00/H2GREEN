# h2verde_tea_eho.py
# Implementação aderente ao "Manual - LCOH Calculator" (Hydrogen Europe Observatory, mai/2024)
# - Eq.1 (composição do LCOH)
# - Eq.2 (trocas de stack), Eq.3 (SEC média vida), Eq.4–6 (capacidade, H2 output e MWh)
# - Eq.9–10 (eletricidade), Eq.11–13 (outros OPEX + stack), Eq.14–17 (grid/taxes)
# - Eq.19–22 (subsídios), Eq.23–25 (receita O2)
from dataclasses import dataclass, field
from typing import Dict, Any
import math

# =========================
# ======= ENTRADAS ========
# =========================

@dataclass
class EHOElectrolyser:
    power_kw: float = 5000.0                 # potência instalada (kW)
    sec_start_kwh_per_kg: float = 52.4       # SEC inicial (kWh/kg) ano 1 (ex.: 52.4 no manual)
    stack_durability_h: float = 80000.0      # durabilidade do stack (h)
    degradation_pct_per_1000h: float = 0.12  # % por 1000 h (manual)
    compression_kwh_per_kg: float = 2.5      # energia de compressão (kWh/kg) -> opcional nos seus cenários

@dataclass
class EHOEconomics:
    economic_life_years: int = 25            # vida econômica (manual)
    discount_rate: float = 0.06              # taxa para CRF/NPV; aqui usamos CRF (equivalente para perfis estáveis)
    other_opex_pct_capex_per_year: float = 0.03   # outros OPEX como % do CAPEX/ano (Eq.12)
    stack_replacement_pct_capex: float = 0.25     # % do CAPEX que representa o custo de trocar o stack (Eq.11)
    # Eletricidade
    electricity_price_eur_per_mwh: float = 50.0   # custo médio de eletricidade (€/MWh)
    # Grid fees & Taxes (€/MWh) - por default podem ser 0 para PV/onshore
    grid_fees_eur_per_mwh: float = 0.0
    electricity_taxes_eur_per_mwh: float = 0.0

@dataclass
class EHOCAPEX:
    electrolyser_capex_eur_per_kw: float = 700.0  # CAPEX do eletrolisador (€/kW). CAPEX de geração NÃO entra (escopo)
    installed_power_kw: float = 5000.0            # por padrão igual à potência do eletrolisador

@dataclass
class EHOSubsidiesAndRevenues:
    # Três vias de subsídio (manual):
    capex_subsidy_eur_per_kw: float = 0.0        # grant em €/kW (Eq.19, depois vira €/kg em Eq.22)
    h2_premium_eur_per_kg: float = 0.0           # prêmio/feed-in €/kg (Eq.20→22)
    reduction_grid_or_tax_eur_per_mwh: float = 0.0  # redução (€/MWh) aplicada ao consumo (Eq.21→22)
    # Receitas de O2:
    oxygen_sale_price_eur_per_ton: float = 0.0   # €/t (Eq.23–25)

@dataclass
class EHOOperatingProfile:
    operating_hours_per_year: float = 4000.0     # wholesale típico do manual; pode ser 8.500 h para SOEC etc.
    availability: float = 1.0                    # usado apenas se quiser ajustar horas efetivas (default 1)

@dataclass
class EHOScenario:
    electrolyser: EHOElectrolyser = field(default_factory=EHOElectrolyser)
    economics: EHOEconomics = field(default_factory=EHOEconomics)
    capex: EHOCAPEX = field(default_factory=EHOCAPEX)
    subs: EHOSubsidiesAndRevenues = field(default_factory=EHOSubsidiesAndRevenues)
    ops: EHOOperatingProfile = field(default_factory=EHOOperatingProfile)
    currency: str = "EUR"

# =========================
# ======= UTILITÁRIOS =====
# =========================

def crf(i: float, n: int) -> float:
    """Capital Recovery Factor."""
    if n <= 0:
        return 1.0
    if i == 0:
        return 1.0 / n
    return i * (1 + i) ** n / ((1 + i) ** n - 1)

# =========================
# ======= CÁLCULOS ========
# =========================

def stack_replacements(econ_years: int, op_hours_per_year: float, durability_h: float) -> int:
    """
    Eq.2 — número de trocas de stack ao longo da vida econômica (arredondado para baixo).
    """
    return int(math.floor((econ_years * op_hours_per_year) / max(durability_h, 1e-12)))

def average_sec_kwh_per_kg_over_life(sec0: float, degr_pct_per_1000h: float,
                                     econ_years: int, op_hours_per_year: float,
                                     durability_h: float) -> float:
    """
    Eq.3 — SEC média da vida econômica, considerando:
    - degradação %/1000h ao longo das horas
    - resets quando há troca de stack (Eq.2)
    Implementação por aproximação discreta em blocos de 1000h para ser fiel ao Manual (ver Figura/Tabela).
    """
    total_hours = econ_years * op_hours_per_year
    repls = stack_replacements(econ_years, op_hours_per_year, durability_h)

    # Simula hora a hora em passos de 1000h (suficiente; pode refinar), resetando a cada durabilidade
    step = 1000.0
    sec_sum = 0.0
    hours_counted = 0.0
    hours_until_reset = durability_h
    current_sec = sec0

    while hours_counted < total_hours - 1e-9:
        # próximo passo
        block = min(step, total_hours - hours_counted, hours_until_reset)
        # degradação no bloco
        # taxa por hora = degr_pct_per_1000h / 100 / 1000
        rate_per_h = (degr_pct_per_1000h / 100.0) / 1000.0
        sec_end = current_sec * (1 + rate_per_h * block)
        # média no bloco
        sec_block_avg = (current_sec + sec_end) / 2.0
        # acumula
        sec_sum += sec_block_avg * block
        # avança
        current_sec = sec_end
        hours_counted += block
        hours_until_reset -= block
        # reset se atingiu durabilidade
        if hours_until_reset <= 1e-9 and hours_counted < total_hours - 1e-9:
            current_sec = sec0
            hours_until_reset = durability_h

    avg_sec = sec_sum / max(total_hours, 1e-12)
    return avg_sec

def capacity_kg_per_h(power_kw: float, avg_sec_kwh_per_kg: float) -> float:
    """Eq.4 — capacidade (kg/h) = kW / (kWh/kg)."""
    return power_kw / max(avg_sec_kwh_per_kg, 1e-12)

def hydrogen_output_kg(op_hours_per_year: float, capacity_kg_h: float, econ_years: int) -> float:
    """Eq.5 — produção total (kg) na vida econômica."""
    return op_hours_per_year * capacity_kg_h * econ_years

def electricity_consumption_mwh(h2_output_kg: float, avg_sec_kwh_per_kg: float) -> float:
    """Eq.6 — consumo total (MWh) = H2_kg * (kWh/kg)/1000."""
    return (h2_output_kg * avg_sec_kwh_per_kg) / 1000.0

def add_compression_to_sec(avg_sec_kwh_per_kg: float, compression_kwh_per_kg: float) -> float:
    """Soma a energia de compressão à SEC média (se aplicável ao seu escopo)."""
    return avg_sec_kwh_per_kg + max(compression_kwh_per_kg, 0.0)

def electrolyser_capex_eur(capex_eur_per_kw: float, installed_kw: float) -> float:
    """Eq.7 — CAPEX total do eletrolisador (EUR)."""
    return capex_eur_per_kw * installed_kw

def annualised_capex_eur_per_year(capex_eur: float, i: float, n_years: int) -> float:
    """Anualização via CRF (equivalente ao NPV/annuity para perfil estável)."""
    return capex_eur * crf(i, n_years)

def electricity_cost_eur(electricity_mwh: float, price_eur_per_mwh: float) -> float:
    """Eq.9 — custo da energia (EUR)."""
    return electricity_mwh * price_eur_per_mwh

def electricity_cost_eur_per_kg(cost_eur: float, h2_output_kg: float) -> float:
    """Eq.10 — EUR/kg."""
    return cost_eur / max(h2_output_kg, 1e-12)

def other_opex_total_eur(capex_eur: float, pct_per_year: float, econ_years: int) -> float:
    """Eq.12 — outros OPEX totais (EUR) = CAPEX * %/ano * anos."""
    return capex_eur * pct_per_year * econ_years

def stack_replacement_total_eur(capex_eur: float, pct_capex: float, n_repl: int) -> float:
    """Eq.11 — custo total de trocas (EUR) = %CAPEX * CAPEX * nº trocas."""
    return capex_eur * pct_capex * n_repl

def other_opex_eur_per_kg(other_opex_eur: float, stack_eur: float, h2_output_kg: float) -> float:
    """Eq.13 — EUR/kg para outros OPEX (inclui trocas)."""
    return (other_opex_eur + stack_eur) / max(h2_output_kg, 1e-12)

def grid_fees_total_eur(electricity_mwh: float, grid_fee_eur_per_mwh: float) -> float:
    """Eq.14 — Grid fees (EUR)."""
    return electricity_mwh * grid_fee_eur_per_mwh

def grid_fees_eur_per_kg(grid_eur: float, h2_output_kg: float) -> float:
    """Eq.15 — EUR/kg."""
    return grid_eur / max(h2_output_kg, 1e-12)

def taxes_total_eur(electricity_mwh: float, taxes_eur_per_mwh: float) -> float:
    """Eq.16 — Impostos (EUR)."""
    return electricity_mwh * taxes_eur_per_mwh

def taxes_eur_per_kg(taxes_eur: float, h2_output_kg: float) -> float:
    """Eq.17 — EUR/kg."""
    return taxes_eur / max(h2_output_kg, 1e-12)

def subsidies_total_eur(capex_kw: float, grant_eur_per_kw: float,
                        h2_output_kg: float, premium_eur_per_kg: float,
                        electricity_mwh: float, reduction_eur_per_mwh: float) -> float:
    """
    Eq.19–21 — Total de subsídios (EUR):
      (1) Grant CAPEX: grant_eur_per_kw * kW_instalados
      (2) Prêmio por kg: premium_eur_per_kg * H2_kg
      (3) Redução por MWh: reduction_eur_per_mwh * MWh
    """
    capex_grant = grant_eur_per_kw * capex_kw
    premium = premium_eur_per_kg * h2_output_kg
    reduction = reduction_eur_per_mwh * electricity_mwh
    return capex_grant + premium + reduction

def subsidies_eur_per_kg(subsidies_eur: float, h2_output_kg: float) -> float:
    """Eq.22 — EUR/kg (entra com sinal negativo no LCOH total)."""
    return - subsidies_eur / max(h2_output_kg, 1e-12)

def oxygen_output_kg(h2_output_kg: float) -> float:
    """Eq.23 — kg O2 = 8 * kg H2."""
    return h2_output_kg * 8.0

def oxygen_revenues_total_eur(o2_output_kg: float, o2_price_eur_per_ton: float) -> float:
    """Eq.24 — Receita total de O2 (EUR)."""
    return (o2_output_kg / 1000.0) * o2_price_eur_per_ton

def oxygen_revenues_eur_per_kg(o2_total_eur: float, h2_output_kg: float) -> float:
    """Eq.25 — EUR/kg (entra negativo no LCOH total)."""
    return - o2_total_eur / max(h2_output_kg, 1e-12)

# =========================
# ======= SIMULAÇÃO =======
# =========================

def simulate_eho(s: EHOScenario) -> Dict[str, Any]:
    e = s.electrolyser
    ec = s.economics
    cap = s.capex
    sb = s.subs
    op = s.ops

    # Horas efetivas
    op_hours = op.operating_hours_per_year * op.availability

    # Trocas de stack (Eq.2)
    n_repl = stack_replacements(ec.economic_life_years, op_hours, e.stack_durability_h)

    # SEC média (Eq.3) — inclui apenas eletrólise; compressão somada depois (se quiser no escopo)
    avg_sec_el_kwh_kg = average_sec_kwh_per_kg_over_life(
        sec0=e.sec_start_kwh_per_kg,
        degr_pct_per_1000h=e.degradation_pct_per_1000h,
        econ_years=ec.economic_life_years,
        op_hours_per_year=op_hours,
        durability_h=e.stack_durability_h
    )
    # Somar compressão (opcional ao seu escopo)
    avg_sec_total_kwh_kg = add_compression_to_sec(avg_sec_el_kwh_kg, e.compression_kwh_per_kg)

    # Capacidade (Eq.4), produção total (Eq.5), MWh (Eq.6)
    cap_kg_h = capacity_kg_per_h(power_kw=e.power_kw, avg_sec_kwh_per_kg=avg_sec_total_kwh_kg)
    h2_total_kg = hydrogen_output_kg(op_hours, cap_kg_h, ec.economic_life_years)
    elec_mwh = electricity_consumption_mwh(h2_total_kg, avg_sec_total_kwh_kg)

    # CAPEX do eletrolisador (Eq.7) — ESCOP0: somente eletrolisador/BOP; geração fora
    capex_eur = electrolyser_capex_eur(cap.electrolyser_capex_eur_per_kw, cap.installed_power_kw)
    # CAPEX anualizado -> €/kg (anuidade / (kg/ano)) — aproxima Eq.8
    ann_capex_eur_year = annualised_capex_eur_per_year(capex_eur, ec.discount_rate, ec.economic_life_years)
    h2_per_year = h2_total_kg / ec.economic_life_years
    lcoh_capex_eur_per_kg = ann_capex_eur_year / max(h2_per_year, 1e-12)

    # Eletricidade (Eq.9–10)
    elec_cost_eur = electricity_cost_eur(elec_mwh, ec.electricity_price_eur_per_mwh)
    lcoh_electricity = electricity_cost_eur_per_kg(elec_cost_eur, h2_total_kg)

    # Outros OPEX (Eq.11–13)
    other_eur = other_opex_total_eur(capex_eur, ec.other_opex_pct_capex_per_year, ec.economic_life_years)
    stack_eur = stack_replacement_total_eur(capex_eur, ec.stack_replacement_pct_capex, n_repl)
    lcoh_other_opex = other_opex_eur_per_kg(other_eur, stack_eur, h2_total_kg)

    # Grid fees (Eq.14–15) e impostos (Eq.16–17)
    grid_eur = grid_fees_total_eur(elec_mwh, ec.grid_fees_eur_per_mwh)
    lcoh_grid = grid_fees_eur_per_kg(grid_eur, h2_total_kg)
    tax_eur = taxes_total_eur(elec_mwh, ec.electricity_taxes_eur_per_mwh)
    lcoh_taxes = taxes_eur_per_kg(tax_eur, h2_total_kg)

    # Subsídios (Eq.19–22) → EUR/kg com sinal negativo
    subs_eur_total = subsidies_total_eur(
        capex_kw=cap.installed_power_kw,
        grant_eur_per_kw=sb.capex_subsidy_eur_per_kw,
        h2_output_kg=h2_total_kg,
        premium_eur_per_kg=sb.h2_premium_eur_per_kg,
        electricity_mwh=elec_mwh,
        reduction_eur_per_mwh=sb.reduction_grid_or_tax_eur_per_mwh
    )
    lcoh_subs = subsidies_eur_per_kg(subs_eur_total, h2_total_kg)

    # O2 (Eq.23–25) → EUR/kg com sinal negativo
    o2_kg = oxygen_output_kg(h2_total_kg)
    o2_eur = oxygen_revenues_total_eur(o2_kg, sb.oxygen_sale_price_eur_per_ton)
    lcoh_o2 = oxygen_revenues_eur_per_kg(o2_eur, h2_total_kg)

    # LCOH Total (Eq.1)
    lcoh_total = (lcoh_capex_eur_per_kg + lcoh_electricity + lcoh_other_opex +
                  lcoh_grid + lcoh_taxes + lcoh_subs + lcoh_o2)

    return {
        "currency": s.currency,
        "lcoh_total": lcoh_total,
        "breakdown_eur_per_kg": {
            "CAPEX (Eq.7~8)": lcoh_capex_eur_per_kg,
            "Electricity (Eq.9–10)": lcoh_electricity,
            "Other OPEX (Eq.11–13)": lcoh_other_opex,
            "Grid fees (Eq.14–15)": lcoh_grid,
            "Electricity taxes (Eq.16–17)": lcoh_taxes,
            "Subsidies (Eq.22, negative)": lcoh_subs,
            "Oxygen revenues (Eq.25, negative)": lcoh_o2,
        },
        "lifetime_totals": {
            "H2_total_kg (Eq.5)": h2_total_kg,
            "Electricity_total_MWh (Eq.6)": elec_mwh,
            "Stack_replacements (Eq.2)": n_repl,
            "Average_SEC_kWh_per_kg (Eq.3, incl. compression)": avg_sec_total_kwh_kg,
            "Electrolyser_CAPEX_EUR (Eq.7)": capex_eur,
            "Grid_fees_EUR (Eq.14)": grid_eur,
            "Taxes_EUR (Eq.16)": tax_eur,
            "Subsidies_total_EUR (Eq.19–21)": subs_eur_total,
            "Oxygen_revenues_total_EUR (Eq.24)": o2_eur,
        }
    }

# ============ Exemplo rápido ============
if __name__ == "__main__":
    scenario = EHOScenario()
    out = simulate_eho(scenario)
    print("LCOH total [EUR/kg]:", round(out["lcoh_total"], 3))
    print("Breakdown [EUR/kg]:")
    for k,v in out["breakdown_eur_per_kg"].items():
        print(f"  - {k}: {v:.3f}")
