"""
Décodeur FJSP : transforme une solution candidate (chromosome) en planning.

Un chromosome est composé de deux parties :

  - OS (Operation Sequence) : liste d'order_id. Chaque commande apparaît
    autant de fois qu'elle a d'opérations. La k-ième apparition d'une
    commande correspond à sa k-ième opération. Les contraintes de gamme
    sont donc respectées automatiquement, sans réparation.

  - MS (Machine Selection) : dictionnaire {task_id: machine}, la machine
    choisie parmi les machines compatibles de chaque tâche.

Le décodeur lit OS de gauche à droite et place chaque opération au plus tôt
sur sa machine, dans le premier trou disponible, en évitant :
  - les tâches déjà placées sur cette machine,
  - les fenêtres d'indisponibilité (pannes, calendriers d'équipes).

Ce module ne dépend ni de PuLP ni de Streamlit : il lit seulement le
DataFrame de tâches produit par create_tasks().
"""

import bisect
import random
from itertools import chain

import pandas as pd


EPS = 1e-9

# Mêmes colonnes, dans le même ordre, que le planning renvoyé par le MILP
# (optimize_schedule) : KPI, Gantt, scénarios et Monte Carlo restent valables.
SCHEDULE_COLUMNS = [
    "task_id",
    "order_id",
    "product_id",
    "operation_id",
    "operation_type",
    "machine",
    "start",
    "end",
    "duration",
    "deadline",
]


# ============================================================
# DONNEES DU PROBLEME
# ============================================================

def _task_durations(task):
    """
    {machine: durée} d'une tâche. Si la colonne machine_durations est
    absente ou vide, toutes les machines compatibles prennent "duration"
    (même règle que le MILP).
    """

    durations = task["machine_durations"] if "machine_durations" in task else None

    if isinstance(durations, dict) and durations:
        return durations

    return {
        machine: float(task["duration"])
        for machine in task["compatible_machines"]
    }


class Problem:
    """
    Données du problème, calculées une seule fois à partir du DataFrame
    de tâches (create_tasks). Le décodeur est appelé des milliers de fois
    par un algorithme génétique : on évite de refaire ces calculs.
    """

    def __init__(self, tasks, machine_unavailability=None):

        records = tasks.to_dict("records")

        self.records = {record["task_id"]: record for record in records}
        self.task_order = [record["task_id"] for record in records]

        self.durations = {}
        self.compatible = {}

        for record in records:
            self.durations[record["task_id"]] = _task_durations(record)
            self.compatible[record["task_id"]] = list(
                record["compatible_machines"]
            )

        # order_id -> [task_id dans l'ordre de la gamme]
        by_order = {}

        for record in records:
            by_order.setdefault(record["order_id"], []).append(record)

        self.order_tasks = {
            order_id: [
                r["task_id"]
                for r in sorted(order_records, key=lambda r: r["operation_number"])
            ]
            for order_id, order_records in by_order.items()
        }

        # Fenêtres d'indisponibilité, triées, par machine
        self.unavailability = {
            machine: sorted((float(s), float(e)) for s, e in windows)
            for machine, windows in (machine_unavailability or {}).items()
        }

        self.machines = sorted(
            {m for ms in self.compatible.values() for m in ms}
            | set(self.unavailability)
        )


# ============================================================
# PLACEMENT AU PLUS TOT
# ============================================================

def _earliest_start(busy, windows, ready, duration):
    """
    Premier instant t >= ready tel que [t, t + duration] ne chevauche
    aucune tâche déjà placée (busy) ni aucune fenêtre d'indisponibilité.
    Deux intervalles qui se touchent (fin = début) ne se chevauchent pas.
    """

    blocked = sorted(chain(busy, windows))

    t = ready

    for block_start, block_end in blocked:

        if block_end <= t + EPS:
            continue  # ce bloc est entièrement avant t

        if block_start >= t + duration - EPS:
            break  # la tâche tient avant ce bloc : trou trouvé

        t = block_end  # chevauchement : on repousse après le bloc

    return t


# ============================================================
# VERIFICATION D'UN CHROMOSOME
# ============================================================

def check_chromosome(problem, os_vector, ms):
    """Lève ValueError si le chromosome est invalide."""

    expected = {
        order_id: len(task_ids)
        for order_id, task_ids in problem.order_tasks.items()
    }

    counts = {}

    for order_id in os_vector:

        if order_id not in expected:
            raise ValueError(f"OS : commande inconnue '{order_id}'")

        counts[order_id] = counts.get(order_id, 0) + 1

    for order_id, expected_count in expected.items():

        if counts.get(order_id, 0) != expected_count:
            raise ValueError(
                f"OS : la commande '{order_id}' doit apparaître "
                f"{expected_count} fois, elle apparaît "
                f"{counts.get(order_id, 0)} fois"
            )

    for task_id in problem.task_order:

        if task_id not in ms:
            raise ValueError(f"MS : aucune machine choisie pour '{task_id}'")

        if ms[task_id] not in problem.compatible[task_id]:
            raise ValueError(
                f"MS : la machine '{ms[task_id]}' n'est pas compatible "
                f"avec la tâche '{task_id}' "
                f"(compatibles : {problem.compatible[task_id]})"
            )


# ============================================================
# DECODEUR
# ============================================================

def decode(problem, os_vector, ms, check=True):
    """
    Transforme un chromosome (os_vector, ms) en planning.

    Retourne (entries, makespan) :
      - entries : liste de dict {task_id, machine, start, end}
      - makespan : date de fin de la dernière tâche
    """

    if check:
        check_chromosome(problem, os_vector, ms)

    next_operation = {order_id: 0 for order_id in problem.order_tasks}
    order_ready = {order_id: 0.0 for order_id in problem.order_tasks}
    busy = {machine: [] for machine in problem.machines}

    entries = []

    for order_id in os_vector:

        index = next_operation[order_id]
        next_operation[order_id] += 1

        task_id = problem.order_tasks[order_id][index]
        machine = ms[task_id]
        duration = problem.durations[task_id][machine]

        start = _earliest_start(
            busy[machine],
            problem.unavailability.get(machine, []),
            order_ready[order_id],
            duration,
        )

        end = start + duration

        bisect.insort(busy[machine], (start, end))
        order_ready[order_id] = end

        entries.append({
            "task_id": task_id,
            "machine": machine,
            "start": start,
            "end": end,
        })

    makespan = max(entry["end"] for entry in entries)

    return entries, makespan


# ============================================================
# CONVERSION EN PLANNING (MEME FORMAT QUE LE MILP)
# ============================================================

def to_schedule(problem, entries):
    """DataFrame au même format que optimize_schedule (MILP)."""

    by_task = {entry["task_id"]: entry for entry in entries}

    rows = []

    for task_id in problem.task_order:

        record = problem.records[task_id]
        entry = by_task[task_id]

        rows.append({
            "task_id": task_id,
            "order_id": record["order_id"],
            "product_id": record["product_id"],
            "operation_id": record["operation_id"],
            "operation_type": record["operation_type"],
            "machine": entry["machine"],
            "start": round(entry["start"], 2),
            "end": round(entry["end"], 2),
            "duration": round(
                float(problem.durations[task_id][entry["machine"]]), 2
            ),
            "deadline": record["deadline"],
        })

    return pd.DataFrame(rows, columns=SCHEDULE_COLUMNS)


def schedule_from_chromosome(
    tasks, os_vector, ms, machine_unavailability=None
):
    """Raccourci : tâches + chromosome -> planning (DataFrame)."""

    problem = Problem(tasks, machine_unavailability)
    entries, _ = decode(problem, os_vector, ms)

    return to_schedule(problem, entries)


# ============================================================
# CHROMOSOME ALEATOIRE (utile pour les tests et l'initialisation)
# ============================================================

def random_chromosome(problem, rng=None):
    """
    Chromosome valide tiré au hasard.
    rng : instance de random.Random (pour la reproductibilité).
    """

    rng = rng or random.Random()

    os_vector = [
        order_id
        for order_id, task_ids in problem.order_tasks.items()
        for _ in task_ids
    ]

    rng.shuffle(os_vector)

    ms = {
        task_id: rng.choice(problem.compatible[task_id])
        for task_id in problem.task_order
    }

    return os_vector, ms
