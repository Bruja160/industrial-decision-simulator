"""
Tests du statut de résolution du MILP : "optimum prouvé" ou "limite de temps".

PuLP renvoie "Optimal" dès qu'une solution existe, même si CBC s'est arrêté
à la limite de temps. On ne déclare donc l'optimalité PROUVEE que si le
solveur a fini nettement avant cette limite.
"""

from src.optimizer.optimizer import solver_proved_optimal


def test_proved_optimal_when_solver_finishes_early():
    assert solver_proved_optimal("Optimal", solve_time=3.0, time_limit=120) is True
    assert solver_proved_optimal("Optimal", solve_time=100.0, time_limit=120) is True


def test_not_proved_when_time_limit_is_reached():
    # CBC s'arrête à 119,9 s sur une limite de 120 s : rien n'est prouvé
    assert solver_proved_optimal("Optimal", solve_time=119.9, time_limit=120) is False
    assert solver_proved_optimal("Optimal", solve_time=120.5, time_limit=120) is False


def test_not_proved_for_other_statuses():
    assert solver_proved_optimal("Not Solved", solve_time=1.0, time_limit=120) is False
    assert solver_proved_optimal("Infeasible", solve_time=1.0, time_limit=120) is False


def test_milp_status_on_small_instance_is_proved():
    """Sur 2 commandes, le MILP prouve l'optimum bien avant la limite."""

    from src.optimizer.optimizer import load_data, create_tasks, optimize_schedule

    orders, _, operations = load_data()
    tasks = create_tasks(orders.head(2), operations)

    schedule = optimize_schedule(tasks, time_limit=30)

    assert schedule.attrs["solver"] == "MILP"
    assert schedule.attrs["proved_optimal"] is True
    assert schedule.attrs["solve_time"] < 0.95 * 30


def test_milp_status_on_full_dataset_with_tiny_limit_is_not_proved():
    """Sur tout le jeu par défaut, 2 s ne suffisent pas à prouver l'optimum :
    le statut ne doit PAS être présenté comme prouvé."""

    from src.optimizer.optimizer import load_data, create_tasks, optimize_schedule

    orders, _, operations = load_data()
    tasks = create_tasks(orders, operations)

    schedule = optimize_schedule(tasks, time_limit=2)

    assert schedule is not None
    assert schedule.attrs["proved_optimal"] is False
    assert schedule.attrs["time_limit"] == 2
