import numpy as np
import pandas as pd


def _has_value(raw_value):
    """Vrai si la cellule machine_durations contient une vraie valeur."""

    return not (pd.isna(raw_value) or str(raw_value).strip() == "")


def _scale_machine_durations(raw_value, duration_factor):
    """
    Multiplie chaque durée d'une chaîne "M1:5|M3:4" par duration_factor.

    Si la valeur est absente ou vide, elle est renvoyée telle quelle
    (compatibilité arrière avec les CSV sans durées par machine).
    """

    if not _has_value(raw_value):
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


def add_machine_to_operation(
    operations,
    operation_id,
    machine_id,
    duration=None
):
    """
    Scénario "ajouter une machine compatible à une opération".

    Ajoute machine_id à compatible_machines. Si le CSV contient des durées
    par machine, la nouvelle machine reçoit par défaut la durée nominale
    (colonne "duration", c'est-à-dire la moyenne) de l'opération, comme dans
    l'ancien comportement où toutes les machines avaient la même durée.
    Le paramètre duration permet de forcer une autre valeur (durée unitaire).
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

    has_durations_column = "machine_durations" in scenario_operations.columns

    if has_durations_column:
        scenario_operations["machine_durations"] = (
            scenario_operations["machine_durations"].astype(object)
        )

    for row_index in scenario_operations.index[mask]:

        current_machines = [
            machine.strip()
            for machine in str(
                scenario_operations.at[row_index, "compatible_machines"]
            ).split("|")
        ]

        if machine_id in current_machines:
            raise ValueError(
                f"{machine_id} est déjà compatible avec {operation_id}"
            )

        scenario_operations.at[row_index, "compatible_machines"] = (
            "|".join(current_machines + [machine_id])
        )

        if has_durations_column:

            raw = scenario_operations.at[row_index, "machine_durations"]

            if _has_value(raw):

                new_duration = (
                    float(scenario_operations.at[row_index, "duration"])
                    if duration is None
                    else float(duration)
                )

                scenario_operations.at[row_index, "machine_durations"] = (
                    f"{raw}|{machine_id}:{round(new_duration, 6)}"
                )

    return scenario_operations


def scale_operations_durations(operations, factors):
    """
    Multiplie la durée de chaque opération (ligne par ligne) par son facteur.
    Utilisé par l'analyse Monte Carlo : un facteur par ligne d'opérations.

    Le même facteur est appliqué à "duration" et à toutes les durées
    de la colonne optionnelle machine_durations de la même ligne.
    """

    factors = list(factors)

    if len(factors) != len(operations):
        raise ValueError(
            "Il faut exactement un facteur par ligne d'opérations "
            f"({len(factors)} reçus pour {len(operations)} lignes)"
        )

    scaled_operations = operations.copy()

    scaled_operations["duration"] = (
        scaled_operations["duration"].astype(float).values
        * np.array(factors)
    )

    if "machine_durations" in scaled_operations.columns:

        scaled_operations["machine_durations"] = pd.Series(
            [
                _scale_machine_durations(raw, factor)
                for raw, factor in zip(
                    scaled_operations["machine_durations"],
                    factors
                )
            ],
            index=scaled_operations.index,
            dtype=object
        )

    return scaled_operations