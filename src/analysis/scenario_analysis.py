import pandas as pd


def compare_scenarios(baseline, scenario):
    """
    Compare les performances de la situation actuelle
    avec celles d'un scénario industriel.
    """

    # ==============================
    # RÉCUPÉRATION DES KPI
    # ==============================

    baseline_makespan = float(baseline["makespan"])
    scenario_makespan = float(scenario["makespan"])

    baseline_delay = float(baseline["total_delay"])
    scenario_delay = float(scenario["total_delay"])

    baseline_on_time = float(baseline["on_time_rate"])
    scenario_on_time = float(scenario["on_time_rate"])

    baseline_late_orders = int(baseline["late_orders"])
    scenario_late_orders = int(scenario["late_orders"])

    baseline_bottleneck = baseline["bottleneck"]
    scenario_bottleneck = scenario["bottleneck"]

    # ==============================
    # CALCUL DES GAINS
    # ==============================

    if baseline_makespan != 0:
        makespan_gain = (
            (baseline_makespan - scenario_makespan)
            / baseline_makespan
            * 100
        )
    else:
        makespan_gain = 0

    if baseline_delay != 0:
        delay_gain = (
            (baseline_delay - scenario_delay)
            / baseline_delay
            * 100
        )
    else:
        delay_gain = 0

    on_time_change = scenario_on_time - baseline_on_time

    late_orders_change = (
        scenario_late_orders - baseline_late_orders
    )

    # ==============================
    # TABLEAU COMPARATIF
    # ==============================

    comparison = pd.DataFrame({
        "KPI": [
            "Makespan (h)",
            "Retard total (h)",
            "Commandes en retard",
            "Taux de respect (%)"
        ],

        "Situation actuelle": [
            baseline_makespan,
            baseline_delay,
            baseline_late_orders,
            baseline_on_time
        ],

        "Scénario": [
            scenario_makespan,
            scenario_delay,
            scenario_late_orders,
            scenario_on_time
        ]
    })

    # ==============================
    # AFFICHAGE
    # ==============================

    print()
    print("=" * 60)
    print("ANALYSE DU SCÉNARIO")
    print("=" * 60)

    print()
    print(comparison.to_string(index=False))

    print()
    print(f"Gain Makespan       : {makespan_gain:+.2f} %")
    print(f"Gain retard total   : {delay_gain:+.2f} %")
    print(
        f"Variation respect   : "
        f"{on_time_change:+.2f} points"
    )
    print(
        f"Variation commandes : "
        f"{late_orders_change:+d}"
    )

    print()
    print(
        f"Goulot actuel       : "
        f"{baseline_bottleneck}"
    )

    print(
        f"Goulot scénario     : "
        f"{scenario_bottleneck}"
    )

    # ==============================
    # DÉCISION
    # ==============================

    if (
        makespan_gain >= 5
        and delay_gain >= 5
        and on_time_change >= 0
    ):
        recommendation = "SCÉNARIO FAVORABLE"

        explanation = (
            "Le scénario améliore globalement "
            "les performances de production."
        )

    elif (
        makespan_gain >= 5
        and delay_gain >= 5
    ):
        recommendation = "SCÉNARIO À ÉTUDIER"

        explanation = (
            "Le scénario réduit le temps de production "
            "et le retard total, mais certains KPI "
            "se dégradent."
        )

    else:
        recommendation = "SCÉNARIO PEU INTÉRESSANT"

        explanation = (
            "Le scénario ne produit pas une amélioration "
            "suffisante des performances."
        )

    print()
    print("=" * 60)
    print("RECOMMANDATION")
    print("=" * 60)

    print()
    print(f"Décision : {recommendation}")
    print()
    print(f"Analyse  : {explanation}")
    print()

    # ==============================
    # RÉSULTAT RETOURNÉ
    # ==============================

    return {
        "comparison": comparison,
        "makespan_gain": makespan_gain,
        "delay_gain": delay_gain,
        "on_time_change": on_time_change,
        "late_orders_change": late_orders_change,
        "baseline_bottleneck": baseline_bottleneck,
        "scenario_bottleneck": scenario_bottleneck,
        "recommendation": recommendation
    }


# ==========================================================
# TEST DU MODULE
# ==========================================================

if __name__ == "__main__":

    baseline = {
        "makespan": 78.60,
        "total_delay": 410.75,
        "late_orders": 10,
        "on_time_rate": 16.67,
        "bottleneck": "M3 - Usinage_2"
    }

    scenario = {
        "makespan": 65.40,
        "total_delay": 319.20,
        "late_orders": 11,
        "on_time_rate": 8.33,
        "bottleneck": "M2 - Usinage_1"
    }

    compare_scenarios(
        baseline,
        scenario
    )