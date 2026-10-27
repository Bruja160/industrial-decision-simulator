"""
Convertit une instance benchmark Brandimarte au format JSON
(github.com/SchedulingLab/fjsp-instances) vers les 3 fichiers CSV
attendus par le projet (orders, machines, operations).

La colonne 'machine_durations' conserve la vraie durée par machine
(format "M1:3|M3:4"). La colonne 'duration' garde la moyenne, pour
rester compatible avec le MILP actuel.

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
    # OPERATIONS.CSV
    # ============================================================

    operations_path = output_dir / "operations.csv"
    job_total_durations = []

    with open(operations_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "operation_id", "product_id", "operation_type",
            "duration", "compatible_machines", "machine_durations"
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

                machine_durations = "|".join(
                    f"M{o['machine'] + 1}:{o['processing']}" for o in options
                )

                writer.writerow([
                    operation_id, product_id, operation_type,
                    round(avg_duration, 3), compatible_machines,
                    machine_durations
                ])

            job_total_durations.append(total_duration)

    # ============================================================
    # ORDERS.CSV
    # ============================================================
    # Deadline synthétique = 1.5x la durée totale (moyenne) du job.

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