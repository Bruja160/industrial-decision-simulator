"""
Tests de la recherche tabou (src/optimizer/local_search.py).

Garanties testées : jamais pire que le départ, solutions valides, améliore
réellement de mauvaises solutions, respecte pannes et limites de temps,
reproductible avec la même graine.
"""

import random
import time

import pandas as pd

from src.optimizer.decoder import (
    SCHEDULE_COLUMNS,
    Problem,
    check_chromosome,
    decode,
    random_chromosome,
    to_schedule,
)
from src.optimizer.local_search import (
    _apply_move,
    _build_indexes,
    _candidate_moves,
    _task_sequence,
    critical_path,
    tabu_search,
)


# ============================================================
# OUTILS
# ============================================================

def make_tasks(spec):
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
                assert row["start"] >= previous_end - 1e-9
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
                )


# ============================================================
# 1. CHEMIN CRITIQUE (cas calculé à la main)
# ============================================================

def test_critical_path_on_hand_case():
    """
    O1 : A sur M1 (3h) puis B sur M2 (2h) ; O2 : A sur M1 (2h) puis B sur M2 (4h).
    OS = O1, O1, O2, O2 : O1.A 0-3, O1.B 3-5, O2.A 3-5, O2.B 5-9.
    Makespan 9 : le chemin critique finit par O2.B et remonte à O1.B ou O2.A,
    puis à O1.A (tout est enchaîné sans temps mort).
    """

    tasks = make_tasks([
        ("O1", [{"M1": 3.0}, {"M2": 2.0}], 20),
        ("O2", [{"M1": 2.0}, {"M2": 4.0}], 20),
    ])

    problem = Problem(tasks)
    ms = {t: problem.compatible[t][0] for t in problem.task_order}

    entries, makespan = decode(problem, ["O1", "O1", "O2", "O2"], ms)
    assert makespan == 9.0

    critical, machine_sequence = critical_path(problem, entries, makespan, random.Random(0))

    assert critical[0] == "O2_OP2"
    assert "O1_OP1" in critical
    assert set(critical) <= set(problem.task_order)
    assert machine_sequence["M1"] == ["O1_OP1", "O2_OP1"]


# ============================================================
# 1 bis. LE CHEMIN CRITIQUE EST UNE VRAIE CHAINE SANS TEMPS MORT
# ============================================================

def test_critical_path_is_a_tight_chain():
    """Le chemin critique finit au Makespan et chaque tâche commence
    exactement quand la précédente du chemin se termine."""

    for seed in range(6):

        tasks = random_instance(seed)
        unavailability = {"M1": [(3.0, 6.0)], "M3": [(0.0, 4.0)]}
        problem = Problem(tasks, unavailability)
        rng = random.Random(seed)

        for _ in range(10):
            os_vector, ms = random_chromosome(problem, rng)
            entries, makespan = decode(problem, os_vector, ms)
            by_task = {e["task_id"]: e for e in entries}

            critical, _ = critical_path(problem, entries, makespan, rng)

            assert len(critical) == len(set(critical))
            assert abs(by_task[critical[0]]["end"] - makespan) <= 1e-9

            for later, earlier in zip(critical, critical[1:]):
                assert abs(by_task[earlier]["end"] - by_task[later]["start"]) <= 1e-9


# ============================================================
# 1 ter. LES MOUVEMENTS NE CASSENT JAMAIS LA GAMME
# ============================================================

def test_moves_never_break_precedence():
    """Après n'importe quel mouvement, les tâches d'une commande restent
    dans l'ordre de leur gamme, et la séquence reste une permutation."""

    for seed in range(5):

        problem = Problem(random_instance(seed))
        rng = random.Random(seed)
        indexes = _build_indexes(problem)

        for _ in range(10):
            os_vector, ms = random_chromosome(problem, rng)
            entries, makespan = decode(problem, os_vector, ms)
            critical, machine_sequence = critical_path(problem, entries, makespan, rng)
            sequence = _task_sequence(problem, os_vector)

            for move in _candidate_moves(problem, ms, critical, machine_sequence):

                applied = _apply_move(problem, indexes, sequence, ms, move)

                if applied is None:
                    continue

                new_sequence, new_ms = applied

                assert sorted(new_sequence) == sorted(sequence)

                position = {t: i for i, t in enumerate(new_sequence)}
                for task_ids in problem.order_tasks.values():
                    for before, after in zip(task_ids, task_ids[1:]):
                        assert position[before] < position[after]

                for task_id, machine in new_ms.items():
                    assert machine in problem.compatible[task_id]


# ============================================================
# 2. TROUVE L'OPTIMUM A PARTIR D'UNE MAUVAISE SOLUTION
# ============================================================

def test_tabu_fixes_a_bad_solution():
    """Départ à 9 h ; l'optimum calculé à la main est 8 h."""

    tasks = make_tasks([
        ("O1", [{"M1": 3.0}, {"M2": 2.0}], 20),
        ("O2", [{"M1": 2.0}, {"M2": 4.0}], 20),
    ])

    problem = Problem(tasks)
    ms = {t: problem.compatible[t][0] for t in problem.task_order}

    _, start_makespan = decode(problem, ["O1", "O1", "O2", "O2"], ms)
    assert start_makespan == 9.0

    _, _, best, _ = tabu_search(
        problem, ["O1", "O1", "O2", "O2"], ms, random.Random(0),
        max_iterations=30, patience=15,
    )

    assert best == 8.0


# ============================================================
# 3. JAMAIS PIRE, TOUJOURS VALIDE, MAKESPAN ANNONCE EXACT
# ============================================================

def test_tabu_never_worse_and_always_valid():
    for seed in range(6):

        tasks = random_instance(seed)
        unavailability = {"M1": [(3.0, 6.0), (20.0, 24.0)], "M3": [(0.0, 4.0)]}
        problem = Problem(tasks, unavailability)
        rng = random.Random(seed)

        for _ in range(5):
            os_vector, ms = random_chromosome(problem, rng)
            _, start_makespan = decode(problem, os_vector, ms)

            original_os, original_ms = list(os_vector), dict(ms)

            new_os, new_ms, new_makespan, _ = tabu_search(
                problem, os_vector, ms, rng, max_iterations=15, patience=8
            )

            # L'entrée n'est pas modifiée
            assert os_vector == original_os and ms == original_ms

            # Jamais pire
            assert new_makespan <= start_makespan + 1e-9

            # Chromosome valide et Makespan annoncé exact
            check_chromosome(problem, new_os, new_ms)
            entries, recomputed = decode(problem, new_os, new_ms)
            assert abs(recomputed - new_makespan) <= 1e-9

            assert_valid_schedule(to_schedule(problem, entries), tasks, unavailability)


# ============================================================
# 4. AMELIORE REELLEMENT DE MAUVAISES SOLUTIONS
# ============================================================

def test_tabu_improves_random_solutions():
    improved = 0
    total = 0

    for seed in range(5):
        tasks = random_instance(seed)
        problem = Problem(tasks)
        rng = random.Random(seed)

        for _ in range(4):
            os_vector, ms = random_chromosome(problem, rng)
            _, start_makespan = decode(problem, os_vector, ms)

            _, _, new_makespan, _ = tabu_search(
                problem, os_vector, ms, rng, max_iterations=30, patience=15
            )

            total += 1
            if new_makespan < start_makespan - 1e-9:
                improved += 1

    # Des solutions aléatoires sont presque toujours améliorables
    assert improved >= 0.8 * total, f"{improved}/{total} améliorées"


# ============================================================
# 5. REPRODUCTIBILITE
# ============================================================

def test_tabu_is_reproducible():
    problem = Problem(random_instance(2))
    os_vector, ms = random_chromosome(problem, random.Random(5))

    first = tabu_search(problem, os_vector, ms, random.Random(9), max_iterations=15)
    second = tabu_search(problem, os_vector, ms, random.Random(9), max_iterations=15)

    assert first == second


# ============================================================
# 6. LIMITES : itérations et temps
# ============================================================

def test_iteration_and_time_limits():
    problem = Problem(random_instance(1, n_orders=10))
    os_vector, ms = random_chromosome(problem, random.Random(0))

    _, _, _, iterations = tabu_search(
        problem, os_vector, ms, random.Random(0), max_iterations=3, patience=100
    )
    assert iterations <= 3

    started = time.perf_counter()
    tabu_search(
        problem, os_vector, ms, random.Random(0),
        max_iterations=10**6, patience=10**6, time_limit=0.3,
    )
    assert time.perf_counter() - started < 2.0


# ============================================================
# 7. SUR TON VRAI JEU DE DONNEES
# ============================================================

def test_tabu_on_default_dataset():
    from src.optimizer.optimizer import load_data, create_tasks

    orders, _, operations = load_data()
    tasks = create_tasks(orders, operations)
    problem = Problem(tasks)
    rng = random.Random(0)

    os_vector, ms = random_chromosome(problem, rng)
    _, start_makespan = decode(problem, os_vector, ms)

    new_os, new_ms, new_makespan, _ = tabu_search(
        problem, os_vector, ms, rng, max_iterations=20, patience=10
    )

    assert new_makespan <= start_makespan + 1e-9

    entries, _ = decode(problem, new_os, new_ms)
    assert_valid_schedule(to_schedule(problem, entries), tasks)


# ============================================================
# 8. JAMAIS MEILLEUR QUE L'OPTIMUM EXACT DU MILP
# ============================================================

def test_tabu_never_beats_milp_optimum():
    from src.optimizer.optimizer import load_data, create_tasks, optimize_schedule

    orders, _, operations = load_data()
    tasks = create_tasks(orders.head(2), operations)

    milp = optimize_schedule(tasks, time_limit=30)
    milp_makespan = float(milp["end"].max())

    problem = Problem(tasks)
    rng = random.Random(0)

    best = min(
        tabu_search(problem, *random_chromosome(problem, rng), rng,
                    max_iterations=30, patience=10)[2]
        for _ in range(20)
    )

    print(f"MILP optimal : {milp_makespan:.2f} h | meilleur tabou : {best:.2f} h")

    assert best >= milp_makespan - 0.02
