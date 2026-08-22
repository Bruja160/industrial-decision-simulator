"""
Convertit une instance benchmark Brandimarte au format JSON
(github.com/SchedulingLab/fjsp-instances) vers les 3 fichiers CSV
attendus par le projet (orders, machines, operations).

Format source (JSON) :
{
  "machines": 6,
  "jobs": [
    [                                   # job 1
      [ {"machine": 0, "processing": 5}, {"machine": 2, "processing": 4} ],
      [ {"machine": 4, "processing": 3}, ... ],
      ...
    ],
    [ ... ],                           # job 2
    ...
  ]
}

IMPORTANT - Limitation assumee (a mentionner dans ton README) :
Le vrai format FJSP autorise une duree DIFFERENTE selon la machine choisie
pour une operation. Ton optimizer.py actuel utilise UNE seule duree par
operation, quelle que soit la machine. Ce script prend donc la MOYENNE
des durees possibles comme duree nominale. C'est une simplification
honnete a assumer, et une piste d'amelioration naturelle pour la suite.

Usage :
    python convert_benchmark.py data/benchmark/mk01.json data/
"""

import sys
import csv
import json
from pathlib import Path


def convert_to_csv(json_path, output_dir, instance_name="mk01"):

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(json_path, "r") as f:
        instance = json.load(f)

    n_machines = instance["machines"]
    jobs = instance["jobs"]

    # ============================================================
    # MACHINES.CSV
    # ============================================================

    machines_path = output_dir / "machines.csv"

    with open(machines_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["machine_id", "machine_name", "capacity_hours_per_day"])

        for m in range(n_machines):
            writer.writerow([f"M{m + 1}", f"Machine_{m + 1}", 8])

    # ============================================================
    # OPERATIONS.CSV + calcul des durees totales par job (pour deadline)
    # ============================================================

    operations_path = output_dir / "operations.csv"
    job_total_durations = []

    with open(operations_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "operation_id", "product_id", "operation_type",
            "duration", "compatible_machines"
        ])

        for job_index, operations in enumerate(jobs):
            product_id = f"P{job_index + 1}"
            total_duration = 0.0

            for op_index, options in enumerate(operations):
                operation_id = f"OP{job_index + 1}_{op_index + 1}"
                operation_type = f"Etape_{op_index + 1}"

                avg_duration = sum(o["processing"] for o in options) / len(options)
                total_duration += avg_duration

                compatible_machines = "|".join(
                    f"M{o['machine'] + 1}" for o in options
                )

                writer.writerow([
                    operation_id, product_id, operation_type,
                    round(avg_duration, 3), compatible_machines
                ])

            job_total_durations.append(total_duration)

    # ============================================================
    # ORDERS.CSV
    # ============================================================
    # Le benchmark n'a pas de notion de deadline (son seul objectif est
    # le makespan). On ajoute une deadline synthetique = 1.5x la duree
    # totale du job, pour que le KPI "retard" reste significatif.

    orders_path = output_dir / "orders.csv"

    with open(orders_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "product_id", "quantity", "deadline"])

        for job_index, total_duration in enumerate(job_total_durations):
            order_id = f"O{job_index + 1:02d}"
            product_id = f"P{job_index + 1}"
            deadline = round(total_duration * 1.5, 1)

            writer.writerow([order_id, product_id, 1, deadline])

    print(f"Conversion terminee pour l'instance '{instance_name}' :")
    print(f"  {machines_path} ({n_machines} machines)")
    print(f"  {operations_path} ({sum(len(j) for j in jobs)} operations)")
    print(f"  {orders_path} ({len(jobs)} commandes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python convert_benchmark.py <fichier.json> <dossier_sortie>")
        sys.exit(1)

    json_file = sys.argv[1]
    output_directory = sys.argv[2]

    convert_to_csv(json_file, output_directory)