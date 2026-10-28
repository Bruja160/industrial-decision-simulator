"""
Lance l'algorithme génétique sur un dossier de 3 CSV (orders, machines,
operations) avec plusieurs graines, et affiche un résumé.

Usage :
    python benchmark_ga.py <dossier> [temps_en_secondes] [nombre_de_graines] [meilleur_connu]

Exemple (mk01, optimum connu = 40) :
    python benchmark_ga.py data/benchmark_csv_test 10 5 40
"""

import sys
from pathlib import Path

import pandas as pd

from src.optimizer.decoder import Problem
from src.optimizer.genetic import run_ga
from src.optimizer.optimizer import create_tasks


def main():

    if len(sys.argv) < 2:
        print(__doc__)
        return

    folder = Path(sys.argv[1])
    time_limit = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    n_seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    best_known = float(sys.argv[4]) if len(sys.argv) > 4 else None

    orders = pd.read_csv(folder / "orders.csv")
    operations = pd.read_csv(folder / "operations.csv")

    tasks = create_tasks(orders, operations)
    problem = Problem(tasks)

    print()
    print("=" * 60)
    print(f"Instance : {folder}")
    print(f"{len(orders)} commandes, {len(tasks)} tâches")
    print(f"Limite : {time_limit:g} s par graine, {n_seeds} graines")
    print("=" * 60)

    makespans = []

    for seed in range(n_seeds):

        result = run_ga(problem, seed=seed, time_limit=time_limit, generations=100000)
        makespans.append(result.best_makespan)

        print(
            f"graine {seed} : Makespan {result.best_makespan:7.2f} h | "
            f"{result.generations_run:5d} générations | "
            f"{result.evaluations:7d} évaluations | {result.elapsed:5.1f} s"
        )

    print("-" * 60)
    print(f"Meilleur : {min(makespans):.2f} h")
    print(f"Moyenne  : {sum(makespans) / len(makespans):.2f} h")
    print(f"Pire     : {max(makespans):.2f} h")

    if best_known:
        gap = (min(makespans) - best_known) / best_known * 100
        gap_mean = (sum(makespans) / len(makespans) - best_known) / best_known * 100
        print(f"Optimum connu : {best_known:g} h")
        print(f"Écart du meilleur : {gap:+.1f} %   |   écart de la moyenne : {gap_mean:+.1f} %")

    print()


if __name__ == "__main__":
    main()
