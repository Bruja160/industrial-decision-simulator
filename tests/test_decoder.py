"""
Tests du décodeur FJSP (src/optimizer/decoder.py).

Les tests 1 à 7 n'utilisent que des mini-instances construites à la main :
leurs résultats sont calculés à la main, indépendamment du décodeur.
Les tests 8 à 10 utilisent ton vrai jeu de données et ton MILP.
"""

import itertools
import random

import pandas as pd

from src.optimizer.decoder import (
    SCHEDULE_COLUMNS,
    Problem,
    check_chromosome,
    decode,
    random_chromosome,
    schedule_from_chromosome,
    to_schedule,
)


# ============================================================
# OUTILS
# ============================================================

def make_tasks(spec):
    """
    spec : liste de (order_id, [ {machine: durée, ...}, ... ], deadline)
    Chaque dict de la liste est une opération (durée par machine).
    """

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


def random_instance(seed, n_orders=6):
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
    """Vérifie un planning de façon indépendante du décodeur."""

    unavailability = unavailability or {}

    assert list(schedule.columns) == SCHEDULE_COLUMNS
    assert sorted(schedule["task_id"]) == sorted(tasks["task_id"])

    # Durée = durée de la machine choisie
    by_task = {t["task_id"]: t for t in tasks.to_dict("records")}
    for _, row in schedule.iterrows():
        expected = by_task[row["task_id"]]["machine_durations"][row["machine"]]
        assert abs((row["end"] - row["start"]) - expected) <= 0.011
        assert abs(row["duration"] - expected) <= 0.011

    # Pas de chevauchement sur une machine
    for machine, group in schedule.groupby("machine"):
        group = group.sort_values("start")
        previous_end = None
        for _, row in group.iterrows():
            if previous_end is not None:
                assert row["start"] >= previous_end - 1e-9, (
                    f"Chevauchement sur {machine}"
                )
            previous_end = row["end"]

    # Gamme respectée
    for order_id, group in tasks.groupby("order_id"):
        ordered = group.sort_values("operation_number")["task_id"].tolist()
        times = schedule.set_index("task_id")
        for before, after in zip(ordered, ordered[1:]):
            assert times.loc[after, "start"] >= times.loc[before, "end"] - 1e-9

    # Fenêtres d'indisponibilité respectées
    for machine, windows in unavailability.items():
        on_machine = schedule[schedule["machine"] == machine]
        for _, row in on_machine.iterrows():
            for window_start, window_end in windows:
                ok = (
                    row["end"] <= round(window_start, 2) + 1e-9
                    or row["start"] >= round(window_end, 2) - 1e-9
                )
                assert ok, f"{row['task_id']} chevauche une fenêtre sur {machine}"


# ============================================================
# 1. RESULTAT CALCULE A LA MAIN
# ============================================================

def test_decoder_reaches_hand_computed_optimum():
    """
    O1 : A sur M1 (3h) puis B sur M2 (2h)
    O2 : A sur M1 (2h) puis B sur M2 (4h)

    M2 doit faire 2 + 4 = 6h et ne peut pas démarrer avant 2h
    (la plus courte opération A finie). Donc Makespan >= 8, et
    O2.A (0-2), O1.A (2-5), O2.B (2-6), O1.B (6-8) atteint 8.
    """

    tasks = make_tasks([
        ("O1", [{"M1": 3.0}, {"M2": 2.0}], 20),
        ("O2", [{"M1": 2.0}, {"M2": 4.0}], 20),
    ])

    problem = Problem(tasks)
    ms = {t: problem.compatible[t][0] for t in problem.task_order}

    makespans = {
        tuple(os_vector): decode(problem, list(os_vector), ms)[1]
        for os_vector in set(itertools.permutations(["O1", "O1", "O2", "O2"]))
    }

    assert min(makespans.values()) == 8.0
    assert makespans[("O2", "O1", "O2", "O1")] == 8.0
    # Ordre défavorable : O1 d'abord sur M1 puis O2.A, puis O2.B en dernier
    assert makespans[("O1", "O1", "O2", "O2")] == 9.0


# ============================================================
# 2. INDISPONIBILITE (calculs à la main)
# ============================================================

def test_unavailability_pushes_task_after_window():
    """Tâche de 3h, machine indisponible de 1h à 2h : elle ne tient pas
    avant la fenêtre, donc elle démarre à 2h et finit à 5h."""

    tasks = make_tasks([("O1", [{"M1": 3.0}], 20)])

    schedule = schedule_from_chromosome(
        tasks, ["O1"], {"O1_OP1": "M1"},
        machine_unavailability={"M1": [(1.0, 2.0)]},
    )

    assert schedule.loc[0, "start"] == 2.0
    assert schedule.loc[0, "end"] == 5.0


def test_task_fits_before_window():
    """Tâche de 1h, fenêtre de 1h à 2h : elle tient juste avant."""

    tasks = make_tasks([("O1", [{"M1": 1.0}], 20)])

    schedule = schedule_from_chromosome(
        tasks, ["O1"], {"O1_OP1": "M1"},
        machine_unavailability={"M1": [(1.0, 2.0)]},
    )

    assert schedule.loc[0, "start"] == 0.0
    assert schedule.loc[0, "end"] == 1.0


# ============================================================
# 3. REMPLISSAGE DES TROUS
# ============================================================

def test_decoder_fills_gaps():
    """
    A : OP1 sur M2 (5h) puis OP2 sur M1 (1h)  -> OP2 sur M1 démarre à 5h
    B : OP1 sur M1 (2h), prête dès 0h.
    Avec OS = [A, A, B], B tient dans le trou 0-5 sur M1 : début à 0.
    """

    tasks = make_tasks([
        ("A", [{"M2": 5.0}, {"M1": 1.0}], 20),
        ("B", [{"M1": 2.0}], 20),
    ])

    schedule = schedule_from_chromosome(
        tasks, ["A", "A", "B"],
        {"A_OP1": "M2", "A_OP2": "M1", "B_OP1": "M1"},
    )

    b = schedule[schedule["task_id"] == "B_OP1"].iloc[0]
    assert b["start"] == 0.0 and b["end"] == 2.0


# ============================================================
# 4. DUREE DEPENDANTE DE LA MACHINE
# ============================================================

def test_duration_depends_on_chosen_machine():
    tasks = make_tasks([("O1", [{"M1": 5.0, "M2": 2.0}], 20)])

    on_m1 = schedule_from_chromosome(tasks, ["O1"], {"O1_OP1": "M1"})
    on_m2 = schedule_from_chromosome(tasks, ["O1"], {"O1_OP1": "M2"})

    assert on_m1.loc[0, "end"] == 5.0
    assert on_m2.loc[0, "end"] == 2.0


# ============================================================
# 5. CHROMOSOMES INVALIDES REFUSES
# ============================================================

def test_invalid_chromosomes_are_rejected():
    tasks = make_tasks([
        ("O1", [{"M1": 3.0}, {"M2": 2.0}], 20),
        ("O2", [{"M1": 2.0, "M3": 2.0}], 20),
    ])

    problem = Problem(tasks)
    good_ms = {"O1_OP1": "M1", "O1_OP2": "M2", "O2_OP1": "M1"}

    check_chromosome(problem, ["O1", "O1", "O2"], good_ms)  # valide

    bad_cases = [
        (["O1", "O2"], good_ms),                                  # opérations manquantes
        (["O1", "O1", "O1", "O2"], good_ms),                      # trop d'occurrences
        (["O1", "O1", "O9"], good_ms),                            # commande inconnue
        (["O1", "O1", "O2"], {**good_ms, "O2_OP1": "M2"}),        # machine incompatible
        (["O1", "O1", "O2"], {"O1_OP1": "M1"}),                   # machines manquantes
    ]

    for os_vector, ms in bad_cases:
        try:
            check_chromosome(problem, os_vector, ms)
        except ValueError:
            continue
        raise AssertionError(f"Chromosome invalide accepté : {os_vector}")


# ============================================================
# 6. PROPRIETES SUR DE NOMBREUX CHROMOSOMES ALEATOIRES
# ============================================================

def test_random_chromosomes_give_valid_schedules():
    for seed in range(5):

        tasks = random_instance(seed)
        unavailability = {
            "M1": [(3.0, 6.0), (20.0, 24.0)],
            "M3": [(0.0, 4.0)],
        }

        problem = Problem(tasks, unavailability)
        rng = random.Random(seed)

        for _ in range(60):
            os_vector, ms = random_chromosome(problem, rng)
            entries, makespan = decode(problem, os_vector, ms)
            schedule = to_schedule(problem, entries)

            assert_valid_schedule(schedule, tasks, unavailability)
            assert abs(schedule["end"].max() - makespan) <= 0.011


# ============================================================
# 7. REPRODUCTIBILITE
# ============================================================

def test_decoding_is_deterministic():
    tasks = random_instance(1)
    problem = Problem(tasks)

    os_vector, ms = random_chromosome(problem, random.Random(42))

    first = decode(problem, os_vector, ms)
    second = decode(problem, list(os_vector), dict(ms))

    assert first == second

    again = random_chromosome(problem, random.Random(42))
    assert again == (os_vector, ms)


# ============================================================
# 8. COMPATIBILITE AVEC TON VRAI PROJET (jeu de données par défaut)
# ============================================================

def test_decoder_on_default_dataset_matches_project_format():
    from src.optimizer.optimizer import load_data, create_tasks, calculate_kpis

    orders, machines, operations = load_data()
    tasks = create_tasks(orders, operations)

    problem = Problem(tasks)
    os_vector, ms = random_chromosome(problem, random.Random(0))

    entries, _ = decode(problem, os_vector, ms)
    schedule = to_schedule(problem, entries)

    assert_valid_schedule(schedule, tasks)

    # Le planning doit être directement utilisable par les KPI du projet
    kpis = calculate_kpis(schedule, orders, machines)
    assert kpis["makespan"] > 0
    assert 0 <= kpis["on_time_rate"] <= 100


# ============================================================
# 9. LE DECODEUR NE PEUT JAMAIS BATTRE L'OPTIMUM DU MILP
# ============================================================

def test_decoder_never_beats_milp_optimum():
    """
    Sur une petite instance (2 commandes de ton jeu par défaut), le MILP
    donne l'optimum exact. Aucun chromosome ne peut faire mieux : si c'est
    le cas, le décodeur contient un bug.
    """

    from src.optimizer.optimizer import load_data, create_tasks, optimize_schedule

    orders, _, operations = load_data()
    tasks = create_tasks(orders.head(2), operations)

    milp_schedule = optimize_schedule(tasks, time_limit=30)
    milp_makespan = float(milp_schedule["end"].max())

    problem = Problem(tasks)
    rng = random.Random(0)

    best = min(
        decode(problem, *random_chromosome(problem, rng), check=False)[1]
        for _ in range(2000)
    )

    print(f"MILP optimal : {milp_makespan:.2f} h | meilleur décodeur (2000 tirages) : {best:.2f} h")

    assert best >= milp_makespan - 0.02


# ============================================================
# 10. FENETRES D'INDISPONIBILITE SUR TON JEU PAR DEFAUT
# ============================================================

def test_decoder_respects_unavailability_on_default_dataset():
    from src.optimizer.optimizer import load_data, create_tasks

    orders, _, operations = load_data()
    tasks = create_tasks(orders, operations)

    unavailability = {"M2": [(5.0, 12.0)], "M4": [(0.0, 3.0), (20.0, 26.0)]}
    problem = Problem(tasks, unavailability)
    rng = random.Random(1)

    for _ in range(30):
        os_vector, ms = random_chromosome(problem, rng)
        entries, _ = decode(problem, os_vector, ms)
        schedule = to_schedule(problem, entries)
        assert_valid_schedule(schedule, tasks, unavailability)
