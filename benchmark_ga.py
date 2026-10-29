"""
Lance l'algorithme génétique sur un dossier de 3 CSV (orders, machines,
operations) avec plusieurs graines, et affiche un résumé.

Usage :
    python benchmark_ga.py <dossier> [temps_en_secondes] [nombre_de_graines] [meilleur_connu] [options]

Options :
    --compare          compare GA pur, GA + tabou léger et GA + tabou renforcé
                       (mêmes graines, même temps pour chaque méthode)
    --ls-top N         recherche tabou sur N individus par passage (GA mémétique)
    --ls-every N       un passage toutes les N générations (défaut 5)
    --ls-iterations N  itérations maximum de chaque recherche tabou (défaut 10)

Exemples (mk01, optimum connu = 40) :
    python benchmark_ga.py data/benchmark_csv_test 10 5 40
    python benchmark_ga.py data/benchmark_csv_test 10 20 40 --compare
"""

import argparse
from pathlib import Path

import pandas as pd

from src.optimizer.decoder import Problem
from src.optimizer.genetic import run_ga
from src.optimizer.optimizer import create_tasks


VARIANTS = {
    "GA pur": dict(local_search_top=0),
    "GA + tabou léger": dict(
        local_search_top=1, local_search_every=5,
        local_search_iterations=10, local_search_patience=5,
    ),
    "GA + tabou renforcé": dict(
        local_search_top=3, local_search_every=10,
        local_search_iterations=15, local_search_patience=6,
    ),
}


def run_variant(problem, name, params, time_limit, n_seeds, best_known, verbose=True):
    """Lance une méthode sur n_seeds graines. Renvoie la liste des Makespans."""

    makespans = []

    if verbose:
        print()
        print(f"--- {name} ---")

    for seed in range(n_seeds):

        result = run_ga(
            problem, seed=seed, time_limit=time_limit, generations=100000, **params
        )
        makespans.append(result.best_makespan)

        if verbose:
            print(
                f"graine {seed:2d} : Makespan {result.best_makespan:7.2f} h | "
                f"{result.generations_run:5d} générations | "
                f"{result.evaluations:7d} évaluations | "
                f"{result.local_search_calls:3d} recherches tabou | "
                f"{result.elapsed:5.1f} s",
                flush=True,
            )

    return makespans


def summarize(name, makespans, best_known):

    mean = sum(makespans) / len(makespans)
    line = (
        f"{name:22s} meilleur {min(makespans):6.2f} | moyenne {mean:6.2f} | "
        f"pire {max(makespans):6.2f}"
    )

    if best_known:
        reached = sum(1 for m in makespans if m <= best_known + 1e-9)
        gap = (mean - best_known) / best_known * 100
        line += f" | écart moyenne {gap:+5.1f} % | optimum atteint {reached}/{len(makespans)}"

    return line


def main():

    parser = argparse.ArgumentParser(description="Benchmark de l'algorithme génétique")
    parser.add_argument("folder")
    parser.add_argument("time_limit", nargs="?", type=float, default=10.0)
    parser.add_argument("seeds", nargs="?", type=int, default=5)
    parser.add_argument("best_known", nargs="?", type=float, default=None)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--ls-top", type=int, default=0)
    parser.add_argument("--ls-every", type=int, default=5)
    parser.add_argument("--ls-iterations", type=int, default=10)
    args = parser.parse_args()

    folder = Path(args.folder)

    orders = pd.read_csv(folder / "orders.csv")
    operations = pd.read_csv(folder / "operations.csv")

    tasks = create_tasks(orders, operations)
    problem = Problem(tasks)

    print()
    print("=" * 78)
    print(f"Instance : {folder}")
    print(f"{len(orders)} commandes, {len(tasks)} tâches")
    print(f"Limite : {args.time_limit:g} s par graine, {args.seeds} graines")
    print("=" * 78)

    if args.compare:

        results = {}

        for name, params in VARIANTS.items():
            results[name] = run_variant(
                problem, name, params, args.time_limit, args.seeds, args.best_known
            )

        print()
        print("=" * 78)
        print("COMPARAISON (mêmes graines, même temps de calcul)")
        print("=" * 78)

        for name, makespans in results.items():
            print(summarize(name, makespans, args.best_known))

        print()
        return

    params = dict(local_search_top=args.ls_top)

    if args.ls_top > 0:
        params.update(
            local_search_every=args.ls_every,
            local_search_iterations=args.ls_iterations,
        )

    name = "GA mémétique" if args.ls_top > 0 else "GA pur"
    makespans = run_variant(
        problem, name, params, args.time_limit, args.seeds, args.best_known
    )

    print("-" * 78)
    print(summarize(name, makespans, args.best_known))
    print()


if __name__ == "__main__":
    main()
