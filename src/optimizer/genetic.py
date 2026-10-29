"""
Algorithme génétique pour le FJSP (Flexible Job Shop Scheduling Problem).

Un individu est un chromosome (OS, MS) décodé par decoder.py :
  - OS : ordre des opérations (liste d'order_id répétés)
  - MS : machine choisie pour chaque tâche
Son score (fitness) est le Makespan du planning décodé : plus petit = mieux.

Boucle principale, à chaque génération :
  1. On garde les meilleurs individus tels quels (élitisme)
  2. On choisit des parents par tournoi
  3. On les croise (POX pour OS, uniforme pour MS)
  4. On applique de petites mutations
  5. On décode les enfants pour calculer leur Makespan

Les opérateurs ne produisent que des chromosomes valides : aucune
réparation n'est nécessaire. Résultat reproductible avec une graine (seed).
"""

import random
import time
from dataclasses import dataclass, field

from src.optimizer.decoder import Problem, decode, random_chromosome, to_schedule
from src.optimizer.local_search import tabu_search


# ============================================================
# INDIVIDU
# ============================================================

class Individual:
    """Un chromosome (OS, MS) et son Makespan."""

    __slots__ = ("os", "ms", "makespan", "searched")

    def __init__(self, os_vector, ms, makespan, searched=False):
        self.os = os_vector
        self.ms = ms
        self.makespan = makespan
        self.searched = searched  # True si la recherche locale est déjà passée par là


# ============================================================
# INITIALISATION : solutions aléatoires + quelques solutions gloutonnes
# ============================================================

def greedy_chromosome(problem, rng, ms_mode="fastest", noise=0.0):
    """
    Solution construite avec des règles simples (bon point de départ).

    MS : "fastest" = machine la plus rapide pour chaque tâche ;
         "balanced" = machine qui minimise (charge actuelle + durée).
    OS : règle MWKR (Most Work Remaining) : on place en priorité
         la commande qui a le plus de travail restant.
    noise : bruit aléatoire (0 = aucune, 0.3 = ±30 %) pour diversifier.
    """

    # --- MS ---
    ms = {}

    if ms_mode == "balanced":
        load = {machine: 0.0 for machine in problem.machines}
        task_ids = list(problem.task_order)
        rng.shuffle(task_ids)

        for task_id in task_ids:
            durations = problem.durations[task_id]
            best = min(
                problem.compatible[task_id],
                key=lambda m: (load[m] + durations[m], rng.random()),
            )
            ms[task_id] = best
            load[best] += durations[best]
    else:
        for task_id in problem.task_order:
            durations = problem.durations[task_id]
            ms[task_id] = min(
                problem.compatible[task_id],
                key=lambda m: (durations[m], rng.random()),
            )

    # --- OS (MWKR) ---
    def work(task_id):
        return problem.durations[task_id][ms[task_id]]

    remaining = {
        order_id: sum(work(t) for t in task_ids)
        for order_id, task_ids in problem.order_tasks.items()
    }
    next_index = {order_id: 0 for order_id in problem.order_tasks}
    os_vector = []

    while len(os_vector) < sum(len(t) for t in problem.order_tasks.values()):

        candidates = [
            order_id for order_id, task_ids in problem.order_tasks.items()
            if next_index[order_id] < len(task_ids)
        ]

        chosen = max(
            candidates,
            key=lambda o: (
                remaining[o] * (1 + rng.uniform(-noise, noise)),
                rng.random(),
            ),
        )

        task_id = problem.order_tasks[chosen][next_index[chosen]]
        remaining[chosen] -= work(task_id)
        next_index[chosen] += 1
        os_vector.append(chosen)

    return os_vector, ms


# ============================================================
# OPERATEURS GENETIQUES
# ============================================================

def pox_crossover(parent1_os, parent2_os, order_ids, rng):
    """
    POX (Precedence preserving Order-based crossover) sur OS.

    On choisit au hasard un sous-ensemble de commandes. Enfant 1 garde
    les gènes de ce sous-ensemble à leur place dans le parent 1, et les
    autres positions sont remplies avec les autres gènes dans l'ordre du
    parent 2 (enfant 2 : l'inverse). Les comptages restent corrects.
    """

    if len(order_ids) >= 2:
        subset = set(rng.sample(order_ids, rng.randint(1, len(order_ids) - 1)))
    else:
        subset = set(order_ids)

    def build(keep_from, fill_from):
        fill = iter(g for g in fill_from if g not in subset)
        return [g if g in subset else next(fill) for g in keep_from]

    return build(parent1_os, parent2_os), build(parent2_os, parent1_os)


def uniform_crossover_ms(parent1_ms, parent2_ms, task_ids, rng):
    """Chaque tâche prend sa machine d'un parent ou de l'autre (50/50)."""

    child1, child2 = {}, {}

    for task_id in task_ids:
        if rng.random() < 0.5:
            child1[task_id] = parent1_ms[task_id]
            child2[task_id] = parent2_ms[task_id]
        else:
            child1[task_id] = parent2_ms[task_id]
            child2[task_id] = parent1_ms[task_id]

    return child1, child2


def mutate_os(os_vector, rng):
    """Échange deux positions de l'OS (valide par construction)."""

    if len(os_vector) < 2:
        return

    i, j = rng.sample(range(len(os_vector)), 2)
    os_vector[i], os_vector[j] = os_vector[j], os_vector[i]


def mutate_ms(ms, problem, rng):
    """Change la machine d'une tâche vers une autre machine compatible."""

    flexible = [t for t in problem.task_order if len(problem.compatible[t]) > 1]

    if not flexible:
        return

    task_id = rng.choice(flexible)
    others = [m for m in problem.compatible[task_id] if m != ms[task_id]]
    ms[task_id] = rng.choice(others)


def tournament(population, size, rng):
    """Le meilleur de `size` individus tirés au hasard."""

    return min(rng.sample(population, size), key=lambda ind: ind.makespan)


# ============================================================
# RESULTAT
# ============================================================

@dataclass
class GAResult:
    best_os: list
    best_ms: dict
    best_makespan: float
    schedule: object              # DataFrame, même format que le MILP
    history: list = field(default_factory=list)  # meilleur Makespan par génération
    generations_run: int = 0
    evaluations: int = 0
    elapsed: float = 0.0
    seed: int = 0
    stopped_by: str = "generations"   # "generations", "time" ou "stagnation"
    local_search_calls: int = 0       # nombre de recherches tabou lancées (0 = GA pur)


# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

def run_ga(
    problem,
    population_size=100,
    generations=300,
    crossover_rate=0.9,
    mutation_rate=0.2,
    tournament_size=3,
    elite_fraction=0.05,
    seed=0,
    time_limit=None,
    stagnation_limit=None,
    local_search_top=0,
    local_search_every=5,
    local_search_iterations=10,
    local_search_patience=5,
):
    """
    Lance l'algorithme génétique sur un Problem (decoder.py).

    time_limit       : arrêt après ce nombre de secondes (None = pas de limite)
    stagnation_limit : arrêt si le meilleur n'a pas progressé depuis ce
                       nombre de générations (None = jamais)

    Version mémétique (GA + recherche tabou) :
    local_search_top        : nombre d'individus améliorés par la recherche
                              tabou à chaque passage (0 = GA pur, sans
                              recherche locale)
    local_search_every      : un passage toutes les N générations
    local_search_iterations : itérations maximum de chaque recherche tabou
    local_search_patience   : arrêt de la recherche tabou si elle ne
                              progresse plus depuis N itérations

    La recherche tabou s'applique aux meilleurs individus pas encore
    améliorés ; le résultat remplace l'individu (apprentissage lamarckien).
    """

    rng = random.Random(seed)
    started = time.perf_counter()

    order_ids = list(problem.order_tasks.keys())
    task_ids = problem.task_order
    n_elite = max(1, int(round(elite_fraction * population_size)))
    tournament_size = min(tournament_size, population_size)

    evaluations = 0

    def evaluate(os_vector, ms):
        nonlocal evaluations
        evaluations += 1
        _, makespan = decode(problem, os_vector, ms, check=False)
        return Individual(os_vector, ms, makespan)

    # --- Population initiale ---
    population = []

    g_os, g_ms = greedy_chromosome(problem, rng, "fastest", noise=0.0)
    population.append(evaluate(g_os, g_ms))

    n_balanced = max(0, population_size // 5)

    while len(population) < population_size:
        if len(population) <= n_balanced:
            os_vector, ms = greedy_chromosome(problem, rng, "balanced", noise=0.3)
        else:
            os_vector, ms = random_chromosome(problem, rng)
        population.append(evaluate(os_vector, ms))

    population.sort(key=lambda ind: ind.makespan)

    history = [population[0].makespan]
    best_so_far = population[0].makespan
    stagnation = 0
    stopped_by = "generations"
    generations_run = 0
    local_search_calls = 0

    # --- Générations ---
    for _ in range(generations):

        if time_limit is not None and time.perf_counter() - started >= time_limit:
            stopped_by = "time"
            break

        if stagnation_limit is not None and stagnation >= stagnation_limit:
            stopped_by = "stagnation"
            break

        next_population = [
            Individual(list(ind.os), dict(ind.ms), ind.makespan, ind.searched)
            for ind in population[:n_elite]
        ]

        timed_out = False

        while len(next_population) < population_size:

            if (
                time_limit is not None
                and len(next_population) % 20 == 0
                and time.perf_counter() - started >= time_limit
            ):
                timed_out = True
                break

            parent1 = tournament(population, tournament_size, rng)
            parent2 = tournament(population, tournament_size, rng)

            if rng.random() < crossover_rate:
                os1, os2 = pox_crossover(parent1.os, parent2.os, order_ids, rng)
                ms1, ms2 = uniform_crossover_ms(parent1.ms, parent2.ms, task_ids, rng)
            else:
                os1, os2 = list(parent1.os), list(parent2.os)
                ms1, ms2 = dict(parent1.ms), dict(parent2.ms)

            for os_child, ms_child in ((os1, ms1), (os2, ms2)):

                if rng.random() < mutation_rate:
                    mutate_os(os_child, rng)

                if rng.random() < mutation_rate:
                    mutate_ms(ms_child, problem, rng)

                if len(next_population) < population_size:
                    next_population.append(evaluate(os_child, ms_child))

        if timed_out:
            stopped_by = "time"
            break

        population = sorted(next_population, key=lambda ind: ind.makespan)
        generations_run += 1

        # --- Recherche locale (tabou) sur les meilleurs individus ---
        if local_search_top > 0 and generations_run % local_search_every == 0:

            candidates = [ind for ind in population if not ind.searched]
            candidates = candidates[:local_search_top]

            for ind in candidates:

                remaining = None

                if time_limit is not None:
                    remaining = time_limit - (time.perf_counter() - started)
                    if remaining <= 0:
                        break

                new_os, new_ms, new_makespan, _ = tabu_search(
                    problem, ind.os, ind.ms, rng,
                    max_iterations=local_search_iterations,
                    patience=local_search_patience,
                    time_limit=remaining,
                )

                ind.os, ind.ms, ind.makespan = new_os, new_ms, new_makespan
                ind.searched = True
                local_search_calls += 1

            population.sort(key=lambda ind: ind.makespan)

        if population[0].makespan < best_so_far - 1e-9:
            best_so_far = population[0].makespan
            stagnation = 0
        else:
            stagnation += 1

        history.append(population[0].makespan)

    best = population[0]
    entries, makespan = decode(problem, best.os, best.ms)

    return GAResult(
        best_os=best.os,
        best_ms=best.ms,
        best_makespan=makespan,
        schedule=to_schedule(problem, entries),
        history=history,
        generations_run=generations_run,
        evaluations=evaluations,
        elapsed=time.perf_counter() - started,
        seed=seed,
        stopped_by=stopped_by,
        local_search_calls=local_search_calls,
    )


# ============================================================
# INTERFACE COMPATIBLE AVEC LE MILP
# ============================================================

def optimize_schedule_ga(
    tasks,
    time_limit=10,
    machine_unavailability=None,
    seed=0,
    return_details=False,
    **ga_params,
):
    """
    Même rôle que optimize_schedule (MILP) : tâches -> planning (DataFrame
    au même format), mais par algorithme génétique.

    Solution approchée de bonne qualité, pas une preuve d'optimalité.
    return_details=True renvoie aussi le GAResult (historique, temps...).
    """

    problem = Problem(tasks, machine_unavailability)

    result = run_ga(
        problem,
        seed=seed,
        time_limit=time_limit,
        **ga_params,
    )

    if return_details:
        return result.schedule, result

    return result.schedule
