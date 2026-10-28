"""
Tests de l'algorithme génétique (src/optimizer/genetic.py).

Un algorithme génétique est aléatoire : on teste donc des GARANTIES
(planning valide, jamais pire que la solution de départ, reproductible
avec la même graine, jamais meilleur que l'optimum exact du MILP...)
et non une valeur de Makespan précise.
"""

import random

import pandas as pd

from src.optimizer.decoder import (
    SCHEDULE_COLUMNS,
    Problem,
    check_chromosome,
    decode,
    random_chromosome,
)
from src.optimizer.genetic import (
    greedy_chromosome,
    mutate_ms,
    mutate_os,
    optimize_schedule_ga,
    pox_crossover,
    run_ga,
    uniform_crossover_ms,
)


# ============================================================
# OUTILS
# ============================================================

def make_tasks(spec):
    """spec : liste de (order_id, [ {machine: durée}, ... ], deadline)."""

    rows = []

    for order_id, operations, deadline in spec:
        for number, durations in enumerate(operations, start=1):
            rows.append({
                "task_id": f"{order_id}_OP{number}",
                "order_id": order_id,
                "product_id": f"P_{order_id}",
                "operation_number": number,
                "operation_id": f"OP{number}",
                "operation_type": f"Type{number}",
                "quantity": 1.0,
                "duration": sum(durations.values()) / len(durations),
                "machine_durations": dict(durations),
                "compatible_machines": list(durations.keys()),
                "deadline": float(deadline),
            })

    return pd.DataFrame(rows)


def random_instance(seed, n_orders=8):
    rng = random.Random(seed)
    machines = ["M1", "M2", "M3", "M4", "M5"]
    spec = []

    for i in range(n_orders):
        operations = []
        for _ in range(rng.randint(3, 5)):
            chosen = rng.sample(machines, rng.randint(1, 3))
            operations.append({m: float(rng.randint(1, 9)) for m in chosen})
        spec.append((f"O{i + 1}", operations, 50))

    return make_tasks(spec)


def assert_valid_schedule(schedule, tasks, unavailability=None):
    """Vérifie un planning indépendamment du décodeur et du GA."""

    unavailability = unavailability or {}

    assert list(schedule.columns) == SCHEDULE_COLUMNS
    assert sorted(schedule["task_id"]) == sorted(tasks["task_id"])

    by_task = {t["task_id"]: t for t in tasks.to_dict("records")}

    for _, row in schedule.iterrows():
        expected = by_task[row["task_id"]]["machine_durations"][row["machine"]]
        assert abs((row["end"] - row["start"]) - expected) <= 0.011

    for machine, group in schedule.groupby("machine"):
        previous_end = None
        for _, row in group.sort_values("start").iterrows():
            if previous_end is not None:
                assert row["start"] >= previous_end - 1e-9, f"Chevauchement sur {machine}"
            previous_end = row["end"]

    times = schedule.set_index("task_id")
    for _, group in tasks.groupby("order_id"):
        ordered = group.sort_values("operation_number")["task_id"].tolist()
        for before, after in zip(ordered, ordered[1:]):
            assert times.loc[after, "start"] >= times.loc[before, "end"] - 1e-9

    for machine, windows in unavailability.items():
        for _, row in schedule[schedule["machine"] == machine].iterrows():
            for window_start, window_end in windows:
                assert (
                    row["end"] <= round(window_start, 2) + 1e-9
                    or row["start"] >= round(window_end, 2) - 1e-9
                ), f"{row['task_id']} chevauche une fenêtre sur {machine}"


# ============================================================
# 1. OPERATEURS : ils ne produisent que des chromosomes valides
# ============================================================

def test_operators_always_produce_valid_chromosomes():
    for seed in range(5):

        tasks = random_instance(seed)
        problem = Problem(tasks)
        rng = random.Random(seed)
        order_ids = list(problem.order_tasks.keys())

        for _ in range(100):
            os1, ms1 = random_chromosome(problem, rng)
            os2, ms2 = random_chromosome(problem, rng)

            child_os1, child_os2 = pox_crossover(os1, os2, order_ids, rng)
            child_ms1, child_ms2 = uniform_crossover_ms(ms1, ms2, problem.task_order, rng)

            for child_os, child_ms in ((child_os1, child_ms1), (child_os2, child_ms2)):
                mutate_os(child_os, rng)
                mutate_ms(child_ms, problem, rng)
                check_chromosome(problem, child_os, child_ms)  # lève ValueError sinon


def test_greedy_chromosomes_are_valid():
    for seed in range(5):
        problem = Problem(random_instance(seed))
        rng = random.Random(seed)

        for mode in ("fastest", "balanced"):
            for noise in (0.0, 0.3):
                os_vector, ms = greedy_chromosome(problem, rng, mode, noise)
                check_chromosome(problem, os_vector, ms)


# ============================================================
# 2. TROUVE L'OPTIMUM CALCULE A LA MAIN
# ============================================================

def test_ga_finds_hand_computed_optimum():
    """Même mini-instance que pour le décodeur : l'optimum est 8 h."""

    tasks = make_tasks([
        ("O1", [{"M1": 3.0}, {"M2": 2.0}], 20),
        ("O2", [{"M1": 2.0}, {"M2": 4.0}], 20),
    ])

    result = run_ga(Problem(tasks), population_size=20, generations=30, seed=0)

    assert result.best_makespan == 8.0


# ============================================================
# 3. PLANNINGS VALIDES (avec pannes et calendriers)
# ============================================================

def test_ga_returns_valid_schedules():
    for seed in range(4):

        tasks = random_instance(seed)
        unavailability = {"M1": [(3.0, 6.0), (20.0, 24.0)], "M3": [(0.0, 4.0)]}

        schedule = optimize_schedule_ga(
            tasks,
            time_limit=None,
            machine_unavailability=unavailability,
            seed=seed,
            population_size=40,
            generations=40,
        )

        assert_valid_schedule(schedule, tasks, unavailability)


# ============================================================
# 4. JAMAIS PIRE QUE LA SOLUTION DE DEPART (élitisme)
# ============================================================

def test_ga_never_worse_than_its_start_and_history_never_increases():
    for seed in range(4):

        tasks = random_instance(seed)
        problem = Problem(tasks)

        result = run_ga(problem, population_size=40, generations=40, seed=seed)

        history = result.history

        assert len(history) == result.generations_run + 1
        assert all(b <= a + 1e-9 for a, b in zip(history, history[1:]))
        assert result.best_makespan <= history[0] + 1e-9

        # Le Makespan annoncé = celui du planning renvoyé
        assert abs(result.schedule["end"].max() - result.best_makespan) <= 0.011


def test_ga_at_least_as_good_as_greedy_solution():
    """La solution gloutonne (machine la plus rapide + MWKR) est dans la
    population initiale ; avec élitisme le GA ne peut pas faire pire."""

    for seed in range(4):

        problem = Problem(random_instance(seed))

        greedy_os, greedy_ms = greedy_chromosome(
            problem, random.Random(seed), "fastest", noise=0.0
        )
        _, greedy_makespan = decode(problem, greedy_os, greedy_ms)

        result = run_ga(problem, population_size=40, generations=30, seed=seed)

        assert result.best_makespan <= greedy_makespan + 1e-9


# ============================================================
# 5. REPRODUCTIBILITE
# ============================================================

def test_same_seed_gives_same_result():
    tasks = random_instance(3)

    first = run_ga(Problem(tasks), population_size=30, generations=25, seed=7)
    second = run_ga(Problem(tasks), population_size=30, generations=25, seed=7)
    other = run_ga(Problem(tasks), population_size=30, generations=25, seed=8)

    assert first.history == second.history
    assert first.best_os == second.best_os
    assert first.best_ms == second.best_ms
    assert other.best_makespan >= 0  # une autre graine tourne aussi


# ============================================================
# 6. ARRETS : temps et stagnation
# ============================================================

def test_time_limit_is_respected():
    tasks = random_instance(1, n_orders=10)

    result = run_ga(
        Problem(tasks), population_size=100, generations=100000,
        seed=0, time_limit=0.6,
    )

    assert result.stopped_by == "time"
    assert result.elapsed < 3.0


def test_stagnation_stop():
    tasks = make_tasks([("O1", [{"M1": 3.0}], 20), ("O2", [{"M1": 2.0}], 20)])

    result = run_ga(
        Problem(tasks), population_size=10, generations=500,
        seed=0, stagnation_limit=5,
    )

    assert result.stopped_by == "stagnation"
    assert result.generations_run < 500


# ============================================================
# 7. COMPATIBILITE AVEC TON VRAI PROJET
# ============================================================

def test_ga_on_default_dataset_matches_project_format():
    from src.optimizer.optimizer import load_data, create_tasks, calculate_kpis

    orders, machines, operations = load_data()
    tasks = create_tasks(orders, operations)

    schedule = optimize_schedule_ga(
        tasks, time_limit=None, seed=0, population_size=40, generations=30
    )

    assert_valid_schedule(schedule, tasks)

    kpis = calculate_kpis(schedule, orders, machines)
    assert kpis["makespan"] > 0


# ============================================================
# 8. LE GA NE PEUT JAMAIS BATTRE L'OPTIMUM DU MILP
# ============================================================

def test_ga_never_beats_milp_optimum():
    """Sur 2 commandes de ton jeu par défaut, le MILP donne l'optimum exact.
    Si le GA trouve mieux, c'est qu'il y a un bug."""

    from src.optimizer.optimizer import load_data, create_tasks, optimize_schedule

    orders, _, operations = load_data()
    tasks = create_tasks(orders.head(2), operations)

    milp = optimize_schedule(tasks, time_limit=30)
    milp_makespan = float(milp["end"].max())

    result = run_ga(Problem(tasks), population_size=60, generations=60, seed=0)

    print(
        f"MILP optimal : {milp_makespan:.2f} h | "
        f"GA : {result.best_makespan:.2f} h "
        f"({result.evaluations} évaluations, {result.elapsed:.2f} s)"
    )

    assert result.best_makespan >= milp_makespan - 0.02
