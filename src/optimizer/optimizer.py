from pathlib import Path

import pandas as pd

from pulp import (
    LpMinimize,
    LpProblem,
    LpStatus,
    LpVariable,
    PULP_CBC_CMD,
    lpSum,
    value,
)

from src.analysis.scenario_analysis import compare_scenarios
from src.analysis.scenario_generator import create_scenario


# ============================================================
# CHEMINS DU PROJET
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

ORDERS_FILE = ROOT / "data" / "orders.csv"
MACHINES_FILE = ROOT / "data" / "machines.csv"
OPERATIONS_FILE = ROOT / "data" / "operations.csv"


# ============================================================
# PARAMETRES D'OPTIMISATION
# ============================================================
#
# Choix : objectif pur Makespan (DELAY_WEIGHT = 0).
#
# Justification : la version pondérée (Makespan + retard) a révélé une
# instabilité numérique du solveur liée à la formulation big-M (des
# scénarios strictement dominants pouvaient être classés comme
# "moins bons" par CBC malgré un statut "Optimal"). L'objectif pur
# Makespan élimine cette instabilité et donne des résultats fiables
# et reproductibles à 100%. Le retard, le taux de respect des délais
# et le goulot restent calculés et affichés (calculate_kpis) à titre
# d'indicateurs de suivi, ils ne pilotent simplement plus l'optimisation.
#
# Piste d'évolution possible : réintroduire un objectif multi-critères
# avec un big-M resserré (borne par tâche plutôt que globale) pour
# stabiliser numériquement la version pondérée.

MAKESPAN_WEIGHT = 1.0
DELAY_WEIGHT = 0.0
SOLVER_TIME_LIMIT = 300


# ============================================================
# CHARGEMENT DES DONNEES
# ============================================================

def load_data():

    print()
    print("=== CHARGEMENT DES DONNEES ===")

    if not ORDERS_FILE.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {ORDERS_FILE}"
        )

    if not MACHINES_FILE.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {MACHINES_FILE}"
        )

    if not OPERATIONS_FILE.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {OPERATIONS_FILE}"
        )

    orders = pd.read_csv(ORDERS_FILE)
    machines = pd.read_csv(MACHINES_FILE)
    operations = pd.read_csv(OPERATIONS_FILE)

    return orders, machines, operations


# ============================================================
# CREATION DES TACHES
# ============================================================

def create_tasks(orders, operations):

    tasks = []

    for _, order in orders.iterrows():

        product_operations = operations[
            operations["product_id"]
            == order["product_id"]
        ].reset_index(drop=True)

        for operation_number, (_, operation) in enumerate(
            product_operations.iterrows(),
            start=1
        ):

            compatible_machines = [
                machine.strip()
                for machine in str(
                    operation["compatible_machines"]
                ).split("|")
            ]

            duration = (
                float(order["quantity"])
                * float(operation["duration"])
            )

            tasks.append({

                "task_id":
                    f"{order['order_id']}_"
                    f"{operation['operation_id']}",

                "order_id":
                    order["order_id"],

                "product_id":
                    order["product_id"],

                "operation_number":
                    operation_number,

                "operation_id":
                    operation["operation_id"],

                "operation_type":
                    operation["operation_type"],

                "quantity":
                    float(order["quantity"]),

                "duration":
                    duration,

                "compatible_machines":
                    compatible_machines,

                "deadline":
                    float(order["deadline"]),
            })

    return pd.DataFrame(tasks)


# ============================================================
# OPTIMISATION
# ============================================================

def optimize_schedule(tasks, time_limit=None):
    """
    time_limit : permet de forcer une limite de temps différente de
    SOLVER_TIME_LIMIT pour un appel donné (utilisé par l'analyse
    Monte Carlo, qui lance de nombreuses résolutions courtes plutôt
    qu'une seule résolution longue). Si None, comportement inchangé.
    """

    effective_time_limit = time_limit if time_limit is not None else SOLVER_TIME_LIMIT

    print()
    print("=== CONSTRUCTION DU MODELE ===")

    model = LpProblem(
        "Industrial_Decision_Simulator",
        LpMinimize
    )

    horizon = (
        float(tasks["duration"].sum())
        + 10
    )

    # --------------------------------------------------------
    # VARIABLES
    # --------------------------------------------------------

    start = {}
    end = {}
    machine_used = {}

    for _, task in tasks.iterrows():

        task_id = task["task_id"]
        duration = float(task["duration"])

        start[task_id] = LpVariable(
            f"start_{task_id}",
            lowBound=0,
            upBound=horizon
        )

        end[task_id] = LpVariable(
            f"end_{task_id}",
            lowBound=0,
            upBound=horizon
        )

        model += (
            end[task_id]
            == start[task_id] + duration
        )

        for machine in task["compatible_machines"]:

            machine_used[
                (task_id, machine)
            ] = LpVariable(
                f"use_{task_id}_{machine}",
                cat="Binary"
            )

        model += (
            lpSum(
                machine_used[
                    (task_id, machine)
                ]
                for machine in task["compatible_machines"]
            )
            == 1
        )

    # ========================================================
    # CONTRAINTES DE GAMME
    # ========================================================

    print(
        "Ajout des contraintes de gamme..."
    )

    for order_id in tasks["order_id"].unique():

        order_tasks = tasks[
            tasks["order_id"] == order_id
        ].sort_values(
            "operation_number"
        )

        task_ids = order_tasks[
            "task_id"
        ].tolist()

        for previous_task, next_task in zip(
            task_ids,
            task_ids[1:]
        ):

            model += (
                start[next_task]
                >= end[previous_task]
            )

    # ========================================================
    # CONTRAINTES MACHINES
    # ========================================================

    print(
        "Ajout des contraintes machines..."
    )

    big_m = horizon

    task_list = tasks.to_dict(
        "records"
    )

    for i in range(len(task_list)):

        task_a = task_list[i]
        id_a = task_a["task_id"]

        machines_a = set(
            task_a["compatible_machines"]
        )

        for j in range(i + 1, len(task_list)):

            task_b = task_list[j]
            id_b = task_b["task_id"]

            machines_b = set(
                task_b["compatible_machines"]
            )

            common_machines = (
                machines_a & machines_b
            )

            for machine in common_machines:

                assign_a = machine_used[
                    (id_a, machine)
                ]

                assign_b = machine_used[
                    (id_b, machine)
                ]

                order_ab = LpVariable(
                    f"order_{id_a}_{id_b}_{machine}",
                    cat="Binary"
                )

                model += (
                    start[id_b]
                    >= end[id_a]
                    - big_m * (
                        3
                        - assign_a
                        - assign_b
                        - order_ab
                    )
                )

                model += (
                    start[id_a]
                    >= end[id_b]
                    - big_m * (
                        2
                        - assign_a
                        - assign_b
                        + order_ab
                    )
                )

    # ========================================================
    # MAKESPAN
    # ========================================================

    makespan = LpVariable(
        "makespan",
        lowBound=0,
        upBound=horizon
    )

    for task_id in tasks["task_id"]:

        model += (
            makespan >= end[task_id]
        )

    # ========================================================
    # VARIABLES DE RETARD
    # ========================================================

    print(
        "Ajout des contraintes de retard..."
    )

    tardiness = {}

    for order_id in tasks["order_id"].unique():

        order_tasks = tasks[
            tasks["order_id"] == order_id
        ]

        order_task_ids = order_tasks[
            "task_id"
        ].tolist()

        deadline = float(
            order_tasks["deadline"].iloc[0]
        )

        tardiness[order_id] = LpVariable(
            f"tardiness_{order_id}",
            lowBound=0
        )

        last_task = order_task_ids[-1]

        model += (
            tardiness[order_id]
            >= end[last_task] - deadline
        )

    # ========================================================
    # OBJECTIF
    # ========================================================

    total_tardiness = lpSum(
        tardiness[order_id]
        for order_id in tardiness
    )

    objective = (
        MAKESPAN_WEIGHT * makespan
        +
        DELAY_WEIGHT * total_tardiness
    )

    model += objective

    # ========================================================
    # RESOLUTION
    # ========================================================

    print()
    print("=== LANCEMENT DU SOLVEUR ===")

    print(
        f"Objectif : "
        f"{MAKESPAN_WEIGHT} × Makespan "
        f"+ "
        f"{DELAY_WEIGHT} × Retard total"
    )

    print(
        f"Temps maximum : "
        f"{effective_time_limit} secondes"
    )

    solver = PULP_CBC_CMD(
        msg=True,
        timeLimit=effective_time_limit,
        gapRel=0.0  # précision exacte : essentiel pour la fiabilité des comparaisons de scénarios
    )

    status = model.solve(
        solver
    )

    print()
    print("=== RESULTAT ===")

    status_name = LpStatus[status]

    print(
        "Statut :",
        status_name
    )

    if status_name not in [
        "Optimal",
        "Integer Feasible"
    ]:

        print(
            "Aucune solution exploitable."
        )

        return None

    # ========================================================
    # VALEURS DE L'OBJECTIF
    # ========================================================

    makespan_value = value(
        makespan
    )

    total_tardiness_value = value(
        total_tardiness
    )

    print(
        f"Makespan : "
        f"{makespan_value:.2f} heures"
    )

    print(
        f"Retard total optimisé : "
        f"{total_tardiness_value:.2f} heures"
    )

    # ========================================================
    # CONSTRUCTION DU PLANNING
    # ========================================================

    results = []

    for _, task in tasks.iterrows():

        task_id = task["task_id"]

        selected_machine = None

        for machine in task[
            "compatible_machines"
        ]:

            machine_value = value(
                machine_used[
                    (task_id, machine)
                ]
            )

            if (
                machine_value is not None
                and machine_value > 0.5
            ):

                selected_machine = machine
                break

        start_value = value(
            start[task_id]
        )

        end_value = value(
            end[task_id]
        )

        results.append({

            "task_id":
                task_id,

            "order_id":
                task["order_id"],

            "product_id":
                task["product_id"],

            "operation_id":
                task["operation_id"],

            "operation_type":
                task["operation_type"],

            "machine":
                selected_machine,

            "start":
                round(
                    start_value,
                    2
                ),

            "end":
                round(
                    end_value,
                    2
                ),

            "duration":
                round(
                    float(task["duration"]),
                    2
                ),

            "deadline":
                task["deadline"],
        })

    return pd.DataFrame(
        results
    )


# ============================================================
# CALCUL DES KPI
# ============================================================

def calculate_kpis(
    schedule,
    orders,
    machines
):

    print()
    print("=== KPI DE PRODUCTION ===")

    # --------------------------------------------------------
    # MAKESPAN
    # --------------------------------------------------------

    makespan = float(
        schedule["end"].max()
    )

    print(
        f"Makespan : "
        f"{makespan:.2f} heures"
    )

    # --------------------------------------------------------
    # PERFORMANCE DES COMMANDES
    # --------------------------------------------------------

    order_results = []

    for order_id in orders[
        "order_id"
    ]:

        order_schedule = schedule[
            schedule["order_id"]
            == order_id
        ]

        completion_time = float(
            order_schedule["end"].max()
        )

        deadline = float(
            orders.loc[
                orders["order_id"]
                == order_id,
                "deadline"
            ].iloc[0]
        )

        delay = max(
            0,
            completion_time - deadline
        )

        order_results.append({

            "order_id":
                order_id,

            "completion_time":
                completion_time,

            "deadline":
                deadline,

            "delay":
                delay
        })

    order_kpis = pd.DataFrame(
        order_results
    )

    # --------------------------------------------------------
    # RETARD TOTAL
    # --------------------------------------------------------

    total_delay = float(
        order_kpis["delay"].sum()
    )

    # --------------------------------------------------------
    # COMMANDES EN RETARD
    # --------------------------------------------------------

    late_orders = int(
        (
            order_kpis["delay"] > 0
        ).sum()
    )

    total_orders = len(
        order_kpis
    )

    # --------------------------------------------------------
    # TAUX DE RESPECT
    # --------------------------------------------------------

    on_time_rate = (
        (
            total_orders
            - late_orders
        )
        /
        total_orders
        *
        100
    )

    print(
        f"Retard total : "
        f"{total_delay:.2f} heures"
    )

    print(
        f"Commandes en retard : "
        f"{late_orders} / "
        f"{total_orders}"
    )

    print(
        f"Taux de respect des délais : "
        f"{on_time_rate:.2f} %"
    )

    # --------------------------------------------------------
    # TABLEAU COMMANDES
    # --------------------------------------------------------

    print()
    print(
        "=== PERFORMANCE DES COMMANDES ==="
    )

    print(
        order_kpis.to_string(
            index=False
        )
    )

    # --------------------------------------------------------
    # UTILISATION DES MACHINES
    # --------------------------------------------------------

    print()
    print(
        "=== UTILISATION DES MACHINES ==="
    )

    machine_results = []

    for _, machine in machines.iterrows():

        machine_id = machine[
            "machine_id"
        ]

        machine_tasks = schedule[
            schedule["machine"]
            == machine_id
        ]

        workload = float(
            machine_tasks[
                "duration"
            ].sum()
        )

        utilization = (
            workload
            /
            makespan
            *
            100
        )

        machine_results.append({

            "machine_id":
                machine_id,

            "machine_name":
                machine[
                    "machine_name"
                ],

            "workload_hours":
                workload,

            "utilization_percent":
                utilization
        })

    machine_kpis = pd.DataFrame(
        machine_results
    )

    print(
        machine_kpis.to_string(
            index=False
        )
    )

    # --------------------------------------------------------
    # GOULOT
    # --------------------------------------------------------

    bottleneck = machine_kpis.loc[
        machine_kpis[
            "utilization_percent"
        ].idxmax()
    ]

    bottleneck_name = (
        f"{bottleneck['machine_id']} - "
        f"{bottleneck['machine_name']}"
    )

    print()
    print(
        "=== GOULOT DE PRODUCTION ==="
    )

    print(
        f"Machine : "
        f"{bottleneck_name}"
    )

    print(
        f"Utilisation : "
        f"{bottleneck['utilization_percent']:.2f} %"
    )

    return {

        "makespan":
            makespan,

        "total_delay":
            total_delay,

        "late_orders":
            late_orders,

        "total_orders":
            total_orders,

        "on_time_rate":
            on_time_rate,

        "orders":
            order_kpis,

        "machines":
            machine_kpis,

        "bottleneck":
            bottleneck_name
    }


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    try:

        # ====================================================
        # CHARGEMENT
        # ====================================================

        orders, machines, operations = (
            load_data()
        )

        # ====================================================
        # SITUATION ACTUELLE
        # ====================================================

        print()
        print("=" * 60)
        print("SITUATION ACTUELLE")
        print("=" * 60)

        tasks_baseline = create_tasks(
            orders,
            operations
        )

        print()
        print(
            f"Commandes : {len(orders)}"
        )

        print(
            f"Machines : {len(machines)}"
        )

        print(
            f"Taches : {len(tasks_baseline)}"
        )

        schedule_baseline = optimize_schedule(
            tasks_baseline
        )

        if schedule_baseline is None:
            return

        print()
        print(
            "=== PLANNING ACTUEL ==="
        )

        print(
            schedule_baseline
            .sort_values(
                [
                    "machine",
                    "start"
                ]
            )
            .to_string(
                index=False
            )
        )

        print()
        print(
            "=== KPI SITUATION ACTUELLE ==="
        )

        baseline_kpis = calculate_kpis(
            schedule_baseline,
            orders,
            machines
        )

        # ====================================================
        # SCENARIO WHAT-IF
        # ====================================================

        print()
        print("=" * 60)
        print("SCENARIO WHAT-IF")
        print("=" * 60)

        print()
        print(
            "Scénario : réduction de 10 % "
            "de la durée de OP03"
        )

        scenario_operations = create_scenario(
            operations,
            operation_id="OP03",
            duration_factor=0.90
        )

        # ====================================================
        # VERIFICATION DU SCENARIO
        # ====================================================

        original_duration = float(
            operations.loc[
                operations["operation_id"] == "OP03",
                "duration"
            ].iloc[0]
        )

        scenario_duration = float(
            scenario_operations.loc[
                scenario_operations["operation_id"] == "OP03",
                "duration"
            ].iloc[0]
        )

        print()
        print(
            f"Durée OP03 actuelle : "
            f"{original_duration:.3f}"
        )

        print(
            f"Durée OP03 scénario : "
            f"{scenario_duration:.3f}"
        )

        # ====================================================
        # OPTIMISATION DU SCENARIO
        # ====================================================

        print()
        print("=" * 60)
        print("OPTIMISATION DU SCENARIO")
        print("=" * 60)

        tasks_scenario = create_tasks(
            orders,
            scenario_operations
        )

        schedule_scenario = optimize_schedule(
            tasks_scenario
        )

        if schedule_scenario is None:
            return

        print()
        print(
            "=== PLANNING SCENARIO ==="
        )

        print(
            schedule_scenario
            .sort_values(
                [
                    "machine",
                    "start"
                ]
            )
            .to_string(
                index=False
            )
        )

        # ====================================================
        # KPI SCENARIO
        # ====================================================

        print()
        print(
            "=== KPI SCENARIO ==="
        )

        scenario_kpis = calculate_kpis(
            schedule_scenario,
            orders,
            machines
        )

        # ====================================================
        # COMPARAISON
        # ====================================================

        print()
        print("=" * 60)
        print("COMPARAISON DES SCENARIOS")
        print("=" * 60)

        comparison_result = compare_scenarios(
            baseline_kpis,
            scenario_kpis
        )

        # ====================================================
        # RESULTAT FINAL
        # ====================================================

        print()
        print("=" * 60)
        print("DECISION FINALE")
        print("=" * 60)

        print()
        print(
            f"Décision : "
            f"{comparison_result['recommendation']}"
        )

        print()

    except Exception as error:

        print()
        print(
            "=== ERREUR ==="
        )

        print(
            type(error).__name__
        )

        print(
            str(error)
        )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()