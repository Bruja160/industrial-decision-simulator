import pandas as pd


def _scale_machine_durations(raw_value, duration_factor):
    """
    Multiplie chaque durée d'une chaîne "M1:5|M3:4" par duration_factor.

    Si la valeur est absente ou vide, elle est renvoyée telle quelle
    (compatibilité arrière avec les CSV sans durées par machine).
    """

    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return raw_value

    scaled_items = []

    for item in str(raw_value).split("|"):
        machine, _, value_text = item.strip().partition(":")
        scaled_value = float(value_text) * duration_factor
        scaled_items.append(f"{machine.strip()}:{round(scaled_value, 6)}")

    return "|".join(scaled_items)


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

    Si le CSV contient la colonne optionnelle machine_durations
    (durée par machine), le facteur est appliqué à toutes les machines
    de l'opération, en plus de la durée moyenne "duration".
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

    if "machine_durations" in scenario_operations.columns:

        scenario_operations["machine_durations"] = (
            scenario_operations["machine_durations"].astype(object)
        )

        scenario_operations.loc[
            mask,
            "machine_durations"
        ] = scenario_operations.loc[
            mask,
            "machine_durations"
        ].apply(
            lambda raw: _scale_machine_durations(
                raw,
                duration_factor
            )
        )

    return scenario_operations