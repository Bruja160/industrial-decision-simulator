"""
Recherche tabou sur le chemin critique pour le FJSP.

Idée : à partir d'une solution (OS, MS), on calcule son planning, puis on
cherche le CHEMIN CRITIQUE (la chaîne d'opérations qui détermine le
Makespan). Seules ces opérations peuvent réduire le Makespan si on les
déplace. On teste donc uniquement des modifications autour d'elles :

  - changer la machine d'une opération critique ;
  - la placer juste avant la tâche qui la précède sur sa machine ;
  - la placer juste après la tâche qui la suit sur sa machine.

À chaque itération on prend le meilleur voisin non tabou, MÊME s'il est
moins bon que la solution actuelle : c'est ce qui permet de sortir des
impasses. Une liste tabou interdit de défaire un mouvement pendant quelques
itérations (sinon on tournerait en rond). Un mouvement tabou reste permis
s'il bat le meilleur résultat connu (critère d'aspiration).

La solution renvoyée n'est jamais pire que celle de départ.
"""

import time

from src.optimizer.decoder import EPS, decode


# ============================================================
# OUTILS : OS (ordre des commandes) <-> séquence de tâches
# ============================================================

def _task_sequence(problem, os_vector):
    """OS (liste d'order_id) -> liste de task_id dans le même ordre."""

    counters = {order_id: 0 for order_id in problem.order_tasks}
    sequence = []

    for order_id in os_vector:
        sequence.append(problem.order_tasks[order_id][counters[order_id]])
        counters[order_id] += 1

    return sequence


def _build_indexes(problem):
    """task_id -> (order_id, rang de l'opération dans la gamme)."""

    return {
        task_id: (order_id, rank)
        for order_id, task_ids in problem.order_tasks.items()
        for rank, task_id in enumerate(task_ids)
    }


# ============================================================
# CHEMIN CRITIQUE
# ============================================================

def critical_path(problem, entries, makespan, rng):
    """
    Renvoie (tâches critiques, séquence des tâches par machine).

    On part d'une tâche qui finit au Makespan et on remonte : à chaque
    pas, le prédécesseur est la tâche précédente de la commande, ou la
    tâche précédente sur la machine, si elle finit exactement au début de
    la tâche courante (aucun temps mort entre les deux).
    """

    by_task = {entry["task_id"]: entry for entry in entries}

    machine_sequence = {}

    for entry in sorted(entries, key=lambda e: (e["start"], e["end"])):
        machine_sequence.setdefault(entry["machine"], []).append(entry["task_id"])

    machine_pred = {}

    for tasks_on_machine in machine_sequence.values():
        for before, after in zip(tasks_on_machine, tasks_on_machine[1:]):
            machine_pred[after] = before

    job_pred = {}

    for task_ids in problem.order_tasks.values():
        for before, after in zip(task_ids, task_ids[1:]):
            job_pred[after] = before

    last_tasks = [
        task_id for task_id, entry in by_task.items()
        if abs(entry["end"] - makespan) <= EPS
    ]

    current = rng.choice(last_tasks)
    critical = []
    seen = set()

    while current is not None and current not in seen:

        seen.add(current)
        critical.append(current)

        start = by_task[current]["start"]
        candidates = []

        for predecessor in (job_pred.get(current), machine_pred.get(current)):
            if predecessor is not None and abs(by_task[predecessor]["end"] - start) <= EPS:
                candidates.append(predecessor)

        current = rng.choice(candidates) if candidates else None

    return critical, machine_sequence


# ============================================================
# VOISINAGE
# ============================================================

def _candidate_moves(problem, ms, critical, machine_sequence):
    """Liste de mouvements autour des tâches critiques."""

    moves = []

    for task_id in critical:

        machine = ms[task_id]

        for other in problem.compatible[task_id]:
            if other != machine:
                moves.append(("machine", task_id, other))

        on_machine = machine_sequence[machine]
        index = on_machine.index(task_id)

        if index > 0:
            moves.append(("before", task_id, on_machine[index - 1]))

        if index < len(on_machine) - 1:
            moves.append(("after", task_id, on_machine[index + 1]))

    return moves


def _apply_move(problem, indexes, sequence, ms, move):
    """
    Applique un mouvement. Renvoie (nouvelle séquence, nouvelle MS) ou
    None si le mouvement est impossible (gamme violée, rien ne change).
    """

    kind, task_id, target = move

    if kind == "machine":
        new_ms = dict(ms)
        new_ms[task_id] = target
        return sequence, new_ms

    new_sequence = list(sequence)
    new_sequence.remove(task_id)

    order_id, rank = indexes[task_id]
    order_tasks = problem.order_tasks[order_id]

    # La tâche doit rester après la précédente et avant la suivante
    # de sa commande (sinon la gamme serait violée).
    lowest = new_sequence.index(order_tasks[rank - 1]) + 1 if rank > 0 else 0
    highest = (
        new_sequence.index(order_tasks[rank + 1])
        if rank + 1 < len(order_tasks)
        else len(new_sequence)
    )

    position = new_sequence.index(target)

    if kind == "after":
        position += 1

    if position < lowest or position > highest:
        return None

    new_sequence.insert(position, task_id)

    if new_sequence == sequence:
        return None

    return new_sequence, ms


# ============================================================
# RECHERCHE TABOU
# ============================================================

def tabu_search(
    problem,
    os_vector,
    ms,
    rng,
    max_iterations=30,
    patience=10,
    tenure=7,
    time_limit=None,
):
    """
    Améliore une solution. Renvoie (os, ms, makespan, iterations).

    max_iterations : nombre maximum d'itérations
    patience       : arrêt si le meilleur n'a pas progressé depuis ce
                     nombre d'itérations
    tenure         : durée (en itérations) pendant laquelle un mouvement
                     est interdit
    time_limit     : limite de temps en secondes (None = aucune)
    """

    started = time.perf_counter()

    indexes = _build_indexes(problem)
    task_order = {task_id: order_id for task_id, (order_id, _) in indexes.items()}

    sequence = _task_sequence(problem, os_vector)
    ms = dict(ms)

    entries, makespan = decode(problem, os_vector, ms, check=False)

    best_sequence, best_ms, best_makespan = list(sequence), dict(ms), makespan

    tabu = {}
    since_improvement = 0
    iteration = 0

    for iteration in range(1, max_iterations + 1):

        if since_improvement >= patience:
            iteration -= 1
            break

        if time_limit is not None and time.perf_counter() - started >= time_limit:
            iteration -= 1
            break

        critical, machine_sequence = critical_path(problem, entries, makespan, rng)
        moves = _candidate_moves(problem, ms, critical, machine_sequence)

        chosen = None

        for move in moves:

            kind, task_id, target = move

            if kind == "machine":
                tabu_key = ("machine", task_id, target)
            elif kind == "before":
                tabu_key = ("order", task_id, target)
            else:
                tabu_key = ("order", target, task_id)

            is_tabu = tabu.get(tabu_key, 0) >= iteration

            applied = _apply_move(problem, indexes, sequence, ms, move)

            if applied is None:
                continue

            new_sequence, new_ms = applied
            new_os = [task_order[t] for t in new_sequence]
            new_entries, new_makespan = decode(problem, new_os, new_ms, check=False)

            if is_tabu and new_makespan >= best_makespan - 1e-9:
                continue  # interdit, sans aspiration

            if chosen is None or new_makespan < chosen[0] - 1e-9 or (
                abs(new_makespan - chosen[0]) <= 1e-9 and rng.random() < 0.5
            ):
                chosen = (new_makespan, new_sequence, new_ms, new_entries, move)

        if chosen is None:
            iteration -= 1
            break

        new_makespan, new_sequence, new_ms, new_entries, move = chosen

        kind, task_id, target = move
        expiry = iteration + tenure

        # Interdire de défaire ce mouvement pendant `tenure` itérations
        if kind == "machine":
            tabu[("machine", task_id, ms[task_id])] = expiry
        elif kind == "before":
            tabu[("order", target, task_id)] = expiry
        else:
            tabu[("order", task_id, target)] = expiry

        makespan, sequence, ms, entries = (
            new_makespan, new_sequence, new_ms, new_entries
        )

        if makespan < best_makespan - 1e-9:
            best_sequence, best_ms, best_makespan = list(sequence), dict(ms), makespan
            since_improvement = 0
        else:
            since_improvement += 1

    best_os = [task_order[t] for t in best_sequence]

    return best_os, best_ms, best_makespan, iteration
