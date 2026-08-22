import pandas as pd


def create_scenario(
    operations,
    operation_id,
    duration_factor=1.0
):
    """
    Crée un scénario What-If en modifiant
    la durée d'une opération.

    duration_factor :
        1.00 = aucune modification
        0.90 = réduction de 10 %
        1.10 = augmentation de 10 %
    """

    scenario_operations = operations.copy()

    mask = (
        scenario_operations["operation_id"]
        == operation_id
    )

    if not mask.any():
        raise ValueError(
            f"Opération inconnue : {operation_id}"
        )

    scenario_operations.loc[
        mask,
        "duration"
    ] = (
        scenario_operations.loc[
            mask,
            "duration"
        ].astype(float)
        * duration_factor
    )

    return scenario_operations