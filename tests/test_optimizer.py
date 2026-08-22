"""
Tests du moteur d'optimisation (src/optimizer/optimizer.py).

Ces tests encodent des propriétés qu'on a vérifiées MANUELLEMENT,
à la main, pendant plusieurs heures de debug :

  1. Réduire la durée d'une opération ne peut jamais dégrader
     le Makespan optimal.
  2. Ajouter une machine compatible à une opération ne peut jamais
     dégrader le Makespan optimal.
  3. Un planning optimisé ne fait jamais chevaucher deux tâches
     sur la même machine.
  4. Un planning optimisé respecte toujours l'ordre des opérations
     d'une même commande (contraintes de gamme).
  5. Les KPI calculés respectent des bornes logiques de base.
  6. La recommandation de compare_scenarios() est cohérente avec
     les gains calculés.

Instance de test volontairement petite (3 commandes, 4 machines)
pour que le solveur résolve en une fraction de seconde.

Lancer avec : pytest tests/ -v
"""

import pandas as pd
import pytest

from src.optimizer.optimizer import create_tasks, optimize_schedule, calculate_kpis
from src.analysis.scenario_analysis import compare_scenarios


# ============================================================
# DONNÉES DE TEST (petite instance, résolution rapide)
# ============================================================

@pytest.fixture
def machines():
    return pd.DataFrame({
        "machine_id": ["M1", "M2", "M3", "M4"],
        "machine_name": ["Machine_1", "Machine_2", "Machine_3", "Machine_4"],
    })


@pytest.fixture
def orders():
    # 3 commandes du même produit, deadline large pour ne pas
    # perturber les tests de Makespan avec des effets de retard.
    return pd.DataFrame({
        "order_id": ["O1", "O2", "O3"],
        "product_id": ["P1", "P1", "P1"],
        "quantity": [1, 1, 1],
        "deadline": [100.0, 100.0, 100.0],
    })


@pytest.fixture
def operations():
    # OP2 est volontairement un goulot : une seule machine compatible (M3),
    # partagée par les 3 commandes -> forcément séquentiel.
    return pd.DataFrame({
        "operation_id": ["OP1", "OP2"],
        "product_id": ["P1", "P1"],
        "operation_type": ["Etape1", "Etape2"],
        "duration": [2.0, 3.0],
        "compatible_machines": ["M1|M2", "M3"],
    })


def run_pipeline(orders, machines, operations):
    """Raccourci : exécute le pipeline complet et retourne (schedule, kpis)."""
    tasks = create_tasks(orders, operations)
    schedule = optimize_schedule(tasks)
    assert schedule is not None, "Le solveur n'a trouvé aucune solution exploitable."
    kpis = calculate_kpis(schedule, orders, machines)
    return schedule, kpis


# ============================================================
# 1. RÉDUIRE UNE DURÉE NE DÉGRADE JAMAIS LE MAKESPAN OPTIMAL
# ============================================================

def test_reducing_duration_never_worsens_makespan(orders, machines, operations):

    _, baseline_kpis = run_pipeline(orders, machines, operations)

    scenario_operations = operations.copy()
    scenario_operations.loc[
        scenario_operations["operation_id"] == "OP2", "duration"
    ] = 1.5  # moitié de la durée originale (3.0 -> 1.5)

    _, scenario_kpis = run_pipeline(orders, machines, scenario_operations)

    assert scenario_kpis["makespan"] <= baseline_kpis["makespan"] + 1e-6, (
        f"Réduire une durée a dégradé le Makespan : "
        f"{baseline_kpis['makespan']} -> {scenario_kpis['makespan']}"
    )


# ============================================================
# 2. AJOUTER UNE MACHINE NE DÉGRADE JAMAIS LE MAKESPAN OPTIMAL
# ============================================================

def test_adding_machine_never_worsens_makespan(orders, machines, operations):

    _, baseline_kpis = run_pipeline(orders, machines, operations)

    scenario_operations = operations.copy()
    scenario_operations.loc[
        scenario_operations["operation_id"] == "OP2", "compatible_machines"
    ] = "M3|M4"  # ajoute M4 comme option supplémentaire

    _, scenario_kpis = run_pipeline(orders, machines, scenario_operations)

    assert scenario_kpis["makespan"] <= baseline_kpis["makespan"] + 1e-6, (
        f"Ajouter une machine a dégradé le Makespan : "
        f"{baseline_kpis['makespan']} -> {scenario_kpis['makespan']}"
    )

    # Bonus : avec 3 commandes en concurrence sur une seule machine (M3),
    # ajouter une deuxième machine (M4) doit apporter un vrai gain, pas
    # juste une égalité - sinon ça indiquerait que M4 n'est pas utilisée.
    assert scenario_kpis["makespan"] < baseline_kpis["makespan"], (
        "Ajouter une machine sur un vrai goulot devrait strictement "
        "améliorer le Makespan sur cette instance de test."
    )


# ============================================================
# 3. AUCUN CHEVAUCHEMENT DE TÂCHES SUR UNE MÊME MACHINE
# ============================================================

def test_no_overlapping_tasks_on_same_machine(orders, machines, operations):

    schedule, _ = run_pipeline(orders, machines, operations)

    for machine_id, group in schedule.groupby("machine"):
        group_sorted = group.sort_values("start")
        previous_end = None

        for _, row in group_sorted.iterrows():
            if previous_end is not None:
                assert row["start"] + 1e-6 >= previous_end, (
                    f"Chevauchement détecté sur {machine_id} : "
                    f"une tâche démarre à {row['start']} avant la fin "
                    f"d'une autre à {previous_end}"
                )
            previous_end = row["end"]


# ============================================================
# 4. L'ORDRE DES OPÉRATIONS D'UNE COMMANDE EST RESPECTÉ
# ============================================================

def test_operation_sequence_respected(orders, machines, operations):

    schedule, _ = run_pipeline(orders, machines, operations)

    for order_id in orders["order_id"]:
        order_schedule = schedule[schedule["order_id"] == order_id]

        op1_end = order_schedule.loc[
            order_schedule["operation_id"] == "OP1", "end"
        ].iloc[0]

        op2_start = order_schedule.loc[
            order_schedule["operation_id"] == "OP2", "start"
        ].iloc[0]

        assert op2_start + 1e-6 >= op1_end, (
            f"Pour {order_id}, OP2 démarre ({op2_start}) avant la fin "
            f"d'OP1 ({op1_end}) - contrainte de gamme violée."
        )


# ============================================================
# 5. BORNES LOGIQUES DES KPI
# ============================================================

def test_kpi_bounds_are_logical(orders, machines, operations):

    _, kpis = run_pipeline(orders, machines, operations)

    assert 0.0 <= kpis["on_time_rate"] <= 100.0
    assert 0 <= kpis["late_orders"] <= kpis["total_orders"]
    assert kpis["makespan"] > 0
    assert kpis["total_delay"] >= 0
    assert kpis["total_orders"] == len(orders)

    # Le goulot doit être une des machines réellement utilisées
    machine_ids_used = set(kpis["machines"]["machine_id"])
    bottleneck_id = kpis["bottleneck"].split(" - ")[0].strip()
    assert bottleneck_id in machine_ids_used


# ============================================================
# 6. COHÉRENCE DE LA RECOMMANDATION compare_scenarios()
# ============================================================

def test_compare_scenarios_favorable_case():

    baseline = {
        "makespan": 100.0,
        "total_delay": 100.0,
        "late_orders": 5,
        "on_time_rate": 50.0,
        "bottleneck": "M1 - Machine_1",
    }

    scenario = {
        "makespan": 80.0,   # -20 % : gain net
        "total_delay": 80.0,  # -20 % : gain net
        "late_orders": 3,
        "on_time_rate": 70.0,
        "bottleneck": "M2 - Machine_2",
    }

    result = compare_scenarios(baseline, scenario)

    assert result["recommendation"] == "SCÉNARIO FAVORABLE"
    assert result["makespan_gain"] == pytest.approx(20.0, abs=0.01)
    assert result["delay_gain"] == pytest.approx(20.0, abs=0.01)


def test_compare_scenarios_unfavorable_case():

    baseline = {
        "makespan": 100.0,
        "total_delay": 100.0,
        "late_orders": 5,
        "on_time_rate": 50.0,
        "bottleneck": "M1 - Machine_1",
    }

    scenario = {
        "makespan": 99.0,   # quasi aucun gain
        "total_delay": 100.0,
        "late_orders": 5,
        "on_time_rate": 50.0,
        "bottleneck": "M1 - Machine_1",
    }

    result = compare_scenarios(baseline, scenario)

    assert result["recommendation"] == "SCÉNARIO PEU INTÉRESSANT"