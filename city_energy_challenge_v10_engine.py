"""City Energy Transition Challenge v0.8 (island-tropical resource calibration).
Illustrative assumptions, not project quotations or a grid planning model.
Run: python city_energy_challenge_v05.py
"""
from dataclasses import dataclass
from typing import Dict, List

YEARS = range(1, 16)
PERIOD_HOURS = {"day": 12, "evening": 6, "night": 6}
HOURS_YEAR = {p: h * 365 for p, h in PERIOD_HOURS.items()}

SECTORS = {
    "residential": {"electricity": 40., "heat": 5., "growth_e": .02, "growth_h": .02, "profile": (.35, .45, .20)},
    "commercial": {"electricity": 25., "heat": 5., "growth_e": .03, "growth_h": .03, "profile": (.72, .20, .08)},
    "government": {"electricity": 10., "heat": 2., "growth_e": .01, "growth_h": .01, "profile": (.80, .10, .10)},
    "industry": {"electricity": 25., "heat": 28., "growth_e": .04, "growth_h": .04, "profile": (.60, .24, .16)},
}
PERIODS = tuple(PERIOD_HOURS)

@dataclass(frozen=True)
class Technology:
    lead_years: int
    capex_billion: float             # Rp billion / package
    capacity_mw: float               # electrical nameplate
    electricity_gwh_year: float      # annual electrical energy budget / package
    heat_gwh_year: float             # annual usable thermal energy / package
    profile: tuple                   # fractions of annual electrical energy across periods
    opex_billion_year: float = 0.0
    max_packages: int = 99

# Reference-case engineering assumptions, calibrated against IRENA 2024 global
# installed-cost and capacity-factor benchmarks (IRENA report published 2025).
# Rp/USD reference conversion: 16,000, rounded and adjusted for project scale/site.
# OPEX is a scenario assumption, not a directly quoted IRENA value.
# Heat: biomass assumes an explicitly configured CHP heat offtake; geothermal
# direct heat is ZERO in the base package to avoid double counting.
FX_RP_USD = 16000.0
# Resource reference case: tropical island setting with seasonal water and wind,
# site-specific hydro and geothermal, and finite sustainable biomass feedstock.
# Location deliberately unspecified in participant-facing output.
# Annual generation derives from nameplate capacity and scenario capacity factor.
CAPACITY_FACTORS = {
    "solar": 0.17,
    "wind": 0.25,
    "biomass": 0.70,
    "hydro": 0.40,
    "geothermal": 0.85,
}

def annual_generation_gwh(capacity_mw, capacity_factor):
    return capacity_mw * 8760.0 * capacity_factor / 1000.0

TECH = {
    "solar":      Technology(1,  65., 5., annual_generation_gwh(5., CAPACITY_FACTORS["solar"]), 0., (1., 0., 0.),    1.0, 8),
    "wind":       Technology(2, 100., 5., annual_generation_gwh(5., CAPACITY_FACTORS["wind"]), 0., (.40,.30,.30), 2.5, 4),
    "biomass":    Technology(2, 165., 3., annual_generation_gwh(3., CAPACITY_FACTORS["biomass"]), 8., (.50,.25,.25),16.0, 2),
    "hydro":      Technology(5, 200., 5., annual_generation_gwh(5., CAPACITY_FACTORS["hydro"]), 0., (.50,.25,.25), 3.0, 2),
    "geothermal": Technology(5, 350., 5., annual_generation_gwh(5., CAPACITY_FACTORS["geothermal"]), 0., (.50,.25,.25), 9.0, 2),
}
TECH_NOTES = {
    "solar": "Utility PV 5 MWp; 17% CF; daylight-only simplified generation; no battery",
    "wind": "Onshore wind 5 MW; 25% CF; site-qualified wind; seasonal variability not yet modeled",
    "biomass": "CHP 3 MWe; 70% electrical CF; 8 GWhth/y useful heat; fuel/logistics included in OPEX",
    "hydro": "Reservoir hydro 5 MW; 40% annual CF; simplified annual water-energy budget",
    "geothermal": "Geothermal 5 MWe; 85% CF; site-specific reservoir; electric-only base package",
}

# These are deliberately stylized game costs and direct combustion emissions.
FOSSIL = {
    "coal": {"capacity_mw": 15., "min_stable_fraction": .35, "ramp_mw_per_hour": 1.10, "cost_rp_kwh": 800., "emission_kg_kwh": 1.0},
    "gas": {"capacity_mw": 10., "cost_rp_kwh": 1500., "emission_kg_kwh": .5},
    "heat": {"cost_rp_kwh": 1000., "emission_kg_kwh": .25},
}
# Coal baseline is calibrated to 90 GWh/year, gas to 10 GWh/year, for year 0.
COAL_BASELINE_GWH = 90.
BASELINE_GAS_SHARE = 0.10  # 10% energy in every time block at year 0
BUDGET_BILLION = 1000.  # Illustrative, total budget across both investment rounds per city

@dataclass(frozen=True)
class Investment:
    technology: str
    packages: int
    year: int


def demand_at_year(year: int, growth_overrides=None):
    """Return electricity by time block (GWh) and total annual thermal demand (GWhth)."""
    e = dict.fromkeys(PERIODS, 0.)
    heat = 0.
    for name, sector in SECTORS.items():
        ge = (growth_overrides or {}).get(name, sector["growth_e"])
        annual_e = sector["electricity"] * (1 + ge) ** year
        heat += sector["heat"] * (1 + sector["growth_h"]) ** year
        for period, fraction in zip(PERIODS, sector["profile"]):
            e[period] += annual_e * fraction
    return e, heat


def validate_investments(investments: List[Investment]):
    capex = 0.
    counts = {k: 0 for k in TECH}
    for inv in investments:
        if inv.technology not in TECH or inv.packages < 0 or inv.year not in (0, 5):
            raise ValueError(f"Invalid investment: {inv}")
        t = TECH[inv.technology]
        counts[inv.technology] += inv.packages
        capex += inv.packages * t.capex_billion
    for name, count in counts.items():
        if count > TECH[name].max_packages:
            raise ValueError(f"Resource limit exceeded: {name}")
    if capex > BUDGET_BILLION:
        raise ValueError(f"APBD exceeded: {capex:.1f} > {BUDGET_BILLION:.1f} Rp billion")
    return capex


def generation_at_year(investments: List[Investment], year: int, event=None):
    """Per-technology available energy per block, not yet dispatched (GWh)."""
    gen = {k: {p: 0. for p in PERIODS} for k in TECH}
    installed = {k: 0 for k in TECH}
    heat = 0.
    opex = 0.
    for inv in investments:
        t = TECH[inv.technology]
        if year < inv.year + t.lead_years:
            continue
        installed[inv.technology] += inv.packages
        multiplier = (event or {}).get("generation_multiplier", {}).get(inv.technology, 1.)
        if multiplier < 0:
            raise ValueError("Generation multiplier cannot be negative")
        for period, fraction in zip(PERIODS, t.profile):
            gen[inv.technology][period] += inv.packages * t.electricity_gwh_year * fraction * multiplier
        heat += inv.packages * t.heat_gwh_year * multiplier
        opex += inv.packages * t.opex_billion_year
    return gen, heat, opex, installed


def dispatch_year(demand, renewable, installed, year, coal_settings=None,
                  hours_by_period=None, availability=None):
    """Three-period average-power dispatch with a simple coal commitment rule.

    Baseload coal target is at most 90% of gross demand in each block,
    preserving the 90/10 year-zero calibration. Renewable output displaces
    coal first. If the residual coal target is below its minimum stable output,
    the coal unit is turned OFF for that block; gas covers any shortfall.

    Ramp limits constrain consecutive ONLINE coal blocks only. Shutdown/startup
    are idealized (no startup fuel, minimum up/down time, or startup ramp).
    Ramping is applied to average MW between blocks, not subhourly power.
    A repeated typical day is assumed; no year-to-year ramp continuity.
    """
    coal_cfg = {**FOSSIL["coal"], **(coal_settings or {})}
    availability = availability or {}
    hours_by_period = hours_by_period or HOURS_YEAR
    coal_cap_mw = coal_cfg["capacity_mw"] * availability.get("coal", 1.)
    min_mw = coal_cap_mw * coal_cfg["min_stable_fraction"]
    ramp_mw_per_hour = coal_cfg["ramp_mw_per_hour"]
    if not (0 <= coal_cfg["min_stable_fraction"] <= 1) or ramp_mw_per_hour < 0:
        raise ValueError("Invalid coal min stable fraction or ramp rate")

    result = {"re_used": 0., "coal": 0., "gas": 0., "unserved": 0., "curtailed": 0.}
    result["technology_used"] = {k: 0. for k in TECH}
    result["periods"] = {}
    priority = ("geothermal", "hydro", "biomass", "solar", "wind")
    previous_coal_mw = None
    # Block-to-block transition windows: day -> evening 9h,
    # evening -> night 6h (distance between block midpoints).
    ramp_transition_hours = {"day": None, "evening": 9., "night": 6.}
    for period in PERIODS:
        hours = hours_by_period[period]
        remaining = demand[period]
        used_by_tech = {}
        curtailed_by_tech = {}
        for name in priority:
            factor = availability.get(name, 1.)
            cap_gwh = installed[name] * TECH[name].capacity_mw * hours / 1000 * factor
            available = min(renewable[name][period] * factor, cap_gwh)
            used = min(remaining, available)
            used_by_tech[name] = used
            curtailed_by_tech[name] = renewable[name][period] - used
            remaining -= used
            result["technology_used"][name] += used
            result["re_used"] += used
            result["curtailed"] += curtailed_by_tech[name]

        # Set desired coal power, respecting original 90%-of-gross baseline.
        coal_target_gwh = min(remaining, coal_cap_mw * hours / 1000,
                              (1 - BASELINE_GAS_SHARE) * demand[period])
        target_mw = coal_target_gwh * 1000 / hours
        coal_mw = 0.
        if target_mw >= min_mw:
            coal_mw = target_mw
            if previous_coal_mw is not None and previous_coal_mw >= min_mw:
                ramp_window = ramp_transition_hours[period]
                max_delta = ramp_mw_per_hour * ramp_window
                # Ramp-up limit can require more gas. Ramp-down cannot force
                # overgeneration: shut coal down when ramp floor exceeds load.
                coal_mw = min(coal_mw, previous_coal_mw + max_delta)
                ramp_floor = max(min_mw, previous_coal_mw - max_delta)
                if coal_mw < ramp_floor - 1e-10:
                    coal_mw = 0.
        coal = coal_mw * hours / 1000
        remaining -= coal
        previous_coal_mw = coal_mw

        gas_cap = FOSSIL["gas"]["capacity_mw"] * hours / 1000 * availability.get("gas", 1.)
        gas = min(remaining, gas_cap)
        remaining -= gas
        result["coal"] += coal
        result["gas"] += gas
        result["unserved"] += remaining
        result["periods"][period] = {
            "demand": demand[period], "renewable": sum(used_by_tech.values()),
            "coal": coal, "coal_mw": coal_mw, "coal_online": coal_mw > 0,
            "gas": gas, "unserved": remaining,
            "curtailed": sum(curtailed_by_tech.values()),
            "technology_used": used_by_tech,
        }
        assert abs(demand[period] - sum(used_by_tech.values()) - coal - gas - remaining) < 1e-8
    return result


def simulate(investments: List[Investment], events=None, coal_settings=None):
    capex = validate_investments(investments)
    rows = []
    for year in YEARS:
        event = (events or {}).get(year, {})
        demand_e, demand_h = demand_at_year(year, event.get("growth_overrides"))
        re, re_heat, re_opex, installed = generation_at_year(investments, year, event)
        power = dispatch_year(demand_e, re, installed, year, coal_settings=coal_settings)
        heat_used = min(demand_h, re_heat)
        fossil_heat = demand_h - heat_used
        fossil_cost = (power["coal"] * FOSSIL["coal"]["cost_rp_kwh"]
                       + power["gas"] * FOSSIL["gas"]["cost_rp_kwh"]
                       + fossil_heat * FOSSIL["heat"]["cost_rp_kwh"]) / 1000
        # GWh * Rp/kWh / 1000 = billion rupiah
        emissions_kt = (power["coal"] * FOSSIL["coal"]["emission_kg_kwh"]
                        + power["gas"] * FOSSIL["gas"]["emission_kg_kwh"]
                        + fossil_heat * FOSSIL["heat"]["emission_kg_kwh"])
        rows.append({"year": year, "electricity_demand_gwh": sum(demand_e.values()),
                     "heat_demand_gwhth": demand_h, **{f"electricity_{k}_gwh": power[k] for k in ("re_used", "coal", "gas", "unserved", "curtailed")},
                     "dispatch_periods": power["periods"], "technology_used_gwh": power["technology_used"],
                     "renewable_heat_gwhth": heat_used, "fossil_heat_gwhth": fossil_heat,
                     "annual_operating_cost_billion": fossil_cost + re_opex,
                     "annual_emissions_ktco2": emissions_kt})
    return {"capex_billion": capex, "annual": rows,
            "cumulative_operating_cost_billion": sum(r["annual_operating_cost_billion"] for r in rows),
            "cumulative_emissions_ktco2": sum(r["annual_emissions_ktco2"] for r in rows)}


def print_comparison(a, b):
    print("CITY ENERGY TRANSITION CHALLENGE — resource-calibrated v0.5")
    for name, result in (("City A", a), ("City B", b)):
        end = result["annual"][-1]
        print(f"\n{name}: CAPEX Rp {result['capex_billion']:.1f} bn")
        print(f"  Year 15 electricity: {end['electricity_demand_gwh']:.2f} GWh")
        print(f"  Year 15 RE used / coal / gas: {end['electricity_re_used_gwh']:.2f} / {end['electricity_coal_gwh']:.2f} / {end['electricity_gas_gwh']:.2f} GWh")
        print(f"  Year 15 unserved: {end['electricity_unserved_gwh']:.2f} GWh")
        print(f"  Year 15 renewable heat: {end['renewable_heat_gwhth']:.2f} GWhth")
        print(f"  15y OPEX: Rp {result['cumulative_operating_cost_billion']:.1f} bn")
        print(f"  15y emissions: {result['cumulative_emissions_ktco2']:.1f} ktCO2")


if __name__ == "__main__":

    print("\nTECHNOLOGY CALIBRATION (per package)")
    for name, tech in TECH.items():
        cf = tech.electricity_gwh_year * 1000 / (tech.capacity_mw * 8760)
        assert 0 < cf <= 1, (name, cf)
        assert abs(sum(tech.profile)-1) < 1e-9
        assert abs(cf - CAPACITY_FACTORS[name]) < 1e-12
        for period, share in zip(PERIODS, tech.profile):
            assert tech.electricity_gwh_year * share <= tech.capacity_mw * HOURS_YEAR[period] / 1000 + 1e-9
        print(f"{name:12s}: {tech.capacity_mw:4.1f} MW | {tech.electricity_gwh_year:5.1f} GWh/y | CF {cf:.1%} | CAPEX Rp {tech.capex_billion:.0f}bn | OPEX Rp {tech.opex_billion_year:.1f}bn/y")
    baseline_demand, _ = demand_at_year(0)
    baseline_gen, _, _, baseline_installed = generation_at_year([], 0)
    baseline = dispatch_year(baseline_demand, baseline_gen, baseline_installed, 0)
    assert abs(baseline["coal"] - 90.) < 1e-9
    assert abs(baseline["gas"] - 10.) < 1e-9
    assert baseline["unserved"] == 0.
    print("Baseline year 0: coal = 90.00 GWh, gas = 10.00 GWh")
    city_a = [Investment("solar", 3, 0), Investment("wind", 2, 0), Investment("biomass", 1, 5)]
    city_b = [Investment("geothermal", 1, 0), Investment("hydro", 1, 0), Investment("solar", 2, 5)]
    print_comparison(simulate(city_a), simulate(city_b))
    # Verify hard resource caps (no unlimited site potential).
    for technology, tech in TECH.items():
        try:
            validate_investments([Investment(technology, tech.max_packages + 1, 0)])
        except ValueError:
            pass
        else:
            raise AssertionError(f"Resource cap not enforced for {technology}")
    # A ramp-rate stress test: severe ramp restriction increases gas usage.
    slow = dispatch_year(baseline_demand, baseline_gen, baseline_installed, 0,
                         coal_settings={"ramp_mw_per_hour": .20})
    assert slow["gas"] > baseline["gas"]
    assert slow["unserved"] < 1e-9
    # High renewable output can switch coal off below minimum stable load.
    solar_gen, _, _, solar_installed = generation_at_year(
        [Investment("solar", 5, 0)], 1)
    solar_dispatch = dispatch_year(baseline_demand, solar_gen, solar_installed, 1)
    assert solar_dispatch["periods"]["day"]["coal_mw"] == 0
    print(f"Ramp stress test: baseline gas {baseline['gas']:.2f} -> {slow['gas']:.2f} GWh")
    print("Min-load test: daytime coal switches off with large solar build")


# Resilience stress test: separate from normal 15-year cost/emissions.
# Fractions represent availability during a hypothetical 14-day disruption.
STRESS_TEST = {
    "year": 15,
    "duration_days": 14,
    "availability": {
        "coal": .50, "gas": .50, "solar": .70, "wind": .60,
        "hydro": .90, "geothermal": .95, "biomass": .85,
    },
}

def stress_test(investments, config=None, events=None, coal_settings=None):
    """Return energy-served fraction under a common hypothetical supply shock.

    Uses the same three-period dispatch as the normal simulation. Annual
    demand/production are scaled to a representative 14-day interval; resource
    availability is applied ONCE to both energy and power limits. This is an
    aggregate adequacy proxy, not a grid stability or LOLP model.
    """
    validate_investments(investments)
    cfg = STRESS_TEST if config is None else config
    year, days = cfg["year"], cfg["duration_days"]
    if not 1 <= year <= 15 or not 0 < days <= 365:
        raise ValueError("Stress test year/duration invalid")
    availability = cfg["availability"]
    if any(k not in (*TECH, "coal", "gas") or not 0 <= v <= 1
           for k, v in availability.items()):
        raise ValueError("Availability must be between 0 and 1 for known technologies")
    event = (events or {}).get(year, {})
    demand, _ = demand_at_year(year, event.get("growth_overrides"))
    renewable, _, _, installed = generation_at_year(investments, year, event)
    scale = days / 365.
    short_demand = {k: v * scale for k, v in demand.items()}
    short_renewable = {k: {period: v * scale for period, v in per.items()}
                       for k, per in renewable.items()}
    hours = {period: PERIOD_HOURS[period] * days for period in PERIODS}
    dispatch = dispatch_year(short_demand, short_renewable, installed, year,
                             coal_settings=coal_settings, hours_by_period=hours,
                             availability=availability)
    total = sum(short_demand.values())
    return {
        "year": year, "duration_days": days,
        "demand_gwh": total, "unserved_gwh": dispatch["unserved"],
        "served_gwh": total - dispatch["unserved"],
        "served_percent": 100 * (1 - dispatch["unserved"] / total),
        "dispatch": dispatch,
    }
