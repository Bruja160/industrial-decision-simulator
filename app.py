import sys
from pathlib import Path
import random

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


# ============================================================
# CONFIGURATION DU PROJET
# ============================================================

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# IMPORTS DU PROJET
# ============================================================

from src.optimizer.optimizer import (
    create_tasks,
    optimize_schedule,
    calculate_kpis,
)

from src.analysis.scenario_analysis import compare_scenarios


# ============================================================
# CONFIGURATION STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Industrial Decision Simulator",
    page_icon="🏭",
    layout="wide",
)


# ============================================================
# UTILITAIRE : RETROUVER LE TAUX D'UTILISATION DU GOULOT
# ============================================================
# kpis["bottleneck"] est une chaîne déjà formatée, ex: "M3 - Usinage_2".
# On retrouve le taux d'utilisation en cherchant dans kpis["machines"].

def get_bottleneck_utilization(kpis):
    bottleneck_id = kpis["bottleneck"].split(" - ")[0].strip()

    machine_row = kpis["machines"][
        kpis["machines"]["machine_id"] == bottleneck_id
    ]

    if not machine_row.empty:
        return float(machine_row["utilization_percent"].iloc[0])

    return None


# ============================================================
# UTILITAIRE : PHRASE DE DÉCISION EN LANGAGE HUMAIN
# ============================================================

def describe_change(value, unit="%"):
    """Transforme un gain signé en verbe + valeur absolue lisible."""
    if value > 0.05:
        return f"diminue de {value:.1f} {unit}"
    elif value < -0.05:
        return f"augmente de {abs(value):.1f} {unit}"
    else:
        return f"reste quasiment inchangé"


def generate_decision_sentence(comparison, scenario_label):

    makespan_txt = describe_change(comparison["makespan_gain"])
    delay_txt = describe_change(comparison["delay_gain"])
    on_time_txt = describe_change(comparison["on_time_change"], unit="points")

    recommendation = comparison["recommendation"]

    if recommendation == "SCÉNARIO FAVORABLE":
        verdict = "Ce scénario est **recommandé**."
    elif recommendation == "SCÉNARIO À ÉTUDIER":
        verdict = "Ce scénario **mérite d'être approfondi** avant décision, les gains sont partiels."
    else:
        verdict = "Ce scénario **n'est pas recommandé** en l'état."

    sentence = (
        f"**{scenario_label}**. Avec ce changement, le Makespan {makespan_txt}, "
        f"le retard total {delay_txt}, et le taux de respect des délais {on_time_txt}. "
        f"{verdict}"
    )

    return sentence


# ============================================================
# UTILITAIRE : ANALYSE ÉCONOMIQUE (COÛT / GAIN / ROI)
# ============================================================

def validate_uploaded_data(orders_df, machines_df, operations_df):
    """
    Valide un jeu de données déposé par l'utilisateur, avant de l'utiliser.
    Retourne une liste d'erreurs (vide si tout est valide). Réutilise la
    même logique de contrôle que tests/test_data.py.
    """

    errors = []

    required_orders_cols = {"order_id", "product_id", "quantity", "deadline"}
    required_machines_cols = {"machine_id", "machine_name"}
    required_operations_cols = {
        "operation_id", "product_id", "operation_type", "duration", "compatible_machines"
    }

    missing_orders = required_orders_cols - set(orders_df.columns)
    missing_machines = required_machines_cols - set(machines_df.columns)
    missing_operations = required_operations_cols - set(operations_df.columns)

    if missing_orders:
        errors.append(f"orders.csv : colonnes manquantes {sorted(missing_orders)}")
    if missing_machines:
        errors.append(f"machines.csv : colonnes manquantes {sorted(missing_machines)}")
    if missing_operations:
        errors.append(f"operations.csv : colonnes manquantes {sorted(missing_operations)}")

    if errors:
        return errors  # colonnes manquantes -> impossible de vérifier le reste

    if not orders_df["order_id"].is_unique:
        errors.append("orders.csv : la colonne order_id contient des doublons")
    if not machines_df["machine_id"].is_unique:
        errors.append("machines.csv : la colonne machine_id contient des doublons")
    if not operations_df["operation_id"].is_unique:
        errors.append("operations.csv : la colonne operation_id contient des doublons")

    if len(orders_df) == 0 or (orders_df["quantity"] <= 0).any():
        errors.append("orders.csv : toutes les quantités doivent être > 0")
    if len(orders_df) == 0 or (orders_df["deadline"] <= 0).any():
        errors.append("orders.csv : toutes les deadlines doivent être > 0")
    if len(operations_df) == 0 or (operations_df["duration"] <= 0).any():
        errors.append("operations.csv : toutes les durées doivent être > 0")
    if operations_df["compatible_machines"].isna().any():
        errors.append("operations.csv : compatible_machines ne doit jamais être vide")

    valid_products = set(orders_df["product_id"])
    operation_products = set(operations_df["product_id"])
    if not operation_products.issubset(valid_products):
        errors.append(
            "operations.csv : certains product_id n'existent dans aucune commande "
            f"d'orders.csv ({sorted(operation_products - valid_products)})"
        )

    all_machine_ids = set(machines_df["machine_id"])
    referenced_machines = set()
    for value in operations_df["compatible_machines"].dropna():
        for m in str(value).split("|"):
            referenced_machines.add(m.strip())

    unknown_machines = referenced_machines - all_machine_ids
    if unknown_machines:
        errors.append(
            f"operations.csv : machines référencées mais absentes de machines.csv : "
            f"{sorted(unknown_machines)}"
        )

    return errors


def generate_shift_unavailability_windows(shift_start, shift_end, num_cycles=15, cycle_length=24):
    """
    Génère la liste des fenêtres d'indisponibilité correspondant à une
    machine qui ne travaille que pendant [shift_start, shift_end] de
    chaque cycle de 24h (répété num_cycles fois, largement suffisant
    pour couvrir n'importe quel horizon réaliste de ce projet).

    Réutilise directement le mécanisme machine_unavailability déjà
    validé pour les pannes machine — aucune nouvelle logique côté
    solveur, donc aucun nouveau risque numérique.
    """

    windows = []

    for cycle in range(num_cycles):
        day_start = cycle * cycle_length

        if shift_start > 0:
            windows.append((day_start, day_start + shift_start))

        if shift_end < cycle_length:
            windows.append((day_start + shift_end, day_start + cycle_length))

    return windows


def compute_economic_analysis(baseline_kpis, scenario_kpis, cost, hourly_value, hourly_delay_cost):

    makespan_gain_hours = baseline_kpis["makespan"] - scenario_kpis["makespan"]
    delay_gain_hours = baseline_kpis["total_delay"] - scenario_kpis["total_delay"]

    financial_gain = (
        makespan_gain_hours * hourly_value
        + delay_gain_hours * hourly_delay_cost
    )

    net_gain = financial_gain - cost
    roi_pct = (financial_gain / cost * 100) if cost > 0 else None

    return {
        "makespan_gain_hours": makespan_gain_hours,
        "delay_gain_hours": delay_gain_hours,
        "financial_gain": financial_gain,
        "cost": cost,
        "net_gain": net_gain,
        "roi_pct": roi_pct,
    }


# ============================================================
# UTILITAIRE : DIAGRAMME DE GANTT DU PLANNING
# ============================================================

def create_gantt_chart(schedule, title):

    machines_order = sorted(schedule["machine"].unique(), reverse=True)
    products = sorted(schedule["product_id"].unique())

    palette = px.colors.qualitative.Set2
    color_map = {p: palette[i % len(palette)] for i, p in enumerate(products)}

    fig = go.Figure()

    shown_in_legend = set()

    for _, row in schedule.iterrows():

        show_legend = row["product_id"] not in shown_in_legend
        shown_in_legend.add(row["product_id"])

        fig.add_trace(go.Bar(
            x=[row["duration"]],
            y=[row["machine"]],
            base=[row["start"]],
            orientation="h",
            marker_color=color_map[row["product_id"]],
            name=row["product_id"],
            legendgroup=row["product_id"],
            showlegend=show_legend,
            hovertemplate=(
                f"<b>{row['task_id']}</b><br>"
                f"Opération : {row['operation_id']} ({row['operation_type']})<br>"
                f"Début : {row['start']:.2f} h — Fin : {row['end']:.2f} h<br>"
                f"Durée : {row['duration']:.2f} h"
                "<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=title,
        barmode="stack",
        xaxis_title="Temps (heures)",
        yaxis_title="Machine",
        yaxis=dict(categoryorder="array", categoryarray=machines_order),
        height=350,
        margin=dict(l=10, r=10, t=40, b=10),
        legend_title="Produit",
        template="plotly_dark",
    )

    return fig


# ============================================================
# TITRE
# ============================================================

st.title("🏭 Industrial Decision Simulator")

st.write(
    "Système digital d'aide à la décision pour "
    "l'amélioration des performances industrielles."
)


# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================

@st.cache_data
def load_project_data():

    orders = pd.read_csv(ROOT / "data" / "orders.csv")
    machines = pd.read_csv(ROOT / "data" / "machines.csv")
    operations = pd.read_csv(ROOT / "data" / "operations.csv")

    return orders, machines, operations


orders, machines, operations = load_project_data()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("⚙️ Paramètres du scénario")

st.sidebar.write(
    "Modifiez un paramètre industriel puis "
    "comparez le scénario avec la situation actuelle."
)

st.sidebar.divider()
st.sidebar.header("💰 Paramètres économiques")

hourly_production_value = st.sidebar.number_input(
    "Valeur horaire de production gagnée (DH/h)",
    min_value=0,
    value=500,
    step=50,
    help="Combien vaut 1 heure de Makespan économisée pour l'entreprise "
         "(capacité de production libérée, coût de production évité...)."
)

hourly_delay_cost = st.sidebar.number_input(
    "Coût horaire de retard évité (DH/h)",
    min_value=0,
    value=200,
    step=50,
    help="Combien coûte 1 heure de retard total (pénalités client, "
         "insatisfaction, coûts logistiques...)."
)


# ============================================================
# DONNÉES DU SYSTÈME
# ============================================================

st.header("📊 Données du système industriel")

with st.expander("📁 Charger un autre système industriel (optionnel)"):

    st.write(
        "Le moteur d'optimisation est **générique** : il ne connaît aucun détail "
        "propre à ce jeu de données. Dépose tes propres fichiers CSV pour tester "
        "ton propre atelier de production, sans toucher au code."
    )

    col_u1, col_u2, col_u3 = st.columns(3)

    with col_u1:
        uploaded_orders = st.file_uploader("orders.csv", type="csv", key="upload_orders")

    with col_u2:
        uploaded_machines = st.file_uploader("machines.csv", type="csv", key="upload_machines")

    with col_u3:
        uploaded_operations = st.file_uploader("operations.csv", type="csv", key="upload_operations")

    st.caption(
        "**Colonnes attendues** — `orders.csv` : order_id, product_id, quantity, deadline · "
        "`machines.csv` : machine_id, machine_name · "
        "`operations.csv` : operation_id, product_id, operation_type, duration, compatible_machines "
        "(format `M1|M2|M3` pour plusieurs machines compatibles)."
    )

    if uploaded_orders and uploaded_machines and uploaded_operations:

        current_signature = (
            uploaded_orders.name, uploaded_orders.size,
            uploaded_machines.name, uploaded_machines.size,
            uploaded_operations.name, uploaded_operations.size,
        )

        if st.session_state.get("data_signature") != current_signature:

            try:
                new_orders = pd.read_csv(uploaded_orders)
                new_machines = pd.read_csv(uploaded_machines)
                new_operations = pd.read_csv(uploaded_operations)
            except Exception as e:
                st.error(f"Erreur de lecture des fichiers CSV : {e}")
                new_orders = new_machines = new_operations = None

            if new_orders is not None:

                validation_errors = validate_uploaded_data(new_orders, new_machines, new_operations)

                if validation_errors:
                    st.error(
                        "❌ Fichiers invalides, le système précédent reste actif :\n\n"
                        + "\n".join(f"- {e}" for e in validation_errors)
                    )
                else:
                    orders, machines, operations = new_orders, new_machines, new_operations

                    st.session_state["custom_orders"] = orders
                    st.session_state["custom_machines"] = machines
                    st.session_state["custom_operations"] = operations
                    st.session_state["data_signature"] = current_signature

                    for key in [
                        "baseline_kpis", "baseline_schedule", "scenario_kpis",
                        "scenario_schedule", "comparison", "scenario_label", "mc_results",
                    ]:
                        st.session_state.pop(key, None)

                    st.success(
                        f"✅ Nouveau système chargé : {len(orders)} commandes, "
                        f"{len(machines)} machines, {len(operations)} opérations. "
                        f"Les résultats précédents ont été réinitialisés."
                    )

    elif uploaded_orders or uploaded_machines or uploaded_operations:
        st.warning("Dépose les 3 fichiers ensemble (orders, machines, operations) pour charger un nouveau système.")

    if "custom_orders" in st.session_state:
        if st.button("↩️ Revenir au jeu de données par défaut"):
            for key in [
                "custom_orders", "custom_machines", "custom_operations", "data_signature",
                "baseline_kpis", "baseline_schedule", "scenario_kpis",
                "scenario_schedule", "comparison", "scenario_label", "mc_results",
            ]:
                st.session_state.pop(key, None)
            st.rerun()


# Si un jeu de données personnalisé est actif en session, il prend le pas
# sur le jeu de données par défaut chargé plus haut.
if "custom_orders" in st.session_state:
    orders = st.session_state["custom_orders"]
    machines = st.session_state["custom_machines"]
    operations = st.session_state["custom_operations"]


col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Commandes", len(orders))

with col2:
    st.metric("Machines", len(machines))

with col3:
    st.metric("Opérations", len(operations))

with col4:
    st.metric("Produits", operations["product_id"].nunique())


with st.expander("Voir les commandes"):
    st.dataframe(orders, use_container_width=True)

with st.expander("Voir les machines"):
    st.dataframe(machines, use_container_width=True)

with st.expander("Voir les opérations"):
    st.dataframe(operations, use_container_width=True)


# ============================================================
# 1️⃣ OPTIMISATION SITUATION ACTUELLE
# ============================================================

st.header("1️⃣ Situation actuelle")


if st.button("🚀 Optimiser la situation actuelle", type="primary"):

    with st.spinner("Optimisation de la situation actuelle..."):
        baseline_tasks = create_tasks(orders, operations)
        baseline_schedule = optimize_schedule(baseline_tasks)

    if baseline_schedule is None:
        st.error("Aucune solution trouvée pour la situation actuelle.")
        st.stop()

    baseline_kpis = calculate_kpis(baseline_schedule, orders, machines)

    st.session_state["baseline_schedule"] = baseline_schedule
    st.session_state["baseline_kpis"] = baseline_kpis

    st.success("Optimisation de la situation actuelle terminée.")


if "baseline_kpis" in st.session_state:

    baseline_kpis = st.session_state["baseline_kpis"]

    st.subheader("📈 KPI de la situation actuelle")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Makespan", f"{baseline_kpis['makespan']:.2f} h")

    with col2:
        st.metric("Retard total", f"{baseline_kpis['total_delay']:.2f} h")

    with col3:
        st.metric(
            "Commandes en retard",
            f"{baseline_kpis['late_orders']} / {baseline_kpis['total_orders']}"
        )

    with col4:
        st.metric("Respect des délais", f"{baseline_kpis['on_time_rate']:.2f} %")

    st.write(f"**Goulot actuel :** {baseline_kpis['bottleneck']}")

    st.subheader("📅 Planning (Gantt)")
    st.plotly_chart(
        create_gantt_chart(
            st.session_state["baseline_schedule"],
            "Planning optimisé — Situation actuelle"
        ),
        use_container_width=True,
    )


# ============================================================
# 2️⃣ CRÉATION DU SCÉNARIO
# ============================================================

st.header("2️⃣ Création du scénario")

st.write("Choisissez le type de décision industrielle à tester.")

scenario_type = st.radio(
    "Type de scénario",
    [
        "Modifier la durée d'une opération",
        "Ajouter une machine compatible à une opération",
        "Simuler une panne machine (indisponibilité temporaire)",
        "Simuler un calendrier d'équipes (shift) sur une machine",
    ],
    horizontal=True,
)

machine_to_add = None
scenario_duration = None
current_duration = None
selected_operation = None
breakdown_machine = None
breakdown_start = None
breakdown_end = None

if scenario_type in [
    "Modifier la durée d'une opération",
    "Ajouter une machine compatible à une opération",
]:

    operation_options = operations["operation_id"].tolist()
    selected_operation = st.selectbox("Opération concernée", operation_options)

    selected_row = operations[
        operations["operation_id"] == selected_operation
    ].iloc[0]

    if scenario_type == "Modifier la durée d'une opération":

        current_duration = float(selected_row["duration"])

        scenario_duration = st.number_input(
            "Nouvelle durée de l'opération (heures)",
            min_value=0.001,
            value=current_duration,
            step=0.001,
            format="%.3f"
        )

        variation = (scenario_duration - current_duration) / current_duration * 100

        if variation < 0:
            st.info(f"Amélioration simulée : {variation:.2f} %")
        elif variation > 0:
            st.warning(f"Dégradation simulée : +{variation:.2f} %")
        else:
            st.info("Aucune modification de durée.")

    else:

        current_machines = [
            m.strip() for m in str(selected_row["compatible_machines"]).split("|")
        ]

        st.write(f"Machines actuellement compatibles : **{', '.join(current_machines)}**")

        available_machines = [
            m for m in machines["machine_id"].tolist() if m not in current_machines
        ]

        if available_machines:
            machine_to_add = st.selectbox(
                "Machine à ajouter comme option pour cette opération",
                available_machines
            )
            st.info(
                f"Cette opération pourra désormais aussi être réalisée sur "
                f"**{machine_to_add}**, en plus de {', '.join(current_machines)}."
            )
        else:
            st.warning("Toutes les machines existantes sont déjà compatibles avec cette opération.")

elif scenario_type == "Simuler une panne machine (indisponibilité temporaire)":

    st.write(
        "Simule l'indisponibilité temporaire d'une machine "
        "(maintenance planifiée, panne...) et observe comment "
        "le planning optimal se réorganise autour."
    )

    breakdown_machine = st.selectbox(
        "Machine concernée",
        machines["machine_id"].tolist()
    )

    col_a, col_b = st.columns(2)

    with col_a:
        breakdown_start = st.number_input(
            "Début de l'indisponibilité (heures)",
            min_value=0.0,
            value=10.0,
            step=1.0,
        )

    with col_b:
        breakdown_end = st.number_input(
            "Fin de l'indisponibilité (heures)",
            min_value=0.0,
            value=12.0,
            step=1.0,
        )

    if breakdown_end <= breakdown_start:
        st.warning("La fin de l'indisponibilité doit être après le début.")

else:

    st.write(
        "Simule une machine qui ne travaille que sur une plage horaire "
        "fixe chaque jour (ex: équipe unique 07h-15h), au lieu de tourner "
        "en continu. Le reste du temps, la machine est indisponible."
    )

    shift_machine = st.selectbox(
        "Machine concernée",
        machines["machine_id"].tolist()
    )

    col_a, col_b = st.columns(2)

    with col_a:
        shift_start = st.number_input(
            "Début de l'équipe (heure du cycle, 0-24)",
            min_value=0,
            max_value=24,
            value=7,
            step=1,
        )

    with col_b:
        shift_end = st.number_input(
            "Fin de l'équipe (heure du cycle, 0-24)",
            min_value=0,
            max_value=24,
            value=15,
            step=1,
        )

    if shift_end <= shift_start:
        st.warning("La fin de l'équipe doit être après le début.")
    else:
        st.info(
            f"La machine {shift_machine} ne sera disponible que de "
            f"{shift_start}h à {shift_end}h, chaque jour (cycle de 24h), "
            f"répété sur toute la durée du planning."
        )


st.subheader("💰 Coût estimé de ce scénario")

st.caption(
    "Valeurs par défaut illustratives, modifiables librement. Non calibrées "
    "sur des données industrielles réelles — objectif : démontrer la méthode "
    "de décision économique, pas fournir un chiffrage validé."
)

if scenario_type == "Modifier la durée d'une opération":
    default_cost = 2000
elif scenario_type == "Ajouter une machine compatible à une opération":
    default_cost = 40000
else:
    default_cost = 0

scenario_cost = st.number_input(
    "Investissement nécessaire pour ce scénario (DH)",
    min_value=0,
    value=default_cost,
    step=500,
    help="⚠️ Valeur par défaut illustrative, à ajuster selon ton contexte réel. "
         "Pour un ajout de machine, ceci représente typiquement un coût de "
         "reconfiguration / outillage / formation pour qu'une machine EXISTANTE "
         "puisse aussi réaliser cette opération — PAS l'achat d'une machine neuve "
         "(qui coûterait généralement bien plus cher)."
)


if st.button("🔬 Simuler le scénario"):

    if "baseline_kpis" not in st.session_state:
        st.warning("Vous devez d'abord optimiser la situation actuelle.")
        st.stop()

    if scenario_type == "Ajouter une machine compatible à une opération" and machine_to_add is None:
        st.warning("Aucune machine disponible à ajouter pour cette opération.")
        st.stop()

    if scenario_type == "Simuler une panne machine (indisponibilité temporaire)" and (
        breakdown_end is None or breakdown_start is None or breakdown_end <= breakdown_start
    ):
        st.warning("Vérifie les horaires d'indisponibilité (fin doit être après début).")
        st.stop()

    if scenario_type == "Simuler un calendrier d'équipes (shift) sur une machine" and (
        shift_end <= shift_start
    ):
        st.warning("Vérifie les horaires de l'équipe (fin doit être après début).")
        st.stop()

    scenario_operations = operations.copy()
    machine_unavailability = None

    if scenario_type == "Modifier la durée d'une opération":
        scenario_operations.loc[
            scenario_operations["operation_id"] == selected_operation, "duration"
        ] = scenario_duration

        scenario_label = (
            f"Durée de {selected_operation} modifiée : "
            f"{current_duration:.3f} h → {scenario_duration:.3f} h"
        )

    elif scenario_type == "Ajouter une machine compatible à une opération":
        current_value = str(selected_row["compatible_machines"])
        new_value = f"{current_value}|{machine_to_add}"

        scenario_operations.loc[
            scenario_operations["operation_id"] == selected_operation,
            "compatible_machines"
        ] = new_value

        scenario_label = f"{machine_to_add} ajoutée comme machine compatible pour {selected_operation}"

    elif scenario_type == "Simuler une panne machine (indisponibilité temporaire)":
        machine_unavailability = {
            breakdown_machine: [(breakdown_start, breakdown_end)]
        }

        scenario_label = (
            f"{breakdown_machine} indisponible de {breakdown_start:.0f}h "
            f"à {breakdown_end:.0f}h"
        )

    else:
        shift_windows = generate_shift_unavailability_windows(shift_start, shift_end)

        machine_unavailability = {
            shift_machine: shift_windows
        }

        scenario_label = (
            f"{shift_machine} en équipe unique {shift_start}h-{shift_end}h "
            f"(au lieu de 24h/24)"
        )

    st.caption(f"**Scénario testé :** {scenario_label}")

    scenario_tasks = create_tasks(orders, scenario_operations)

    with st.spinner("Optimisation du scénario..."):
        scenario_schedule = optimize_schedule(
            scenario_tasks,
            machine_unavailability=machine_unavailability,
        )

    if scenario_schedule is None:
        st.error("Aucune solution trouvée pour ce scénario.")
        st.stop()

    scenario_kpis = calculate_kpis(scenario_schedule, orders, machines)

    baseline_kpis = st.session_state["baseline_kpis"]
    comparison = compare_scenarios(baseline_kpis, scenario_kpis)

    st.session_state["scenario_schedule"] = scenario_schedule
    st.session_state["scenario_kpis"] = scenario_kpis
    st.session_state["comparison"] = comparison
    st.session_state["scenario_label"] = scenario_label
    st.session_state["scenario_cost"] = scenario_cost


# ============================================================
# 3️⃣ RESULTATS DU SCENARIO
# ============================================================

if "scenario_kpis" in st.session_state:

    scenario_kpis = st.session_state["scenario_kpis"]
    comparison = st.session_state["comparison"]
    baseline_kpis = st.session_state["baseline_kpis"]

    st.header("3️⃣ Résultats de la simulation")

    st.subheader("📊 Comparaison des performances")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Makespan", f"{scenario_kpis['makespan']:.2f} h",
            delta=f"{comparison['makespan_gain']:.2f} %"
        )

    with col2:
        st.metric(
            "Retard total", f"{scenario_kpis['total_delay']:.2f} h",
            delta=f"{comparison['delay_gain']:.2f} %"
        )

    with col3:
        st.metric(
            "Respect des délais", f"{scenario_kpis['on_time_rate']:.2f} %",
            delta=f"{comparison['on_time_change']:.2f} points"
        )

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Commandes en retard - actuel", baseline_kpis["late_orders"])

    with col2:
        st.metric("Commandes en retard - scénario", scenario_kpis["late_orders"])

    st.subheader("🔴 Analyse du goulot")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**Situation actuelle**")
        st.write(baseline_kpis["bottleneck"])
        baseline_utilization = get_bottleneck_utilization(baseline_kpis)
        if baseline_utilization is not None:
            st.write(f"Utilisation : {baseline_utilization:.2f} %")

    with col2:
        st.write("**Scénario**")
        st.write(scenario_kpis["bottleneck"])
        scenario_utilization = get_bottleneck_utilization(scenario_kpis)
        if scenario_utilization is not None:
            st.write(f"Utilisation : {scenario_utilization:.2f} %")

    st.subheader("📋 Tableau comparatif")

    comparison_table = comparison["comparison"].copy()
    st.dataframe(comparison_table, use_container_width=True)

    st.subheader("📅 Planning comparé (Gantt)")

    col_gantt1, col_gantt2 = st.columns(2)

    with col_gantt1:
        st.plotly_chart(
            create_gantt_chart(
                st.session_state["baseline_schedule"],
                "Situation actuelle"
            ),
            use_container_width=True,
        )

    with col_gantt2:
        st.plotly_chart(
            create_gantt_chart(
                st.session_state["scenario_schedule"],
                "Scénario"
            ),
            use_container_width=True,
        )

    with st.expander("Voir le planning optimisé du scénario (données brutes)"):
        scenario_schedule = st.session_state["scenario_schedule"]
        st.dataframe(
            scenario_schedule.sort_values(["machine", "start"]),
            use_container_width=True
        )


# ============================================================
# 4️⃣ ANALYSE DE L'INCERTITUDE (MONTE CARLO)
# ============================================================

st.divider()
st.header("4️⃣ Analyse de l'incertitude (Monte Carlo)")

st.write(
    "En réalité, les durées ne sont jamais parfaitement fixes "
    "(variabilité opérateur, aléas machine...). Cette section relance "
    "l'optimisation de la situation actuelle plusieurs fois avec des "
    "durées légèrement aléatoires, pour obtenir une **fourchette** de "
    "Makespan plutôt qu'un chiffre unique."
)

col1, col2 = st.columns(2)

with col1:
    n_simulations = st.slider("Nombre de simulations", min_value=5, max_value=30, value=15)

with col2:
    variation_pct = st.slider("Variation des durées (%)", min_value=5, max_value=30, value=15)

st.caption(
    f"⏱️ Chaque simulation est limitée à 30 secondes de calcul pour rester "
    f"gérable ({n_simulations} simulations : jusqu'à "
    f"{n_simulations * 30 // 60} min dans le pire des cas)."
)

if st.button("🎲 Lancer l'analyse Monte Carlo"):

    makespans = []
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    for i in range(n_simulations):
        status_text.text(f"Simulation {i + 1} / {n_simulations}...")

        randomized_operations = operations.copy()
        factors = [
            random.uniform(1 - variation_pct / 100, 1 + variation_pct / 100)
            for _ in range(len(randomized_operations))
        ]
        randomized_operations["duration"] = (
            randomized_operations["duration"].values * np.array(factors)
        )

        tasks_mc = create_tasks(orders, randomized_operations)
        schedule_mc = optimize_schedule(tasks_mc, time_limit=30)

        if schedule_mc is not None:
            makespans.append(float(schedule_mc["end"].max()))

        progress_bar.progress((i + 1) / n_simulations)

    status_text.empty()
    progress_bar.empty()

    if len(makespans) == 0:
        st.error("Aucune simulation n'a abouti à une solution exploitable.")
    else:
        makespans_array = np.array(makespans)

        st.session_state["mc_results"] = {
            "makespans": makespans_array,
            "n_simulations": n_simulations,
            "n_valid": len(makespans),
            "variation_pct": variation_pct,
        }

        st.success(f"{len(makespans)} / {n_simulations} simulations exploitables.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Makespan minimum", f"{makespans_array.min():.2f} h")
        c2.metric("Makespan moyen", f"{makespans_array.mean():.2f} h")
        c3.metric("Makespan maximum", f"{makespans_array.max():.2f} h")
        c4.metric("Écart-type", f"{makespans_array.std():.2f} h")

        st.bar_chart(pd.DataFrame({"Makespan (h)": makespans_array}))

        st.caption(
            f"Avec ±{variation_pct}% de variabilité sur les durées, le "
            f"Makespan réel a de bonnes chances de se situer entre "
            f"{makespans_array.min():.1f}h et {makespans_array.max():.1f}h, "
            f"plutôt que d'être exactement la valeur déterministe calculée "
            f"en section 1."
        )


# ============================================================
# 5️⃣ DÉCISION FINALE
# ============================================================

if "scenario_kpis" in st.session_state:

    st.divider()
    st.header("5️⃣ Décision finale")

    comparison = st.session_state["comparison"]
    scenario_label = st.session_state["scenario_label"]
    recommendation = comparison["recommendation"]

    if recommendation == "SCÉNARIO FAVORABLE":
        st.success(f"✅ {recommendation}")
    elif recommendation == "SCÉNARIO À ÉTUDIER":
        st.warning(f"⚠️ {recommendation}")
    else:
        st.error(f"❌ {recommendation}")

    st.markdown(generate_decision_sentence(comparison, scenario_label))

    st.subheader("💰 Analyse économique")

    economics = compute_economic_analysis(
        baseline_kpis,
        scenario_kpis,
        st.session_state.get("scenario_cost", 0),
        hourly_production_value,
        hourly_delay_cost,
    )

    e1, e2, e3 = st.columns(3)

    e1.metric("Investissement", f"{economics['cost']:,.0f} DH")
    e2.metric("Gain financier estimé", f"{economics['financial_gain']:,.0f} DH")

    if economics["roi_pct"] is not None:
        e3.metric("ROI", f"{economics['roi_pct']:+.0f} %")
    else:
        e3.metric("ROI", "—")

    if economics["cost"] > 0:
        if economics["net_gain"] > 0:
            st.success(
                f"✅ Investissement rentable : gain net estimé de "
                f"**{economics['net_gain']:,.0f} DH** après déduction du coût "
                f"({economics['makespan_gain_hours']:.1f}h de Makespan et "
                f"{economics['delay_gain_hours']:.1f}h de retard économisées)."
            )
        else:
            st.warning(
                f"⚠️ Sur la base des paramètres actuels, le gain financier estimé "
                f"({economics['financial_gain']:,.0f} DH) ne couvre pas "
                f"l'investissement ({economics['cost']:,.0f} DH)."
            )

    st.caption(
        "💡 Estimation basée sur les paramètres économiques réglables dans la "
        "barre latérale (valeur horaire de production, coût horaire de retard). "
        "Ajuste-les pour refléter la réalité de ton contexte industriel."
    )

    if "mc_results" in st.session_state:
        mc = st.session_state["mc_results"]
        st.caption(
            f"🎲 Pour rappel, l'analyse Monte Carlo ({mc['n_valid']} simulations, "
            f"±{mc['variation_pct']}% de variabilité) montre que le Makespan réel "
            f"de la situation actuelle peut varier entre "
            f"{mc['makespans'].min():.1f}h et {mc['makespans'].max():.1f}h — "
            f"à garder en tête pour relativiser la précision du chiffre déterministe "
            f"ci-dessus."
        )
    else:
        st.caption(
            "💡 Lance l'analyse Monte Carlo (section 4️⃣) pour connaître la "
            "fourchette de risque associée à ce résultat."
        )

else:
    st.divider()
    st.header("5️⃣ Décision finale")
    st.info(
        "Optimise la situation actuelle puis simule un scénario "
        "(sections 1️⃣ et 2️⃣) pour obtenir une décision finale."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Industrial Decision Simulator — "
    "Système digital d'aide à la décision industrielle"
)